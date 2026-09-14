# Voice Agent

A realtime **domain-locked F1 voice race companion**. The browser streams audio
to a FastAPI WebSocket relay, which proxies to the OpenAI Realtime API and owns
tool execution, policy, and persistence.

The agent answers Formula 1 questions and refuses everything else. Scope is
enforced in code rather than by prompting — see the turn lifecycle below.

## Architecture

```
Browser (React + Vite)
    │  WebSocket: PCM audio in, audio + events out
    ▼
FastAPI relay  (backend/app/main.py)  ──WS──►  OpenAI Realtime (gpt-realtime)
    ├─ gate   → guard.py   scope classifier; decides if a turn is answered
    ├─ tools  → tools.py   f1_search (domain-locked), get_user_history
    └─ state  → Postgres   users, chat_messages
```

OpenAI Realtime is a single black box doing VAD, transcription, reasoning, and
speech synthesis. The relay's job is to be the **policy layer** around it.

### Turn lifecycle

```
1. User speaks                 browser → PCM chunks → relay → OpenAI
2. VAD detects end of speech   OpenAI commits the audio buffer
3. Transcription completes     OpenAI → relay: the text        ◄── CONTROL POINT
4. Gate                        relay classifies (with recent turns as context)
5a. In scope                   → response.create → model answers, may call tools
5b. Out of scope               → response.create with forced refusal instructions
6. Audio streams back          OpenAI → relay → browser → AudioContext
```

**Step 3 is the design's load-bearing idea.** By default
`turn_detection.create_response` is `true`, so OpenAI jumps straight from 2 to 6
and the backend never gets a say — a system prompt would then be the only thing
keeping the agent on topic. The session sets it `false`, which inserts steps
3–5. Prompt-based refusal alone is explicitly **not** sufficient here.

`interrupt_response` is deliberately left at its default (`true`) — only
`create_response` needs to change for the gate. Barge-in then has two halves
that are both required: OpenAI cancels generation server-side, and the client's
`clearScheduledAudio()` drops audio it has **already** queued. The model
generates faster than real time, so seconds of speech can be scheduled in the
`AudioContext` before the user interrupts; cancelling on the server does nothing
about those.

The gate fails **open** (`guard.FAIL_OPEN`): if the classifier times out or
errors, the turn is allowed through. A gate outage that refuses everything
leaves the agent unusable, and the domain-locked search tool still blocks
off-topic *retrieval* in that window.

## Commands

```bash
# Dependencies (Postgres + Redis)
docker compose -f docker/docker-compose.yml up -d db redis

# Backend — must run from backend/ (see gotchas)
cd backend && uvicorn app.main:app --reload          # :8000

# Frontend
cd frontend && npm run dev                           # :5173

# Whole stack in Docker
docker compose -f docker/docker-compose.yml up --build

# Tests and lint (both run in CI)
PYTHONPATH=backend pytest tests/
ruff check .
cd frontend && npm run lint

# Deploy (requires an AWS account; see Known gaps)
cd infra && terraform apply
./deploy.sh                                          # build → ECR → ECS rollout
```

## Gotchas

- **`.env` lives at the repo root.** `main.py` calls
  `load_dotenv(dotenv_path="../.env")`, which resolves relative to the *current
  working directory* — so the backend must be started from `backend/`. Under
  Docker Compose this call is a no-op; env vars come from `env_file`.
- **`pytest` needs `PYTHONPATH=backend`** or `from app.main import app` fails.
- **`DATABASE_URL` silently falls back** to local Docker Postgres
  (`database.py:7`). A missing env var surfaces as a connection error, not a
  config error.
- **`echo=True`** on the engine (`database.py:14`) logs every SQL statement.
- **`createScriptProcessor`** (`useVoiceAgent.js:128`) is deprecated; AudioWorklet
  is the supported replacement.
- **The repo is public.** Never commit `.env`, `infra/terraform.tfstate*`, or
  `infra/terraform.tfvars`. All three are gitignored and have never been
  committed — keep it that way.

## Conventions

- Branch prefixes: `feat/`, `fix/`, `chore/`, `test/`, `infra/`
- Conventional commits (`feat:`, `fix:`, `chore:`, …)
- One PR per branch, squash merge. `main` is protected: a PR and a green `build`
  check are required, force-push and deletion are blocked.
- Keep PRs scoped. Note unrelated problems in the PR body rather than fixing
  them opportunistically.

## Known gaps

Tracked deliberately — don't fix these outside their branch:

| Gap | Branch |
|---|---|
| `user_id` comes from a query param (`main.py:63`), so anyone can read anyone's history | `feat/session-auth` |
| README claims Redis session state and GPT scoring; neither exists | `chore/repo-hygiene` |
| `print()` throughout instead of structured logging with per-session correlation IDs | `chore/repo-hygiene` |
| `requirements.txt` is a raw `pip freeze` — ships Jupyter into the production image | `chore/repo-hygiene` |
| Redis is provisioned (`elasticache.tf`, compose) but no code uses it | — |
| Terraform state is local; no S3 remote backend | `infra/remote-state` |

## Non-goals

Deferred by explicit decision — raise before revisiting:

- **LiveKit / WebRTC transport.** Would replace the hand-rolled audio pipeline
  and make the existing barge-in implementation dead code.
- **TypeScript on the frontend.** No new capability; revisit only if the
  frontend grows substantially.
- **Jolpica / OpenF1 live data.** Start Tavily-only; add live sources only if
  retrieval proves insufficient in practice.
