#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SENTINEL="$DIR/.bookops_last_sync"
SENT_FILE="$DIR/.bookops_sent_ids"
CONFIG="$DIR/config.json"
MSMTP_CONFIG="$DIR/msmtprc.local"
MSMTP_LOGFILE="$DIR/msmtp.log"

ts() {
    date "+%Y-%m-%d %H:%M:%S"
}

eval "$(
    python3 -c "
import json, sys
try:
    with open('$CONFIG') as f:
        c = json.load(f)
    ke = c.get('kindle_email', '')
    cl = c.get('calibre_library', '')
    print('KINDLE_EMAIL={}; CALIBRE_LIBRARY={};'.format(
        repr(ke), repr(cl)))
except Exception as e:
    print(e, file=sys.stderr)
    sys.exit(2)
" || {
    echo "[$(ts)] [ERROR] Failed to read configuration" >&2
    exit 2
}
)"

if [[ -z "$KINDLE_EMAIL" || -z "$CALIBRE_LIBRARY" ]]; then
    echo "[$(ts)] [ERROR] kindle_email or calibre_library is empty in config" >&2
    exit 2
fi

if [[ ! -d "$CALIBRE_LIBRARY" ]]; then
    echo "[$(ts)] [ERROR] Calibre library directory not found: $CALIBRE_LIBRARY" >&2
    exit 3
fi

if pgrep -x calibre &>/dev/null; then
    echo "[$(ts)] [ERROR] Calibre GUI is running. Close it first to avoid database locks." >&2
    exit 3
fi

LAST_SYNC=$(cat "$SENTINEL" 2>/dev/null || echo "2000-01-01")
SYNC_START=$(date +%Y-%m-%dT%H:%M:%S)

IDS=$(calibredb search "date:>=$LAST_SYNC" \
    --library-path="$CALIBRE_LIBRARY" 2>/dev/null || true)

IDS=$(echo "$IDS" | tr ',' ' ')
IDS="${IDS%"${IDS##*[![:space:]]}"}"

if [[ -z "$IDS" ]]; then
    echo "[$(ts)] [INFO] No new books to sync"
    exit 0
fi

# Filter out IDs already confirmed sent
NEW_IDS=""
for ID in $IDS; do
    if grep -q "^${ID}$" "$SENT_FILE" 2>/dev/null; then
        echo "[$(ts)] [INFO] Book ID $ID already sent, skipping"
    else
        NEW_IDS="$NEW_IDS $ID"
    fi
done
NEW_IDS="${NEW_IDS# }"

if [[ -z "$NEW_IDS" ]]; then
    echo "[$(ts)] [INFO] All books in range already sent"
    exit 0
fi

TEMP_DIR=$(mktemp -d "$DIR/.kindle_sync_XXXXXX")
trap "rm -rf '$TEMP_DIR'" EXIT

ANY_FAILED=0

for ID in $NEW_IDS; do
    echo "[$(ts)] [INFO] Exporting book ID $ID from Calibre..."
    if ! calibredb export "$ID" \
        --library-path="$CALIBRE_LIBRARY" \
        --to-dir="$TEMP_DIR" \
        --formats=epub \
        --single-dir 2>/dev/null; then
        echo "[$(ts)] [WARN] Export failed for book ID $ID, skipping" >&2
        ANY_FAILED=1
    fi
done

while IFS= read -r -d '' BOOK; do
    BOOK_NAME=$(basename "$BOOK")
    SEND_FILE="$BOOK"
    echo "[$(ts)] [INFO] Sending: $BOOK_NAME"
    (
        # msmtp adds the From header from msmtprc.local.
        echo "To: $KINDLE_EMAIL"
        echo "Subject: BookOps Sync: $BOOK_NAME"
        echo "MIME-Version: 1.0"
        echo "Content-Type: multipart/mixed; boundary=\"BOOKOPS_BOUNDARY\""
        echo ""
        echo "--BOOKOPS_BOUNDARY"
        echo "Content-Type: text/plain; charset=UTF-8"
        echo ""
        echo "Sending target book attachment: $BOOK_NAME"
        echo ""
        echo "--BOOKOPS_BOUNDARY"
        echo "Content-Type: application/octet-stream; name=\"$BOOK_NAME\""
        echo "Content-Transfer-Encoding: base64"
        echo "Content-Disposition: attachment; filename=\"$BOOK_NAME\""
        echo ""
        base64 "$SEND_FILE"
        echo ""
        echo "--BOOKOPS_BOUNDARY--"
    ) | msmtp --file="$MSMTP_CONFIG" --logfile="$MSMTP_LOGFILE" "$KINDLE_EMAIL" 2>/dev/null

    if [ ${PIPESTATUS[1]} -eq 0 ]; then
        echo "[$(ts)] [INFO] Successfully sent: $BOOK_NAME"
    else
        echo "[$(ts)] [ERROR] Failed to send: $BOOK_NAME" >&2
        ANY_FAILED=1
    fi
done < <(find "$TEMP_DIR" -type f -name "*.epub" -print0 2>/dev/null)

if [[ $ANY_FAILED -eq 0 ]]; then
    echo "$SYNC_START" > "$SENTINEL"
    for ID in $NEW_IDS; do
        echo "$ID" >> "$SENT_FILE"
    done
    echo "[$(ts)] [INFO] Sync complete"
    exit 0
else
    echo "[$(ts)] [ERROR] One or more books failed to sync" >&2
    exit 3
fi
