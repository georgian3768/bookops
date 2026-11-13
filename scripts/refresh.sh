#!/usr/bin/env bash
set -o errexit
set -o nounset

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

ts() {
    date "+%Y-%m-%d %H:%M:%S"
}

echo "[$(ts)] [INFO] BookOps refresh started"

echo "[$(ts)] [INFO] Step 1: Refreshing covers in Calibre..."
python3 "$DIR/usb_sync.py" --refresh-covers

echo "[$(ts)] [INFO] Step 2: Force-syncing all books to Kindle..."
python3 "$DIR/usb_sync.py" --force

echo "[$(ts)] [INFO] BookOps refresh complete"