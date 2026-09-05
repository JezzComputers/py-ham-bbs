#!/bin/sh
set -e

RED='\033[0;31m'
NC='\033[0m'

RADIO_MODEL="${RADIO_MODEL:-1}"
RADIO_DEVICE="${RADIO_DEVICE:-/dev/null}"

STATUS_LOG=/tmp/direwolf-startup.log
: > "$STATUS_LOG"  # truncate fresh each start

# Start rigctld in the background
rigctld -m ${RADIO_MODEL} -r "${RADIO_DEVICE}" -s 115200 -T 0.0.0.0 -t 4532 &
RIGCTLD_PID=$!

# Wait for rigctld to bind, with a timeout
TIMEOUT=15
ELAPSED=0
until nc -z 127.0.0.1 4532; do
	sleep 0.5
	ELAPSED=$((ELAPSED + 1))
	ELAPSED_SEC=$(awk "BEGIN {print $ELAPSED * 0.5}")
	if [ "$(awk "BEGIN {print ($ELAPSED_SEC >= $TIMEOUT) ? 1 : 0}")" -eq 1 ]; then
		printf "${RED}rigctld failed to bind to port 4532 within %ss${NC}\n" "$TIMEOUT" >&2
		exit 1
	fi
done

echo "rigctld is up after ${ELAPSED_SEC:-0}s, starting direwolf"

tail -f "$STATUS_LOG" &
TAIL_PID=$!

direwolf -c /etc/direwolf/direwolf.conf > "$STATUS_LOG" 2>&1 &
DIREWOLF_PID=$!

trap 'kill "$RIGCTLD_PID" "$DIREWOLF_PID" "$TAIL_PID" 2>/dev/null' EXIT INT TERM
wait "$DIREWOLF_PID"
