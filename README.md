# reachy-assistant

Home voice assistant. Three modes, one box.

**Starting or resuming work? Read [NEXT.md](NEXT.md).** It carries the install
steps, what is left to build, and the rules that must not be quietly undone.

| Wake word | Mode | What leaves the house |
|---|---|---|
| `Mando live` | GPT-Live conversation | live audio |
| `Hey Mando` | one-shot question | transcribed text only |
| private wake word | private | nothing |

Private data (WhatsApp, personal documents, calendar) lives in a separate Qdrant
collection that cloud-facing code has no function to reach — see
[`app/vectors.py`](orchestrator/app/vectors.py). Conversation memory follows the
same rule in one direction: Saturn can read every thread, the cloud path reads
only its own — see [`app/memory.py`](orchestrator/app/memory.py).

## Install on Ubuntu Server

From a fresh install, as your normal user:

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER
```

Log out and back in — the group change needs a new session. Then:

```bash
git clone <this-repo> ~/reachy-assistant
cd ~/reachy-assistant
./setup.sh
```

The first run creates `.env` and stops. Put your Anthropic API key in it
(from console.anthropic.com — a Claude subscription does **not** cover API use),
then run `./setup.sh` again.

The second run starts the services, pulls the models (a few GB — this is the
slow part), and verifies the privacy boundary before telling you it is ready.

## Adding your documents

```
data/inbox/private/   Saturn only — never sent to any cloud provider
data/inbox/public/    reachable by Hey Mando and Mando live
```

Supported: `.txt`, `.md`, `.pdf`, `.docx`. WhatsApp exports are detected
automatically and grouped into conversation blocks rather than single messages.

To export a WhatsApp chat: open the chat → Export chat → **Without media** →
save the `.txt` into `data/inbox/private/`.

Then load everything:

```bash
docker compose run --rm orchestrator python -m app.ingest
```

Files stay where you put them. Re-running is free — each file is tracked by
content hash, and editing one replaces its chunks instead of duplicating them.

## Using it

```bash
# private — runs entirely on this box
curl -X POST localhost:8000/private/ask -H 'content-type: application/json' \
  -d '{"question":"what did Ada say about the blue folder"}'

# public — transcribed text goes to Claude Haiku
curl -X POST localhost:8000/ask -H 'content-type: application/json' \
  -d '{"question":"how tall is the Eiffel tower"}'

# end the current conversation (wire to "Mando, forget that")
curl -X POST localhost:8000/forget

# today's spend
curl localhost:8000/budget
```

Follow-up questions work for three minutes; after that the wake word starts a
fresh conversation.

## Costs

| | |
|---|---|
| `Saturn` question | $0 |
| `Hey Mando` question | ~$0.0013 |
| `Mando live` | $0.05/minute |

One minute of live chat costs about the same as 38 `Hey Mando` questions, so
default to `Hey Mando` and save live mode for real conversations. `DAILY_BUDGET_USD`
in `.env` is the hard ceiling; when it is spent, the public path answers locally
instead of refusing — same documents, slower model.

## Talking to it

Needs a microphone on the server plus `sudo apt install -y alsa-utils jq`.

```bash
./scripts/talk.sh            # private mode, records 6 seconds
./scripts/talk.sh public     # public mode
./scripts/talk.sh private 10 # record for 10 seconds
```

Speech-to-text is Whisper and text-to-speech is Piper, both on the CPU in the
`voice` service. They download their models once during setup and are fully
offline afterwards — which is what makes the Saturn path's zero-egress claim
true rather than aspirational.

Reachy Mini itself supplies no speech recognition or synthesis — only raw audio,
hardware echo cancellation, and a speech-detection flag. The models have to live
here regardless of whether the robot is attached.

## Mando live

A full-duplex conversation with GPT-Live-1. **Piper is not involved** — GPT-Live
generates its own audio, so live mode sounds noticeably different from the other
two. That difference is useful: the voice itself tells you the cloud is on.

```bash
pip install websockets numpy sounddevice

./scripts/live_client.py                  # server microphone
./scripts/live_client.py --source reachy  # Reachy Mini over the network
```

The robot never talks to OpenAI. It streams 16 kHz PCM16 to the orchestrator,
which resamples to the 24 kHz GPT-Live wants, holds the API key, enforces the
budget, and answers document searches locally. Moving from the server mic to the
robot is the `--source` flag — both speak the same format.

Sessions end on silence (`LIVE_IDLE_SECONDS`), on budget, or on Ctrl-C, and the
client prints what the session cost.

**`search_private_docs` is not registered as a tool** and must never be. A live
session has no function that reaches Saturn's data — the same structural rule
used everywhere else, not a runtime check.

> Before your first billed session, confirm `LIVE_URL` and the event names at the
> top of [`app/live.py`](orchestrator/app/live.py) against the current GPT-Live
> reference. Everything else in that file is protocol-independent.

## Verification

```bash
docker compose run --rm orchestrator python -m tests.test_memory
docker compose run --rm orchestrator python -m tests.test_sources
docker compose run --rm orchestrator python -m tests.test_audio
sudo ./scripts/prove-private.sh
```

`test_memory` proves private conversation content cannot reach the cloud path.
`prove-private.sh` watches the wire with tcpdump while a private question is
answered and fails if anything reaches an Anthropic or OpenAI endpoint. Run it
after setup has finished downloading models, or you will be watching the model
download rather than the answer.

## Status

Built: the orchestrator, both collections, conversation memory, ingestion,
budget enforcement, the local voice loop, and the GPT-Live relay.

Not built yet (phase 5): wake-word detection for the three words, the client
loop that plays a mode confirmation before opening the mic, the follow-up
window, and antenna mode indication. The confirmation audio is already rendered
into `data/sounds/` by setup, and `scripts/live_client.py` already has the
Reachy audio path behind `--source reachy`.

Reachy Mini supplies no speech recognition or synthesis — only raw audio,
hardware echo cancellation, and a `get_DoA()` speech-detection flag. That flag
is the VAD the follow-up window needs; do not write another one.
