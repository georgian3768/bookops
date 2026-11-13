#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

REQUIRED_BINARIES = ["rclone", "calibredb", "ebook-convert"]
EMAIL_BINARIES = ["msmtp"]
REQUIRED_DIRECTORIES = ["incoming", "manual_review", "calibre_library"]


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


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


def check_binaries(config):
    all_found = True
    print("--- System Dependencies ---")

    for name in REQUIRED_BINARIES:
        if shutil.which(name):
            print("  [\033[92m✓\033[0m] {} found".format(name))
        else:
            print("  [\033[91m✗\033[0m] {} not found".format(name))
            all_found = False

    email_found = any(shutil.which(b) for b in EMAIL_BINARIES)
    if email_found:
        found_one = next(b for b in EMAIL_BINARIES if shutil.which(b))
        print("  [\033[92m✓\033[0m] Email transport found ({})".format(found_one))
    else:
        print(
            "  [\033[94mi\033[0m] No email transport found (checked: {}); "
            "optional, needed for ./bookops sync".format(", ".join(EMAIL_BINARIES))
        )

    return all_found


def check_directories(config):
    all_exist = True
    print("\n--- Directory Paths ---")

    for key in REQUIRED_DIRECTORIES:
        raw_path = config.get(key, "")
        expanded = os.path.expanduser(raw_path)
        if os.path.isdir(expanded):
            print("  [\033[92m✓\033[0m] {} -> {}".format(key, expanded))
        else:
            print("  [\033[91m✗\033[0m] {} -> {} (missing)".format(key, expanded))
            all_exist = False

    msmtp_config = os.path.join(SCRIPT_DIR, "msmtprc.local")
    if os.path.isfile(msmtp_config):
        print("  [\033[92m✓\033[0m] msmtprc.local found")
    else:
        print(
            "  [\033[94mi\033[0m] msmtprc.local not found (expected at {}); "
            "optional, needed for ./bookops sync".format(msmtp_config)
        )

    return all_exist


def check_remote(config):
    ok = True
    print("\n--- Cloud Remote ---")

    remote = config.get("gdrive_remote_path", "")
    if not remote:
        print("  [\033[91m✗\033[0m] gdrive_remote_path not set in config")
        return False

    try:
        result = subprocess.run(
            ["rclone", "lsd", remote],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            print("  [\033[92m✓\033[0m] Remote reachable: {}".format(remote))
        else:
            print("  [\033[91m✗\033[0m] Remote unreachable: {} ({})".format(
                remote, result.stderr.strip()))
            ok = False
    except FileNotFoundError:
        print("  [\033[91m✗\033[0m] rclone binary not found (cannot verify remote)")
        ok = False
    except subprocess.TimeoutExpired:
        print("  [\033[91m✗\033[0m] Remote check timed out: {}".format(remote))
        ok = False
    except Exception as exc:
        print("  [\033[91m✗\033[0m] Remote check failed: {}".format(exc))
        ok = False

    return ok


def main():
    try:
        config = load_config(CONFIG_PATH)

        bins_ok = check_binaries(config)
        dirs_ok = check_directories(config)
        remote_ok = check_remote(config)

        print()
        if bins_ok and dirs_ok and remote_ok:
            print("[\033[92m✓\033[0m] All checks passed.")
            sys.exit(0)
        else:
            print("[\033[91m✗\033[0m] Some checks failed.")
            sys.exit(3)
    except Exception as exc:
        eprint("[ERROR] Unexpected error: {}".format(exc))
        sys.exit(3)


if __name__ == "__main__":
    main()
