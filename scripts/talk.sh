#!/usr/bin/env bash
# Speak a question at the server and hear the answer. Phase 3 test harness --
# this is what the Reachy Mini client replaces in Phase 5.
#
#   ./scripts/talk.sh            private mode (default), 6 seconds
#   ./scripts/talk.sh public     public mode
#   ./scripts/talk.sh private 10 record for 10 seconds
set -euo pipefail

cd "$(dirname "$0")/.."

MODE="${1:-private}"
SECONDS_TO_RECORD="${2:-6}"

case "$MODE" in
  private) ENDPOINT=private/ask ;;
  public)  ENDPOINT=ask ;;
  *) echo "usage: $0 [private|public] [seconds]" >&2; exit 1 ;;
esac

for tool in arecord aplay curl jq; do
  command -v "$tool" >/dev/null || {
    echo "Missing $tool. Install with: sudo apt install -y alsa-utils jq" >&2
    exit 1
  }
done

# Recordings and spoken answers stay inside the repo's data dir rather than the
# shared /tmp -- on the private path this audio is exactly what must not leak.
WORK=data/tmp
mkdir -p "$WORK"
chmod 700 "$WORK"
trap 'rm -f "$WORK"/turn.*.wav' EXIT

printf '\n\033[1m[%s] listening for %ss...\033[0m\n' "$MODE" "$SECONDS_TO_RECORD"
arecord -q -f S16_LE -r 16000 -c 1 -d "$SECONDS_TO_RECORD" "$WORK/turn.in.wav"

QUESTION=$(curl -fsS -X POST localhost:8001/transcribe \
  -H 'content-type: audio/wav' --data-binary "@$WORK/turn.in.wav" | jq -r .text)

if [ -z "$QUESTION" ] || [ "$QUESTION" = "null" ]; then
  echo "Heard nothing. Check the mic with: arecord -l" >&2
  exit 1
fi
printf '\033[2myou:\033[0m       %s\n' "$QUESTION"

REPLY=$(curl -fsS -X POST "localhost:8000/$ENDPOINT" \
  -H 'content-type: application/json' \
  -d "$(jq -nc --arg q "$QUESTION" '{question:$q}')")

ANSWER=$(printf '%s' "$REPLY" | jq -r .answer)
SOURCE=$(printf '%s' "$REPLY" | jq -r .source)
printf '\033[2m%s:\033[0m %s\n' "$SOURCE" "$ANSWER"

curl -fsS -X POST localhost:8001/speak \
  -H 'content-type: application/json' \
  -d "$(jq -nc --arg t "$ANSWER" '{text:$t}')" -o "$WORK/turn.out.wav"

aplay -q "$WORK/turn.out.wav"
