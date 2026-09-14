#!/usr/bin/env bash
# Pre-render the spoken mode confirmations.
#
# These play before the mic opens, so they must be instant -- playing a file is
# ~50ms against ~500ms to synthesise on the spot. They are also spoken by local
# Piper on every mode, including the cloud ones: a confirmation that depends on
# the network is exactly the confirmation you cannot trust.
set -euo pipefail

cd "$(dirname "$0")/.."

OUT=data/sounds
mkdir -p "$OUT"

render() {
  local name="$1" phrase="$2"
  curl -fsS -X POST localhost:8001/speak \
    -H 'content-type: application/json' \
    -d "$(jq -nc --arg t "$phrase" '{text:$t}')" \
    -o "$OUT/$name.wav"
  printf '  %-14s %s\n' "$name.wav" "\"$phrase\""
}

echo "Rendering mode confirmations to $OUT"
render saturn     "Private mode activated."
render hey-mando  "Yes?"
render mando-live "Chat mode. Cloud is listening."
render chat-ended "Chat ended."

echo
echo "Listen to them:  for f in $OUT/*.wav; do aplay -q \$f; sleep 0.4; done"
