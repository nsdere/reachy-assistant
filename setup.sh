#!/usr/bin/env bash
# Bring the assistant up on a fresh machine. Safe to re-run.
set -euo pipefail

cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- prerequisites
command -v docker >/dev/null || fail \
"Docker is not installed. On Ubuntu:

  sudo apt update && sudo apt install -y docker.io docker-compose-v2
  sudo usermod -aG docker \$USER

Then log out and back in (the group change needs a new session) and re-run this."

docker compose version >/dev/null 2>&1 || fail \
"The docker compose plugin is missing. Install it with:

  sudo apt install -y docker-compose-v2"

docker info >/dev/null 2>&1 || fail \
"Cannot talk to the Docker daemon. Either it is not running:

  sudo systemctl enable --now docker

or your user is not in the docker group yet:

  sudo usermod -aG docker \$USER   # then log out and back in"

# ------------------------------------------------------------------------- env
if [ ! -f .env ]; then
  cp .env.example .env
  say "Created .env"
  echo "Add your Anthropic API key (from console.anthropic.com), then re-run this script."
  echo "  nano .env"
  exit 0
fi

if grep -q 'sk-ant-replace-me' .env; then
  fail "ANTHROPIC_API_KEY is still the placeholder in .env. Edit it, then re-run."
fi

mkdir -p data/inbox/private data/inbox/public

# -------------------------------------------------------------------- services
say "Starting services"
docker compose up -d --build

say "Waiting for Ollama"
for _ in $(seq 1 60); do
  if docker compose exec -T ollama ollama list >/dev/null 2>&1; then break; fi
  sleep 2
done

say "Pulling models (a few GB on first run - this is the slow part)"
docker compose exec -T ollama ollama pull nomic-embed-text
docker compose exec -T ollama ollama pull "$(grep -E '^LOCAL_MODEL=' .env | cut -d= -f2)"

say "Waiting for the orchestrator"
for _ in $(seq 1 60); do
  if curl -fsS localhost:8000/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS localhost:8000/health >/dev/null || fail \
"Orchestrator did not come up. Check: docker compose logs orchestrator"

say "Waiting for the voice service"
for _ in $(seq 1 90); do
  if curl -fsS localhost:8001/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS localhost:8001/health >/dev/null || fail \
"Voice service did not come up. Check: docker compose logs voice"

say "Loading Whisper and Piper (downloads once, then fully offline)"
curl -fsS -X POST localhost:8001/warm --max-time 900 >/dev/null || fail \
"Model load failed. Check: docker compose logs voice"

if command -v jq >/dev/null; then
  say "Rendering the spoken mode confirmations"
  ./scripts/make-confirmations.sh
else
  echo "(skipping mode confirmations - install jq, then run ./scripts/make-confirmations.sh)"
fi

# --------------------------------------------------------- privacy verification
say "Verifying the privacy boundary"
post() { curl -fsS -X POST "localhost:8000/$1" -H 'content-type: application/json' -d "$2"; }

post ingest '{"text":"The spare key is under the blue flowerpot.","source":"setup-check","private":true}' >/dev/null

if post search '{"query":"where is the spare key"}' | grep -q flowerpot; then
  fail "FAILED: a private fact was reachable from the cloud-facing search. Stop and investigate."
fi
echo "  cloud-facing search cannot see private data - OK"

if post private/ask '{"question":"where is the spare key"}' | grep -qi flowerpot; then
  echo "  local private answer works - OK"
else
  echo "  WARNING: the local model did not answer from private context."
  echo "  Usually means the model is still warming up. Retry:"
  echo "    curl -X POST localhost:8000/private/ask -H 'content-type: application/json' \\"
  echo "      -d '{\"question\":\"where is the spare key\"}'"
fi

say "Ready"
cat <<'EOF'
Add your documents:
  data/inbox/private/   Saturn only - never sent to any cloud provider
  data/inbox/public/    reachable by Hey Mando and Mando live

Then load them:
  docker compose run --rm orchestrator python -m app.ingest

Talk to it (needs a mic: sudo apt install -y alsa-utils jq):
  ./scripts/talk.sh            private mode
  ./scripts/talk.sh public     public mode

Prove the private path leaks nothing:
  sudo ./scripts/prove-private.sh

Check spend:
  curl localhost:8000/budget
EOF
