#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
SENT_FILE = os.path.join(SCRIPT_DIR, ".bookops_usb_sent_ids")
KINDLE_DOCS = "documents"


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def log(level, message):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("[{}] [{}] {}".format(ts, level, message))


def load_config(path):
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except FileNotFoundError:
        eprint("[ERROR] Configuration file not found: {}".format(path))
        sys.exit(2)
    except json.JSONDecodeError as exc:
        eprint("[ERROR] Configuration file malformed: {}".format(exc))
        sys.exit(2)


def run_cmd(cmd, label, timeout=120):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            log("WARN", "{}: {}".format(label, result.stderr.strip()))
            return False, ""
        return True, result.stdout.strip()
    except FileNotFoundError:
        log("ERROR", "{}: command not found".format(label))
        return False, ""
    except subprocess.TimeoutExpired:
        log("ERROR", "{}: timed out".format(label))
        return False, ""
    except Exception as exc:
        log("ERROR", "{}: {}".format(label, exc))
        return False, ""


def print_header(phase):
    print()
    print("[--- {} ---]".format(phase))


def print_pass(message):
    print("  [\033[92m\u2713\033[0m] {}".format(message))


def print_fail(message):
    print("  [\033[91m\u2717\033[0m] {}".format(message))


def print_info(message):
    print("  [\033[94mi\033[0m] {}".format(message))


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


def scan_kindle(mount_point):
    print_header("Kindle Library")

    docs_dir = os.path.join(mount_point, KINDLE_DOCS)
    kindle_files = set()

    for root, dirs, files in os.walk(docs_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in (".azw3", ".mobi", ".epub", ".azw"):
                kindle_files.add(f)

    print_pass("{} book files found on device".format(len(kindle_files)))
    return kindle_files


def check_calibre_lock():
    try:
        result = subprocess.run(
            ["pgrep", "-x", "calibre"], capture_output=True, timeout=5
        )
        if result.returncode == 0:
            print_fail("Calibre GUI is running")
            print_info("Close calibre first to avoid database locks")
            sys.exit(3)
    except Exception:
        pass


def get_calibre_books(library_path):
    print_header("Calibre Library")
    check_calibre_lock()
    ok, output = run_cmd(
        ["calibredb", "list", "--library-path=" + library_path,
         "--fields=id,title,authors", "--for-machine"],
        "calibredb list", timeout=30
    )
    if not ok:
        print_fail("Could not query Calibre database")
        print_info("Make sure calibre GUI is closed and the library is accessible")
        sys.exit(1)

    try:
        books = json.loads(output)
    except json.JSONDecodeError as exc:
        print_fail("Failed to parse Calibre output: {}".format(exc))
        sys.exit(1)

    print_pass("{} books in library".format(len(books)))
    return books


def normalize_name(name):
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def match_books(calibre_books, kindle_files, force=False):
    print_header("Matching")

    sent_ids = set()
    if not force and os.path.isfile(SENT_FILE):
        with open(SENT_FILE, "r") as fh:
            for line in fh:
                line = line.strip()
                if line.isdigit():
                    sent_ids.add(int(line))

    kindle_normalized = set()
    for fname in kindle_files:
        stem = os.path.splitext(fname)[0]
        norm = normalize_name(stem)
        kindle_normalized.add(norm)

    to_sync = []
    already_on_kindle = 0
    already_sent = 0

    for book in calibre_books:
        bid = book["id"]
        title = book.get("title", "")
        authors = book.get("authors", "")

        if not force and bid in sent_ids:
            already_sent += 1
            continue

        norm_title = normalize_name(title)
        matched = False
        for kn in kindle_normalized:
            if norm_title in kn or kn in norm_title:
                matched = True
                break

        if not force and matched:
            already_on_kindle += 1
        else:
            to_sync.append(book)

    if not force and already_sent > 0:
        print_info("{} books previously synced (sent IDs)".format(already_sent))
    if not force and already_on_kindle > 0:
        print_info("{} books already present on Kindle".format(already_on_kindle))
    if not to_sync:
        print_pass("No new books to sync")
        sys.exit(0)

    print_pass("{} new books to sync".format(len(to_sync)))
    return to_sync


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


def extract_cover_from_epub(epub_path, output_dir):
    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            images = [n for n in zf.namelist() if n.lower().endswith((".jpg", ".jpeg", ".png"))]
            images.sort(key=lambda n: 0 if "cover" in n.lower() else 1)
            if images:
                data = zf.read(images[0])
                ext = os.path.splitext(images[0])[1]
                out = os.path.join(output_dir, "cover" + ext)
                with open(out, "wb") as f:
                    f.write(data)
                if os.path.getsize(out) > 1000:
                    return out
        return None
    except Exception:
        return None


def fetch_cover_online(title, authors, output_dir):
    query = urllib.parse.urlencode({"q": "{} {}".format(title, authors)})
    url = "https://openlibrary.org/search.json?" + query
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BookOps/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        docs = data.get("docs", [])
        if not docs:
            return None

        cover_i = docs[0].get("cover_i")
        if not cover_i:
            return None

        cover_url = "https://covers.openlibrary.org/b/id/{}-L.jpg".format(cover_i)
        cover_path = os.path.join(output_dir, "cover.jpg")
        cover_req = urllib.request.Request(cover_url, headers={"User-Agent": "BookOps/1.0"})
        with urllib.request.urlopen(cover_req, timeout=10) as cresp:
            with open(cover_path, "wb") as cfh:
                cfh.write(cresp.read())

        if os.path.getsize(cover_path) > 1000:
            return cover_path
        return None
    except Exception:
        return None


def fetch_cover_from_calibre(bid, library_path, output_dir):
    cover_path = os.path.join(output_dir, "calibre_cover.jpg")
    try:
        result = subprocess.run(
            ["calibredb", "cover", str(bid), "--library-path=" + library_path],
            capture_output=True, timeout=15
        )
        if result.returncode == 0 and len(result.stdout) > 1000:
            with open(cover_path, "wb") as f:
                f.write(result.stdout)
            return cover_path
    except Exception:
        pass
    return None


def convert_to_azw3(epub_path, output_dir, kindle_profile, cover_path=None):
    azw3_path = os.path.join(output_dir, "output.azw3")
    cmd = ["ebook-convert", epub_path, azw3_path,
           "--output-profile=" + kindle_profile]
    if cover_path:
        cmd.append("--cover=" + cover_path)
    ok, _ = run_cmd(cmd, "ebook-convert", timeout=300)
    if ok and os.path.isfile(azw3_path):
        return azw3_path
    return None


def sync_books(to_sync, library_path, mount_point, kindle_profile):
    print_header("Syncing {} books".format(len(to_sync)))

    kindle_docs = os.path.join(mount_point, KINDLE_DOCS)
    total = len(to_sync)
    any_failed = False

    for idx, book in enumerate(to_sync, 1):
        bid = book["id"]
        title = book.get("title", "")
        authors = book.get("authors", "")
        label = "{} - {}".format(title, authors)
        print()
        print_info("[{}/{}] {}".format(idx, total, label))

        with tempfile.TemporaryDirectory(prefix="bookops_usb_") as tmpdir:
            ok, _ = run_cmd(
                ["calibredb", "export", str(bid),
                 "--library-path=" + library_path,
                 "--to-dir=" + tmpdir,
                 "--formats=azw3,mobi,kfx,epub,pdf",
                 "--dont-write-opf"],
                "calibredb export", timeout=120
            )
            if not ok:
                print_fail("Export failed for ID {}".format(bid))
                any_failed = True
                continue

            exported = []
            for root, dirs, files in os.walk(tmpdir):
                for f in files:
                    exported.append(os.path.join(root, f))

            azw3_file = None
            mobi_file = None
            kfx_file = None
            pdf_file = None
            epub_file = None

            for fp in exported:
                ext = os.path.splitext(fp)[1].lower()
                if ext == ".azw3":
                    azw3_file = fp
                elif ext == ".mobi":
                    mobi_file = fp
                elif ext == ".kfx":
                    kfx_file = fp
                elif ext == ".pdf":
                    pdf_file = fp
                elif ext == ".epub":
                    epub_file = fp

            target_file = None

            if azw3_file:
                target_file = azw3_file
                target_ext = ".azw3"
                print_pass("Format: AZW3 (already Kindle-ready)")
            elif mobi_file:
                target_file = mobi_file
                target_ext = ".mobi"
                print_pass("Format: MOBI (already Kindle-ready)")
            elif kfx_file:
                target_file = kfx_file
                target_ext = ".kfx"
                print_pass("Format: KFX (already Kindle-ready)")
            elif pdf_file:
                target_file = pdf_file
                target_ext = ".pdf"
                print_pass("Format: PDF (already Kindle-ready)")
            elif epub_file:
                print_info("Format: EPUB (converting to AZW3)...")
                conv_dir = tempfile.mkdtemp(prefix="bookops_conv_")
                try:
                    cover_path = extract_cover_from_epub(epub_file, conv_dir)
                    if cover_path:
                        print_pass("Cover extracted from EPUB")
                    else:
                        print_info("No cover in EPUB, checking Calibre...")
                        cover_path = fetch_cover_from_calibre(bid, library_path, conv_dir)
                        if cover_path:
                            print_pass("Cover found in Calibre library")
                        else:
                            print_info("No cover in Calibre, searching Open Library...")
                            cover_path = fetch_cover_online(title, authors, conv_dir)
                            if cover_path:
                                print_pass("Cover downloaded from Open Library")
                            else:
                                print_info("No cover found from any source")

                    azw3_path = convert_to_azw3(epub_file, conv_dir, kindle_profile, cover_path)
                    if azw3_path:
                        if cover_path:
                            print_pass("Cover embedded in AZW3")
                        target_file = azw3_path
                        dest_name = "{}.azw3".format(label)
                        dest_name = re.sub(r'[\x00-\x1f\/:*?"<>|]', "_", dest_name)
                        dest_path = os.path.join(kindle_docs, dest_name)
                        try:
                            shutil.copy2(target_file, dest_path)
                            print_pass("Copied to Kindle: {}".format(dest_name))
                        except OSError as exc:
                            print_fail("Failed to copy to Kindle: {}".format(exc))
                            any_failed = True
                            continue
                    else:
                        print_fail("EPUB to AZW3 conversion failed")
                        target_file = epub_file
                        dest_name = "{}.epub".format(label)
                        dest_name = re.sub(r'[\x00-\x1f\/:*?"<>|]', "_", dest_name)
                        dest_path = os.path.join(kindle_docs, dest_name)
                        try:
                            shutil.copy2(target_file, dest_path)
                            print_pass("Copied to Kindle (EPUB fallback): {}".format(dest_name))
                        except OSError as exc:
                            print_fail("Failed to copy EPUB to Kindle: {}".format(exc))
                            any_failed = True
                            continue
                finally:
                    try:
                        shutil.rmtree(conv_dir, ignore_errors=True)
                    except OSError:
                        pass
                with open(SENT_FILE, "a") as fh:
                    fh.write("{}\n".format(bid))
                continue
            else:
                print_fail("No supported format found for book ID {}".format(bid))
                any_failed = True
                continue

            if target_file and os.path.isfile(target_file):
                dest_name = "{}{}".format(label, target_ext)
                dest_name = re.sub(r'[\x00-\x1f\/:*?"<>|]', "_", dest_name)
                dest_path = os.path.join(kindle_docs, dest_name)
                try:
                    shutil.copy2(target_file, dest_path)
                    print_pass("Copied to Kindle: {}".format(dest_name))
                except OSError as exc:
                    print_fail("Failed to copy to Kindle: {}".format(exc))
                    any_failed = True
                    continue

        with open(SENT_FILE, "a") as fh:
            fh.write("{}\n".format(bid))

    print()

    if any_failed:
        log("ERROR", "One or more books failed to sync")
        sys.exit(3)

    log("INFO", "All {} books synced successfully".format(total))


def refresh_covers(library_path):
    print_header("Refreshing Covers in Calibre")
    check_calibre_lock()

    ok, output = run_cmd(
        ["calibredb", "list", "--library-path=" + library_path,
         "--fields=id,title,authors", "--for-machine"],
        "calibredb list", timeout=30
    )
    if not ok:
        print_fail("Could not query Calibre database")
        sys.exit(1)

    try:
        books = json.loads(output)
    except json.JSONDecodeError as exc:
        print_fail("Failed to parse Calibre output: {}".format(exc))
        sys.exit(1)

    updated = 0
    for book in books:
        bid = book["id"]
        title = book.get("title", "")
        authors = book.get("authors", "")
        print_info("[{}] {} - {}".format(bid, title, authors))

        with tempfile.TemporaryDirectory(prefix="bookops_cover_") as tmpdir:
            cover = fetch_cover_online(title, authors, tmpdir)
            if cover:
                ok, _ = run_cmd(
                    ["calibredb", "set_metadata", str(bid),
                     "--library-path=" + library_path,
                     "--field=cover:" + cover],
                    "calibredb set_metadata", timeout=30
                )
                if ok:
                    print_pass("Cover updated")
                    updated += 1
                else:
                    print_info("Failed to set cover")
            else:
                print_info("No cover found online")

    print()
    print_pass("Updated covers for {} / {} books".format(updated, len(books)))


def main():
    try:
        import urllib.parse
    except ImportError:
        pass

    force = "--force" in sys.argv
    refresh = "--refresh-covers" in sys.argv

    config = load_config(CONFIG_PATH)
    library_path = os.path.expanduser(config.get("calibre_library", ""))
    kindle_profile = config.get("kindle_model", "kindle_pw3")

    if not library_path or not os.path.isdir(library_path):
        print_fail("Calibre library not found: {}".format(library_path))
        sys.exit(1)

    if refresh:
        refresh_covers(library_path)
        if os.path.isfile(SENT_FILE):
            os.remove(SENT_FILE)
            print_info("Cleared sent IDs file")
        print_info("Cover refresh complete. Run 'bookops usb-sync --force' to sync.")
        sys.exit(0)

    mount_point = detect_kindle()
    kindle_files = scan_kindle(mount_point)
    calibre_books = get_calibre_books(library_path)
    to_sync = match_books(calibre_books, kindle_files, force=force)

    if to_sync:
        sync_books(to_sync, library_path, mount_point, kindle_profile)
    else:
        print_pass("Nothing to sync")

    unmount_kindle(mount_point)
    sys.exit(0)


if __name__ == "__main__":
    main()
