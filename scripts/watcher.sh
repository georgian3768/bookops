#!/usr/bin/env bash

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$DIR/config.json"
INGEST="$DIR/scripts/ingest.py"

ts() {
    date "+%Y-%m-%d %H:%M:%S"
}

notify() {
    if command -v notify-send &>/dev/null; then
        notify-send --urgency=critical "BookOps Watcher" "$1" 2>/dev/null || true
    fi
}

load_config() {
    eval "$(
        python3 -c "
import json, os, sys
try:
    with open('$CONFIG') as f:
        c = json.load(f)
    inc = os.path.expanduser(c.get('incoming', ''))
    mr  = os.path.expanduser(c.get('manual_review', ''))
    gdr = c.get('gdrive_remote_path', '')
    print('INCOMING_DIR={}; MANUAL_REVIEW={}; GDRIVE_REMOTE={};'.format(
        repr(inc), repr(mr), repr(gdr)))
except Exception as e:
    print(e, file=sys.stderr)
    sys.exit(2)
" || {
        echo "[$(ts)] [ERROR] Failed to read configuration" >&2
        exit 2
    }
    )"

    if [[ -z "$INCOMING_DIR" || -z "$MANUAL_REVIEW" || -z "$GDRIVE_REMOTE" ]]; then
        echo "[$(ts)] [ERROR] One or more required config keys are empty" >&2
        exit 2
    fi
}

preflight() {
    if ! command -v rclone &>/dev/null; then
        echo "[$(ts)] [ERROR] rclone binary not found. Is it installed?" >&2
        notify "rclone binary not found"
        exit 3
    fi

    if ! rclone lsd "$GDRIVE_REMOTE" &>/dev/null; then
        echo "[$(ts)] [ERROR] Cannot reach remote path: $GDRIVE_REMOTE" >&2
        notify "Cannot reach remote: $GDRIVE_REMOTE"
        exit 3
    fi

    mkdir -p "$INCOMING_DIR" "$MANUAL_REVIEW"
}

process_incoming() {
    local file
    while IFS= read -r -d '' file; do
        echo "[$(ts)] [INFO] Cloud discovery detected file: $file"
        if python3 "$INGEST" "$file"; then
            echo "[$(ts)] [INFO] Successfully ingested: $file"
        else
            echo "[$(ts)] [WARN] Ingestion failed for: $file" >&2
        fi
    done < <(find "$INCOMING_DIR" -maxdepth 1 -type f -print0 2>/dev/null)
}

load_config
preflight

echo "[$(ts)] [INFO] BookOps watcher started"
echo "[$(ts)] [INFO] Watching remote: $GDRIVE_REMOTE -> $INCOMING_DIR"

while true; do
    if rclone copy "$GDRIVE_REMOTE" "$INCOMING_DIR" 2>/dev/null; then
        process_incoming
    else
        echo "[$(ts)] [WARN] Cloud sync unreachable. Retrying..." >&2
    fi

    sleep 10
done
