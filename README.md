# Omni Operator

Multi-capability Telegram bot. Voice transcription, message summaries, persona-based replies — all through one bot.

## Features

- **🗣️ Transcription** — Voice/audio messages → text via faster-whisper (distil-large-v3)
- **📊 Summary** — `/summary [24h|7d|...]` — LLM-generated summary of your recent messages, DM'd to you
- **🎭 Persona Reply** — `/reply`, `/setpersona`, `/personas` — reply with configurable personas (YAML file, live-reloaded)

## Quick Start

```bash
docker run -d \
  --name omni-operator \
  --restart unless-stopped \
  -e BOT_TOKEN="your-telegram-token" \
  -e AUTHORIZED_USERS="your-user-id,other-user-id" \
  -e LLM_BASE_URL="http://your-llm-server:8088/v1" \
  -v ./data:/data \
  ghcr.io/TheNoticingBegins/omni-operator:latest
```

## Configuration

All config via environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | ✅ | — | Telegram bot token (from @BotFather) |
| `AUTHORIZED_USERS` | ✅ | — | Comma-separated Telegram user IDs |
| `ASR_MODEL` | — | `distil-large-v3` | faster-whisper model |
| `LLM_BASE_URL` | — | `http://your-llm-server:8088/v1` | OpenAI-compatible LLM endpoint |
| `LLM_MODEL` | — | `grug-35b-v2-iq4xs` | Model name for summaries/personas |
| `LOG_LEVEL` | — | `INFO` | Log verbosity |

## Adding Capabilities

Drop a `.py` file into `modules/` with a class extending `BotPlugin`. It auto-registers on next restart.