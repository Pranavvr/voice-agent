# 🎙️ Voice Agent

A **multimodal voice interview agent** powered by the OpenAI Realtime API, FastAPI, PostgreSQL, and Redis.

## Architecture

```
Browser (HTML/JS)
     ↕ WebSocket
FastAPI Backend
     ↕ WebSocket              ↕ Tool calls
OpenAI Realtime API      web_search / get_user_history
                                  ↕
                           PostgreSQL ← permanent storage
                           Redis      ← live session state
```

## Session Flow

| Phase | What happens |
|-------|-------------|
| **Start** | Agent calls `get_user_history` → greets user based on past performance |
| **During** | Audio streams both ways; transcript stored live in Redis; agent can call `web_search` |
| **End** | Transcript read from Redis → GPT scores performance → written to PostgreSQL → Redis cleared |

## Stack

- **Backend**: FastAPI + WebSockets
- **AI**: OpenAI Realtime API (GPT-4o)
- **Storage**: PostgreSQL (permanent) + Redis (live session)
- **Tools**: `get_user_history`, `web_search`

## Setup

```bash
# 1. Clone repo
git clone https://github.com/Pranavvr/voice-agent.git
cd voice-agent

# 2. Create virtual env
python -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure env
cp .env.example .env
# Fill in your keys in .env

# 5. Run notebook prototype
jupyter notebook notebooks/voice_agent_prototype.ipynb
```

## Project Structure

```
Voice_Agent/
├── notebooks/              ← Exploratory prototype (start here)
│   └── voice_agent_prototype.ipynb
├── backend/                ← FastAPI app (production)
│   ├── main.py
│   ├── routes/
│   ├── tools/
│   └── db/
├── frontend/               ← Browser client
│   └── index.html
├── docker/                 ← Docker Compose setup
│   └── docker-compose.yml
├── .env.example
├── requirements.txt
└── README.md
```
