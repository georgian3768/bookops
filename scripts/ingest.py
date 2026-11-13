#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

SUPPORTED_FORMATS = {".epub", ".mobi", ".azw3"}


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


def run_cmd(cmd, label):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log("ERROR", "{} failed: {}".format(label, result.stderr.strip()))
            return False
        return True
    except FileNotFoundError:
        log("ERROR", "{} command not found on system".format(label))
        return False
    except Exception as exc:
        log("ERROR", "{} unexpected error: {}".format(label, exc))
        return False


def main():
    if len(sys.argv) < 2:
        eprint("Usage: {} <path-to-book>".format(sys.argv[0]))
        sys.exit(1)

    book_path = os.path.abspath(sys.argv[1])

    if not os.path.isfile(book_path):
        log("ERROR", "File not found: {}".format(book_path))
        sys.exit(1)

    try:
        if subprocess.run(["pgrep", "-x", "calibre"], capture_output=True, timeout=5).returncode == 0:
            log("ERROR", "Calibre GUI is running. Close it first to avoid database locks.")
            sys.exit(3)
    except Exception:
        pass

    config = load_config(CONFIG_PATH)
    incoming = os.path.expanduser(config.get("incoming", ""))
    manual_review = os.path.expanduser(config.get("manual_review", ""))
    calibre_library = os.path.expanduser(config.get("calibre_library", ""))
    convert_pdfs = config.get("convert_pdfs", False)

    ext = os.path.splitext(book_path)[1].lower()
    log("INFO", "Processing: {} (type: {})".format(book_path, ext))

    added_to_calibre = False

    if ext in SUPPORTED_FORMATS:
        log("INFO", "Adding {} to Calibre library...".format(ext))
        if run_cmd(["calibredb", "add", "--with-library", calibre_library, book_path], "calibredb"):
            added_to_calibre = True
        else:
            sys.exit(3)

    elif ext == ".pdf":
        if convert_pdfs:
            epub_path = os.path.splitext(book_path)[0] + ".epub"
            log("INFO", "Converting PDF to EPUB...")
            ok = run_cmd(
                ["ebook-convert", book_path, epub_path], "ebook-convert"
            )
            if ok:
                log("INFO", "Adding converted EPUB to Calibre library...")
                if run_cmd(["calibredb", "add", "--with-library", calibre_library, epub_path], "calibredb"):
                    added_to_calibre = True
                    try:
                        if os.path.exists(epub_path):
                            os.remove(epub_path)
                            log("INFO", "Cleaned up temporary EPUB: {}".format(epub_path))
                    except OSError as exc:
                        log("WARN", "Could not remove temp EPUB: {}".format(exc))
                else:
                    sys.exit(3)
            else:
                log("WARN", "PDF conversion failed. Quarantining to manual_review.")
                _quarantine(book_path, manual_review)
                sys.exit(3)
        else:
            log(
                "WARN",
                "PDF conversion disabled in config. Quarantining to manual_review.",
            )
            _quarantine(book_path, manual_review)
            sys.exit(1)
    else:
        log("ERROR", "Unsupported file extension: {}".format(ext))
        sys.exit(1)

    if added_to_calibre:
        _cleanup_source(book_path, incoming)

    log("INFO", "Done.")
    sys.exit(0)


def _quarantine(book_path, manual_review):
    if not manual_review:
        log("ERROR", "manual_review path not configured")
        return
    os.makedirs(manual_review, exist_ok=True)
    dest = os.path.join(manual_review, os.path.basename(book_path))
    try:
        shutil.move(book_path, dest)
        log("INFO", "Moved to manual_review: {}".format(dest))
    except OSError as exc:
        log("ERROR", "Failed to quarantine file: {}".format(exc))


def _cleanup_source(book_path, incoming):
    if os.path.dirname(book_path) != incoming:
        log(
            "WARN",
            "Source file not in incoming directory; skipping deletion: {}".format(
                book_path
            ),
        )
        return
    try:
        os.remove(book_path)
        log("INFO", "Removed source file: {}".format(book_path))
    except OSError as exc:
        log("WARN", "Could not remove source file: {}".format(exc))


if __name__ == "__main__":
    main()
