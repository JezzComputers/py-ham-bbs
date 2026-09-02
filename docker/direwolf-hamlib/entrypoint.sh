#!/bin/sh
set -e

RED='\033[0;31m'
NC='\033[0m'

# Start rigctld in the background
# rigctld -m 3085 -r /dev/ttyACM0 -s 115200 -T 127.0.0.1 -t 4532 &
# rigctld -m 1 -r /dev/null -T 127.0.0.1 -t 4532 &
rigctld -m 1 -r /dev/null -T 0.0.0.0 -t 4532 &
RIGCTLD_PID=$!

# Kill rigctld if this script exits/dies for any reason
trap 'kill "$RIGCTLD_PID" 2>/dev/null' EXIT INT TERM

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

# Start Direwolf in the foreground (PID 1)
exec direwolf -c /etc/direwolf/direwolf.conf
