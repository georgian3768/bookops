#!/usr/bin/env bash
set -o errexit
set -o nounset

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
CONFIG="$DIR/../config.json"
INGEST="$DIR/ingest.py"
USB_SYNC="$DIR/usb_sync.py"

ts() {
    date "+%Y-%m-%d %H:%M:%S"
}

load_config() {
    eval "$(
        python3 -c "
import json, os, sys
try:
    with open('$CONFIG') as f:
        c = json.load(f)
    inc = os.path.expanduser(c.get('incoming', ''))
    gdr = c.get('gdrive_remote_path', '')
    print('INCOMING_DIR={}; GDRIVE_REMOTE={};'.format(repr(inc), repr(gdr)))
except Exception as e:
    print(e, file=sys.stderr)
    sys.exit(2)
" || {
            echo "[$(ts)] [ERROR] Failed to read configuration" >&2
            exit 2
        }
    )"

    if [[ -z "$INCOMING_DIR" || -z "$GDRIVE_REMOTE" ]]; then
        echo "[$(ts)] [ERROR] One or more required config keys are empty" >&2
        exit 2
    fi
}

preflight() {
    if ! command -v rclone &>/dev/null; then
        echo "[$(ts)] [ERROR] rclone binary not found" >&2
        exit 3
    fi

    if ! rclone lsd "$GDRIVE_REMOTE" &>/dev/null; then
        echo "[$(ts)] [ERROR] Cannot reach remote path: $GDRIVE_REMOTE" >&2
        exit 3
    fi

    mkdir -p "$INCOMING_DIR"
}

echo "[$(ts)] [INFO] BookOps pipeline started"
load_config
preflight

echo "[$(ts)] [INFO] Pulling from Google Drive..."
rclone copy "$GDRIVE_REMOTE" "$INCOMING_DIR"

echo "[$(ts)] [INFO] Ingesting new books..."
for f in "$INCOMING_DIR"/*; do
    [ -f "$f" ] || continue
    echo "[$(ts)] [INFO] Processing: $f"
    python3 "$INGEST" "$f" || echo "[$(ts)] [WARN] Ingestion failed for: $f" >&2
done

echo "[$(ts)] [INFO] Syncing to Kindle via USB..."
python3 "$USB_SYNC"

echo "[$(ts)] [INFO] BookOps pipeline complete"