#!/usr/bin/env python3
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KINDLE_DOCS = "documents"


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def log(level, message):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("[{}] [{}] {}".format(ts, level, message))


def print_header(phase):
    print()
    print("[--- {} ---]".format(phase))


def print_pass(message):
    print("  [\033[92m\u2713\033[0m] {}".format(message))


def print_fail(message):
    print("  [\033[91m\u2717\033[0m] {}".format(message))


def print_info(message):
    print("  [\033[94mi\033[0m] {}".format(message))


def run_cmd(cmd, label, timeout=30):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout.strip()
    except Exception:
        return False, ""


def detect_kindle():
    print_header("Kindle Detection")

    user = os.environ.get("USER", "")
    candidates = [
        "/media/{}/Kindle".format(user),
        "/run/media/{}/Kindle".format(user),
        "/mnt/Kindle",
    ]

    for path in candidates:
        if os.path.isdir(os.path.join(path, KINDLE_DOCS)):
            print_pass("Kindle detected at {}".format(path))
            return path

    print_info("Kindle not mounted. Scanning for device...")

    ok, output = run_cmd(
        ["lsblk", "-o", "NAME,LABEL,FSTYPE", "-n", "-r"],
        "lsblk", timeout=10
    )
    if ok:
        kindle_dev = None
        for line in output.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3 and parts[1].upper() == "KINDLE" and parts[2] == "vfat":
                kindle_dev = parts[0]
                break

        if kindle_dev:
            print_info("Found Kindle device: /dev/{}".format(kindle_dev))
            ok2, _ = run_cmd(
                ["udisksctl", "mount", "-b", "/dev/{}".format(kindle_dev)],
                "udisksctl", timeout=15
            )
            if ok2:
                for path in candidates:
                    if os.path.isdir(os.path.join(path, KINDLE_DOCS)):
                        print_pass("Mounted Kindle at {}".format(path))
                        return path

    print_fail("Could not find or mount Kindle")
    print_info("Ensure Kindle is connected via USB and unlocked")
    sys.exit(1)


def detect_kindle_device():
    ok, output = run_cmd(
        ["lsblk", "-o", "NAME,LABEL,FSTYPE", "-n", "-r"],
        "lsblk", timeout=10
    )
    if ok:
        for line in output.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3 and parts[1].upper() == "KINDLE":
                return parts[0]
    return None


def unmount_kindle(mount_point):
    kindle_dev = detect_kindle_device()
    if kindle_dev:
        ok, _ = run_cmd(
            ["udisksctl", "unmount", "-b", "/dev/{}".format(kindle_dev)],
            "udisksctl", timeout=15
        )
        if ok:
            print_pass("Kindle unmounted. Safe to disconnect.")
            return
    print_info("Could not auto-unmount. Please unmount manually before disconnecting.")


def normalize_title(name):
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def group_duplicates(kindle_mount):
    print_header("Scanning for Duplicates")

    docs_dir = os.path.join(kindle_mount, KINDLE_DOCS)
    book_files = []

    for root, dirs, files in os.walk(docs_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in (".azw3", ".mobi", ".kfx", ".epub", ".pdf", ".azw"):
                book_files.append(os.path.join(root, f))

    print_info("{} book files found".format(len(book_files)))

    groups = {}
    for fp in book_files:
        fname = os.path.basename(fp)
        stem = os.path.splitext(fname)[0]
        key = normalize_title(stem)
        if key not in groups:
            groups[key] = []
        groups[key].append(fp)

    duplicates = {k: v for k, v in groups.items() if len(v) > 1}

    if not duplicates:
        print_pass("No duplicates found")
        return []

    print_info("{} groups with duplicates".format(len(duplicates)))
    to_remove = []

    for key, files in sorted(duplicates.items()):
        print_info("Key: '{}' ({} files)".format(key, len(files)))
        for fp in files:
            print_info("  {}".format(os.path.basename(fp)))

        files.sort(key=lambda x: len(os.path.basename(x)), reverse=True)
        keeper = files[0]
        print_pass("  Keep: {}".format(os.path.basename(keeper)))
        for fp in files[1:]:
            print_info("  Remove: {}".format(os.path.basename(fp)))
            to_remove.append(fp)

    return to_remove


def main():
    mount_point = detect_kindle()
    to_remove = group_duplicates(mount_point)

    if not to_remove:
        unmount_kindle(mount_point)
        sys.exit(0)

    print()
    print_info("Removing {} duplicate files...".format(len(to_remove)))
    removed = 0
    failed = 0

    for fp in to_remove:
        try:
            os.remove(fp)
            print_pass("Deleted: {}".format(os.path.basename(fp)))
            removed += 1
        except OSError as exc:
            print_fail("Failed to delete {}: {}".format(os.path.basename(fp), exc))
            failed += 1

    print()
    if failed:
        log("ERROR", "Removed {} files, {} failed".format(removed, failed))
        sys.exit(3)

    log("INFO", "Removed {} duplicate files".format(removed))
    unmount_kindle(mount_point)
    sys.exit(0)


if __name__ == "__main__":
    main()