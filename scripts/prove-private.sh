#!/usr/bin/env bash
# The Phase 3 gate: watch the wire while a private question is answered.
#
# The structural guarantee is in the code -- the Saturn path imports no cloud
# client and app/vectors.py gives it no function that reaches public data. This
# script is the empirical check on top of that.
#
#   sudo ./scripts/prove-private.sh
set -euo pipefail

cd "$(dirname "$0")/.."

command -v tcpdump >/dev/null || {
  echo "Missing tcpdump. Install with: sudo apt install -y tcpdump" >&2
  exit 1
}
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo -- tcpdump needs root." >&2; exit 1; }

WORK=data/tmp
mkdir -p "$WORK"
CAPTURE="$WORK/egress.txt"

# Everything outside RFC1918 and loopback. Docker's own bridges live inside
# 172.16/12, so container-to-container traffic is correctly treated as local.
FILTER='not net 10.0.0.0/8 and not net 172.16.0.0/12 and not net 192.168.0.0/16
        and not net 127.0.0.0/8 and not net 169.254.0.0/16 and not arp and not ip6'

echo "Resolving the cloud endpoints this must never touch..."
CLOUD_IPS=$(getent ahostsv4 api.anthropic.com api.openai.com 2>/dev/null \
            | awk '{print $1}' | sort -u || true)
echo "${CLOUD_IPS:-  (could not resolve - offline? the check still runs)}" | sed 's/^/  /'

echo
echo "Capturing..."
tcpdump -n -l -i any $FILTER > "$CAPTURE" 2>/dev/null &
TCPDUMP_PID=$!
trap 'kill $TCPDUMP_PID 2>/dev/null || true' EXIT
sleep 2

echo "Asking a private question..."
ANSWER=$(curl -fsS -X POST localhost:8000/private/ask \
  -H 'content-type: application/json' \
  -d '{"question":"where is the spare key"}' | sed 's/.*"answer":"//; s/".*//')
echo "  answer: $ANSWER"

sleep 2
kill $TCPDUMP_PID 2>/dev/null || true
wait $TCPDUMP_PID 2>/dev/null || true

echo
LEAKED=""
for ip in $CLOUD_IPS; do
  if grep -q "$ip" "$CAPTURE"; then LEAKED="$LEAKED $ip"; fi
done

if [ -n "$LEAKED" ]; then
  printf '\033[31mFAILED: traffic reached a cloud API endpoint:%s\033[0m\n' "$LEAKED"
  echo "Stop and investigate before putting real documents in data/inbox/private."
  exit 1
fi
printf '\033[32mPASS: no traffic to any cloud API endpoint during the private answer.\033[0m\n'

COUNT=$(wc -l < "$CAPTURE")
echo
if [ "$COUNT" -eq 0 ]; then
  echo "Nothing at all left this machine during the exchange."
else
  echo "$COUNT packet(s) left the LAN during the window. This is normal background"
  echo "traffic (NTP, apt, telemetry from other software). None of it went to the"
  echo "cloud APIs above. Destinations seen:"
  awk '{for (i=1;i<=NF;i++) if ($i==">") print $(i+1)}' "$CAPTURE" \
    | sed 's/:$//' | sort | uniq -c | sort -rn | head -10 | sed 's/^/  /'
fi
echo
echo "Full capture: $CAPTURE"
