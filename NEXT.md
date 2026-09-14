# What to do next

Written so this can be picked up cold — by you in a month, or by a fresh Claude
session with no memory of building it.

## 1. Right now: get it running

On the Ubuntu Server 26.04 box, as your normal user:

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git jq alsa-utils tcpdump
sudo usermod -aG docker $USER
```

Log out and back in — the group change needs a new session. Then:

```bash
cd ~/reachy-assistant
./setup.sh          # writes .env, then stops
nano .env           # paste the Anthropic key from console.anthropic.com
./setup.sh          # does everything else
```

The second run pulls a few GB of models. That is the slow part, not the code.

**A Claude or ChatGPT subscription does not pay for API use.** Billing is set up
separately at console.anthropic.com and platform.openai.com.

## 2. Verify before trusting it with real documents

```bash
docker compose run --rm orchestrator python -m tests.test_memory
docker compose run --rm orchestrator python -m tests.test_sources
docker compose run --rm orchestrator python -m tests.test_audio
sudo ./scripts/prove-private.sh
```

`prove-private.sh` is the one that matters: it watches the wire with tcpdump
while a private question is answered, and fails if anything reaches Anthropic or
OpenAI. Run it **after** setup has finished downloading models, or you will be
watching the model download instead of the answer.

Then talk to it:

```bash
./scripts/talk.sh          # private mode
./scripts/talk.sh public   # public mode
```

**Judgement call waiting for you here:** Piper is fast but flat. Listen to it
before going further. If it grates, the alternatives are in §5.

## 3. Load your documents

```
data/inbox/private/   Saturn only — never sent to any cloud provider
data/inbox/public/    reachable by Hey Mando and Mando live
```

WhatsApp: open the chat → Export chat → **Without media** → drop the `.txt` in
`data/inbox/private/`. The parser detects the format and groups messages into
conversation blocks. This is a manual snapshot, not a live sync — there is no
API for personal WhatsApp chats.

```bash
docker compose run --rm orchestrator python -m app.ingest
```

Re-running is free. Editing a file replaces its chunks rather than duplicating.

## 4. Before the first billed live session

Confirm `LIVE_URL` and the event-name block at the top of
[`orchestrator/app/live.py`](orchestrator/app/live.py) against the current
GPT-Live reference. Those constants follow OpenAI's realtime protocol, but the
model page says GPT-Live-1 is served from `v1/live`, not `v1/realtime`, and the
public docs for that path were thin when this was written.

Everything else in that file — relay, budget, tool handling, resampling — does
not depend on the exact spelling. If the names differ it is a two-minute fix in
one place.

Then:

```bash
pip install websockets numpy sounddevice
./scripts/live_client.py
```

Watch `curl localhost:8000/budget` the first few times. At $0.05/min the
expensive failure is a session left open, not the questions.

## 5. Phase 5 — the robot (needs Reachy Mini in hand)

Everything below runs on the Ubuntu box, not the Pi. `ReachyMini(media_backend=
"webrtc")` drives the robot over the network and Linux is the supported remote
client, so all the code stays in this repo.

- **Train three wake words** with openWakeWord, on your own voice, not just
  synthetic samples: `Hey Mando`, `Mando live`, `Saturn`. Raise the threshold on
  the Mando pair — "Mando" is two syllables and hides inside "commando" and
  "Amanda". Prefer a missed wake over a false one.
- **Client loop**: wake word → play the confirmation from `data/sounds/` →
  *then* open the mic. Never the other order, or you have started talking before
  you know the mode.
- **Follow-up window**: after an answer, keep the mic open ~10 s for Saturn,
  ~5 s for Hey Mando, and close on silence. **Use `mini.media.get_DoA()`, which
  returns `(doa, is_speech_detected)`** — the VAD is in the hardware, do not
  write one. A follow-up must never change mode.
- **Antennas show the mode** for the whole window, not just the first question.
  An open cloud mic has to be visible.
- **Ambiguity falls back to private.** A below-threshold detection routes local.

Gate: mumble "Saturn" and confirm it never falls through to a cloud mode; say
"commando" and "Amanda" ten times each and confirm the threshold holds; run
`prove-private.sh` against a follow-up, not just a first question.

### Hardware facts worth not re-discovering

Reachy Mini has **no STT and no TTS** — raw audio only, which is why Whisper and
Piper are here. It does give you hardware echo cancellation (so the robot will
not re-trigger on its own confirmation) and the speech-detection flag above.
Audio is 16 kHz float32, `(samples, 2)` in, 1–2 channels out, and
`push_audio_sample()` is **non-blocking** — sleep for the clip length or the
next action cuts it off.

## 6. Open decisions

- **Calendar backend** — CalDAV (Apple/Nextcloud) or Google Calendar API. Not
  wired yet. Blocks only the calendar part of ingestion.
- **Calendar is currently private**, so "what's on my calendar tomorrow" needs
  Saturn: slow path, flat voice, for a question asked daily. Moving it to
  `public` is a folder change if that trade stops being worth it.
- **Local model size** — `qwen3:4b` is the default. Drop to `qwen3:1.7b` if
  Saturn answers feel too slow on this CPU.
- **Piper voice** — `PIPER_VOICE=tr_TR-dfki-medium` for Turkish. Whisper
  auto-detects language already; pin `WHISPER_LANGUAGE` if you only use one.
- **If you ever add a GPU**, swapping Piper for Qwen3-TTS is the upgrade worth
  making — far more natural, too slow on CPU. One file: `voice/app/speech.py`.

## 7. Rules that must not be quietly undone

These are the reason the design looks the way it does.

1. **Private vectors live in their own collection**, and cloud-facing code has
   no function that reaches them. Not a filter flag — a missing code path.
2. **Memory flows one way.** Saturn reads every thread; the cloud path reads
   only its own. `tests/test_memory.py` fails if that stops being true.
3. **`search_private_docs` is never registered as a GPT-Live tool.** Not
   blocked — not offered.
4. **Budget exhaustion changes the model, never the data scope.** A public
   question answered locally still searches public documents.
5. **Mode is chosen explicitly by wake word, never inferred.** A classifier that
   is 97% accurate leaks 3% of private questions, and the question itself is
   usually the sensitive part.
