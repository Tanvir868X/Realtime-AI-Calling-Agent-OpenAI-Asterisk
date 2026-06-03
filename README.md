# 📞 Realtime AI Calling Agent — OpenAI + Asterisk

A production-grade, real-time AI voice calling agent built on **Asterisk ARI** (Asterisk REST Interface) and **OpenAI Realtime API**. Handles live phone calls with full-duplex audio streaming, server-side Voice Activity Detection (VAD), barge-in support, and colored conversation logging.

---

## ✨ Features

- 🎙️ **Full-duplex Voice** — Simultaneous send and receive over RTP using G.711 µ-law audio
- 🤖 **OpenAI Realtime API** — Single WebSocket per call handles STT + LLM + TTS together
- 📡 **Asterisk ARI Integration** — Connects to Asterisk via REST + WebSocket event stream
- 🔊 **Barge-in Support** — Server VAD detects when the user speaks and cancels current playback instantly
- 🏗️ **Bridge + ExternalMedia** — Proper Asterisk mixing bridge with ExternalMedia channel for clean audio routing
- 🔄 **Concurrent Calls** — Configurable max concurrent calls (default: 10)
- 🎛️ **Configurable VAD** — Threshold, prefix padding, and silence duration all tuneable
- 🌈 **Colored Conversation Logging** — Client events (cyan C-0001) and OpenAI events (yellow O-0001) tracked separately
- 🩺 **Health Checks** — Verifies OpenAI Realtime connectivity before accepting calls

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.10+ |
| Telephony | Asterisk ARI (REST + WebSocket) |
| AI | OpenAI Realtime API (`gpt-4o-mini-realtime-preview`) |
| Audio Transport | RTP (G.711 µ-law, 8kHz) |
| Async Framework | asyncio + aiohttp + websockets |
| Logging | Rich (colored terminal output) |
| Config | python-dotenv (`config.conf`) |

---


---

## 📁 Project Structure

```
calling-agent/
├── main.py                      # App entry point — startup, health checks, signal handling
├── start.py                     # Simple launcher script
├── asterisk_client.py           # Asterisk ARI client — event handling, bridge, ExternalMedia
├── openai_realtime_client.py    # OpenAI Realtime WS client — STT+LLM+TTS per call
├── rtp_handler.py               # RTP receiver/sender — G.711 µ-law audio streaming
├── state.py                     # Global state manager for active channels
├── config.py                    # Config loader + Rich logging setup
├── config.conf                  # Your actual config (not committed)
├── example_config.conf          # Template config with all available options
├── CONVERSATION_LOGGING.md      # Logging system documentation
└── requirements.txt
```

---

## ⚙️ How It Works

1. A call comes in → Asterisk routes it to extension **9999** → fires a `StasisStart` event to the agent
2. The agent **answers the call**, creates a **mixing bridge**, and starts an **RTP receiver** on a local port
3. An **ExternalMedia channel** is added to the bridge to pipe audio in/out via RTP
4. An **OpenAI Realtime WebSocket** session is opened for the channel with G.711 µ-law audio format and server VAD
5. Incoming RTP audio is forwarded to OpenAI → OpenAI streams back audio deltas → agent sends them back via RTP in real-time 20ms frames
6. If the user speaks while the agent is talking, **barge-in** is triggered — current playback is cancelled immediately
7. On hang-up, all resources (RTP sockets, WebSocket, bridge) are cleaned up

---

## 🚀 Getting Started

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure the agent

Copy the example config and fill in your values:

```bash
cp example_config.conf config.conf
```

Edit `config.conf`:

```ini
# Required
OPENAI_API_KEY=your_openai_api_key

# Asterisk ARI
ARI_URL=http://127.0.0.1:6021
ARI_USER=asterisk
ARI_PASS=asterisk
ARI_APP=myapp

# Agent personality
SYSTEM_PROMPT=You are a helpful voice assistant for phone calls...
INITIAL_MESSAGE=Hi there! How can I help you today?

# RTP
RTP_PORT_START=12000
RTP_EXTERNAL_HOST=127.0.0.1
MAX_CONCURRENT_CALLS=10

# VAD
VAD_THRESHOLD=0.6
VAD_PREFIX_PADDING_MS=200
VAD_SILENCE_DURATION_MS=600
```

### 3. Start the agent

```bash
python start.py
```

The agent will:
- Run health checks on OpenAI Realtime
- Connect to Asterisk ARI
- Listen for incoming calls on extension **9999**

---

## ☎️ Asterisk Dialplan Setup

Add this to your Asterisk `extensions.conf`:

```ini
[default]
exten => 9999,1,NoOp(AI Agent)
 same => n,Stasis(myapp)
 same => n,Hangup()
```

Restart Asterisk after editing.

---

## 🔧 Configuration Reference

| Key | Default | Description |
|-----|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key (required) |
| `OPENAI_REALTIME_MODEL` | `gpt-4o-mini-realtime-preview-2024-12-17` | Realtime model |
| `OPENAI_VOICE` | `alloy` | TTS voice |
| `ARI_URL` | `http://127.0.0.1:6021/ari` | Asterisk ARI endpoint |
| `RTP_PORT_START` | `12000` | Starting port for RTP receivers |
| `RTP_EXTERNAL_HOST` | `127.0.0.1` | Host for RTP (use public IP for remote Asterisk) |
| `MAX_CONCURRENT_CALLS` | `10` | Max simultaneous calls |
| `VAD_THRESHOLD` | `0.6` | Voice activity detection sensitivity |
| `VAD_SILENCE_DURATION_MS` | `600` | Silence duration before turn ends |
| `SILENCE_PADDING_MS` | `100` | Silence prepended to each response |
| `CALL_DURATION_LIMIT_SECONDS` | `0` | Max call length (0 = unlimited) |
| `LOG_LEVEL` | `info` | Logging verbosity |
| `ENABLE_CONVERSATION_LOGGING` | `true` | Enable colored conversation log |
| `LOG_TRANSCRIPT_DELTAS` | `false` | Log partial transcript deltas |

---

## 🌈 Conversation Logging

The agent uses a dual-counter logging system:

```
C-0001 | WebSocket connected for channel_abc123
O-0001 | Session updated for channel_abc123
O-0002 | User transcript: Hello, I need help booking a flight
C-0002 | Assistant response: Sure! Where would you like to fly to?
O-0003 | Barge-in detected; canceling playback
```

- **C-XXXX** (cyan) — client-side events (connections, responses, audio)
- **O-XXXX** (yellow) — OpenAI-side events (transcripts, barge-in, errors)

---

## 🛠️ Troubleshooting

| Issue | Fix |
|-------|-----|
| `OPENAI_API_KEY is missing` | Add key to `config.conf` |
| `ARI connection failed` | Check Asterisk is running and ARI credentials match |
| No audio heard | Verify `RTP_EXTERNAL_HOST` is reachable from Asterisk |
| Agent doesn't answer | Check dialplan routes to `Stasis(myapp)` on extension 9999 |
| Barge-in not working | Lower `VAD_THRESHOLD` (e.g. 0.4) |
