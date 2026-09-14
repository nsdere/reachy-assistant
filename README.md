# Reachy Mini Home Assistant

A home voice assistant on Reachy Mini with a hard privacy split:

- **General questions** (weather, trivia, chat) → OpenAI **GPT-Live-1**, full-duplex,
  natural talking speed (~1-2s).
- **Anything personal** (WhatsApp, notes/documents, calendar, email) → answered
  **entirely on the local Proxmox box**. No personal content ever leaves the house,
  not even summarized.

## Architecture

```
Reachy Mini (Raspberry Pi CM4/5, on-device)
  wake word → stream mic audio over LAN
        │
        ▼
Proxmox: orchestrator service
  1. local STT (whisper)             → text
  2. local classifier (small Ollama) → "does this need personal data?"
        │
        ├── NO  → GPT-Live-1 session → stream audio back to Reachy Mini
        │
        └── YES → Qdrant vector search (WhatsApp / notes / email)
                  or live calendar API call
                  → Ollama generates answer
                  → Piper TTS → stream audio back to Reachy Mini
```

Design notes:

- **Calendar is not embedded into the vector DB.** Calendar questions need live data,
  so they are a direct API lookup at question time.
- **WhatsApp ingestion is manual.** There is no personal-use WhatsApp export API —
  only the app's own "Export chat". Exports get dropped into a watched folder.
- **GPT-Live-1 has no personal-data tool at all.** Anything a cloud tool call returns
  would be sent to OpenAI, so the private path never involves it.

## Hardware

| Piece | Spec |
|---|---|
| Robot | Reachy Mini Wireless — RPi CM4/5, 4-mic array, 5W speaker, Python SDK |
| Server | HP G4 mini, 16GB RAM, 512GB disk, Proxmox, Ollama already installed |

## Build phases

| # | Phase | Status |
|---|---|---|
| 1 | Proxmox services up (Qdrant + Whisper + Piper + Ollama models) | **built** |
| 2 | Notes ingestion + local Q&A, CLI only | **built** |
| 3 | WhatsApp ingestion + live calendar lookup | not started |
| 4 | GPT-Live-1 client, standalone | not started |
| 5 | Router: STT → classifier → branch | not started |
| 6 | Reachy Mini integration (wake word, audio streaming) | not started |
| 7 | Latency tuning | not started |

---

# Setup — do these in order

Everything below runs **on the Proxmox machine**, except step 0.

## Step 0 — copy this repo to the box (on your laptop)

```bash
scp -r ~/Documents/reachy-assistant/ youruser@PROXMOX_IP:~/
```

## Step 1 — find out where Ollama is running

Ollama is already installed, but the new services need to reach it. On the
Proxmox host shell:

```bash
systemctl status ollama --no-pager | head -3
```

- **Running here** → Ollama is on the Proxmox host itself. Note the host's IP
  (`hostname -I`); you'll need it in step 5.
- **Not found** → it's inside an existing LXC/VM. Find it with `pct list` and
  `qm list`, then note that container's IP.

## Step 2 — create an LXC container for the stack

Don't install Docker on the Proxmox host itself — it can interfere with
Proxmox's own networking and storage. Make a container for it.

In the Proxmox web UI: **Create CT**

| Setting | Value |
|---|---|
| Template | Debian 12 or 13 |
| Disk | 40 GB |
| Cores | 4 |
| Memory | 6144 MB (6 GB) |
| Swap | 2048 MB |
| Network | DHCP, bridge `vmbr0` |
| Unprivileged | yes (leave checked) |

Note the container ID it gives you (e.g. `101`) and its IP.

## Step 3 — enable Docker support on that container

Docker will not start in an LXC without these two flags.

**Web UI:** select the container → **Options** → **Features** → tick
**nesting** and **keyctl** → then **stop and start the container** (a reboot
from inside is not enough — the flags only apply on a fresh start).

**Or from the Proxmox host shell** (replace `101` with your container ID):

```bash
pct set 101 --features nesting=1,keyctl=1
pct stop 101 && pct start 101
```

Verify it took:

```bash
grep features /etc/pve/lxc/101.conf
```

Expect: `features: keyctl=1,nesting=1`

## Step 4 — install Docker inside the container

Enter the container (`pct enter 101` from the host, or SSH into its IP):

```bash
apt update && apt install -y curl
curl -fsSL https://get.docker.com | sh
```

Check it actually runs — this is where a missing `keyctl=1` shows up:

```bash
docker run --rm hello-world
```

If that fails with a cgroup or keyring error, go back to step 3.

## Step 5 — configure

Move the repo into the container if you copied it to the host
(`pct push 101 ...`, or just `scp` straight to the container's IP), then:

```bash
cd ~/reachy-assistant
cp .env.example .env
nano .env
```

Set `OLLAMA_URL` to where Ollama actually lives, from step 1:

- Ollama on the Proxmox host → `OLLAMA_URL=http://PROXMOX_HOST_IP:11434`
- Ollama in another container → `OLLAMA_URL=http://THAT_CONTAINER_IP:11434`

Leave `OPENAI_API_KEY` empty until Phase 4.

> If Ollama refuses connections from the container, it's only listening on
> localhost. On the machine running Ollama:
> `systemctl edit ollama`, add
> `[Service]` / `Environment="OLLAMA_HOST=0.0.0.0"`, then
> `systemctl restart ollama`.

## Step 6 — start the services

```bash
docker compose up -d
```

## Step 7 — pull the Ollama models

On whichever machine runs Ollama:

```bash
ollama pull nomic-embed-text
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
```

`nomic-embed-text` does embeddings, `qwen2.5:3b` is the fast classifier
(Phase 5), `qwen2.5:7b` writes the answers. Swap the 7b for a smaller model in
Phase 7 if it's too slow.

## Step 8 — verify Phase 1

All five should pass before moving on.

```bash
# 1. containers up: expect reachy-qdrant, reachy-whisper, reachy-piper
docker compose ps

# 2. Qdrant answers
curl -s http://localhost:6333/healthz

# 3. Ollama reachable from the container (use your .env value)
curl -s http://PROXMOX_HOST_IP:11434/api/tags | head -c 200

# 4. Piper listening, no errors
docker logs reachy-piper | tail -5

# 5. Whisper transcribes (record a few seconds of speech as test.wav first)
curl -s http://localhost:8000/v1/audio/transcriptions \
  -F "file=@test.wav" \
  -F "model=Systran/faster-whisper-small"
```

Check 5 is slow the first time — it downloads the model — then fast.

---

# Phase 2 — your documents, answered locally

## Step 9 — install the Python bits

```bash
cd ~/reachy-assistant
apt install -y python3-venv
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Step 10 — put some notes on the box

Anything `.md` or `.txt`. Subfolders are fine.

```bash
mkdir -p /data/sources/notes
# copy some real notes in, e.g. from your laptop:
#   scp -r ~/Documents/my-notes/ root@CONTAINER_IP:/data/sources/notes/
```

## Step 11 — ingest them

```bash
.venv/bin/python ingest_notes.py
```

Expect a per-file chunk count and a total. Re-running is safe — a file's old
chunks are replaced, not duplicated.

## Step 12 — ask a question

```bash
.venv/bin/python ask.py "what did I write about the kitchen renovation?"
```

Expect an answer plus the source files it used.

## Step 13 — verify Phase 2

- Ask something you **know** is in your notes → answer should be right and cite
  the correct file.
- Ask something absolutely **not** in your notes → it should say it doesn't
  know, not invent an answer.
- Check what got indexed: `curl -s http://localhost:6333/collections/personal`

If answers are vague, the retrieval is the usual culprit, not the model — see
what chunks came back by lowering `limit` in `rag.py:search`.

---

## What's in this repo

| File | Role |
|---|---|
| `docker-compose.yml` | Qdrant (vectors), Whisper (STT), Piper (TTS) |
| `.env.example` | All config — copy to `.env` |
| `config.py` | Reads `.env` |
| `rag.py` | Embedding, chunking, Qdrant upsert/search |
| `ingest_notes.py` | Phase 2 — index a notes folder |
| `ask.py` | Phase 2 — ask your documents, fully local |

## Resource budget (16GB total)

| Service | Rough RAM |
|---|---|
| Qdrant | ~200-500MB |
| Whisper (small, CPU) | ~1-2GB while transcribing |
| Piper | ~200MB |
| Ollama 7B Q4 | ~5-6GB while generating |
| Proxmox host + LXC overhead | ~1-2GB |

Leaves headroom, but don't run the 7B answer model and a second large model at
once.
