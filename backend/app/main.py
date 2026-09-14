import asyncio
import json
import logging
import os
from collections import deque
from contextlib import asynccontextmanager

import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket

from app import crud, tools
from app.config import REFUSAL_INSTRUCTIONS, SYSTEM_PROMPT, TOOLS_CONFIG
from app.database import AsyncSessionLocal, Base, engine
from app.guard import is_in_scope

load_dotenv(dotenv_path="../.env")  # Load the .env from the root folder

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WS_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime"

# Turns held in memory per connection to give the scope classifier context.
CONTEXT_WINDOW = 8


# --- FASTAPI LIFECYCLE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="F1 Voice Agent Backend", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# --- THE WEBSOCKET RELAY ---
@app.websocket("/ws/chat")
async def websocket_relay(client_ws: WebSocket):
    await client_ws.accept()
    print("Client connected")

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    # Grab user info from query params (e.g., ws://.../ws/chat?user_id=p_1&name=Pranav)
    user_id = client_ws.query_params.get("user_id", "guest_user")
    user_name = client_ws.query_params.get("name", "User")

    current_assistant_transcript = ""
    recent_turns: deque[tuple[str, str]] = deque(maxlen=CONTEXT_WINDOW)
    response_active = False

    print(f"Connection request: {user_name} ({user_id})")

    # Ensure the user exists in the DB so we don't hit Foreign Key errors
    try:
        async with AsyncSessionLocal() as db:
            await crud.get_or_create_user(db, user_id, name=user_name)
            print(f"User {user_id} ({user_name}) verified in DB")
    except Exception as e:
        print(f"User verification failed: {e}")

    try:
        async with websockets.connect(
            WS_URL, additional_headers=headers, ping_interval=None
        ) as openai_ws:
            print("OpenAI connection established")
            instructions = (
                f"{SYSTEM_PROMPT}\nIn this session, you are talking to {user_name}."
            )

            await openai_ws.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "type": "realtime",
                            "instructions": instructions,
                            "output_modalities": ["audio"],
                            "audio": {
                                "input": {
                                    "format": {"type": "audio/pcm", "rate": 24000},
                                    "turn_detection": {
                                        "type": "server_vad",
                                        # The relay decides whether each turn gets
                                        # answered at all -- see handle_user_turn.
                                        # Left at the default, OpenAI would reply
                                        # before any scope policy could run.
                                        "create_response": False,
                                        "interrupt_response": False,
                                    },
                                    "transcription": {"model": "whisper-1"},
                                },
                                "output": {
                                    "format": {"type": "audio/pcm", "rate": 24000},
                                    "voice": "alloy",
                                },
                            },
                            "tools": TOOLS_CONFIG,
                            "tool_choice": "auto",
                        },
                    }
                )
            )

            # Opening greeting. Explicit response.create, so it is unaffected by
            # create_response=False above.
            await openai_ws.send(json.dumps({"type": "response.create"}))

            async def handle_user_turn(user_text: str):
                """Persist the turn, then decide whether the model may answer."""
                nonlocal response_active

                if not user_text:
                    return  # Noise or silence; stay quiet rather than replying.

                try:
                    async with AsyncSessionLocal() as db:
                        await crud.save_chat_message(db, user_id, "user", user_text)
                except Exception as db_err:
                    print(f"User DB Save Error: {db_err}")

                # Context excludes the current utterance; it is passed separately.
                context = list(recent_turns)
                recent_turns.append(("user", user_text))

                if await is_in_scope(user_text, context):
                    await openai_ws.send(json.dumps({"type": "response.create"}))
                else:
                    logger.info("Out-of-scope utterance refused for %s", user_id)
                    await openai_ws.send(
                        json.dumps(
                            {
                                "type": "response.create",
                                "response": {"instructions": REFUSAL_INSTRUCTIONS},
                            }
                        )
                    )
                response_active = True

            async def upstream_loop():
                try:
                    while True:
                        data = await client_ws.receive_text()
                        await openai_ws.send(data)
                except Exception as e:
                    print(f"Upstream closed: {e}")

            async def downstream_loop():
                nonlocal current_assistant_transcript, response_active
                try:
                    while True:
                        message = await openai_ws.recv()
                        event = json.loads(message)
                        etype = event.get("type", "")

                        # Surface OpenAI error events; they are otherwise silent
                        if etype == "error":
                            print(f"OpenAI ERROR event: {json.dumps(event)}")

                        elif etype == "response.created":
                            response_active = True

                        elif etype == "input_audio_buffer.speech_started":
                            # interrupt_response=False means OpenAI no longer
                            # cancels on our behalf, so the relay owns the server
                            # half of barge-in. The client stops its own queued
                            # audio on this same event.
                            if response_active:
                                await openai_ws.send(
                                    json.dumps({"type": "response.cancel"})
                                )
                                response_active = False

                        # 1. Log AI Transcript Deltas
                        elif etype == "response.output_audio_transcript.delta":
                            current_assistant_transcript += event.get("delta", "")

                        # 2. Gate and persist the user's turn
                        elif (
                            etype
                            == "conversation.item.input_audio_transcription.completed"
                        ):
                            await handle_user_turn(event.get("transcript", "").strip())

                        elif (
                            etype == "conversation.item.input_audio_transcription.failed"
                        ):
                            # No transcript means nothing to classify. Answer
                            # ungated rather than leaving the user in silence.
                            logger.warning("Input transcription failed; answering ungated")
                            await openai_ws.send(json.dumps({"type": "response.create"}))
                            response_active = True

                        # 3. Save AI message and run any tool calls
                        elif etype == "response.done":
                            response_active = False

                            if current_assistant_transcript:
                                recent_turns.append(
                                    ("assistant", current_assistant_transcript)
                                )
                                try:
                                    async with AsyncSessionLocal() as db:
                                        await crud.save_chat_message(
                                            db,
                                            user_id,
                                            "assistant",
                                            current_assistant_transcript,
                                        )
                                except Exception as db_err:
                                    print(f"Assistant DB Save Error: {db_err}")
                                current_assistant_transcript = ""

                            for item in event.get("response", {}).get("output", []):
                                if item.get("type") != "function_call":
                                    continue

                                try:
                                    args = json.loads(item.get("arguments") or "{}")
                                except json.JSONDecodeError:
                                    args = {}

                                print(f"Tool called: {item.get('name')}")
                                result = await tools.dispatch(
                                    item.get("name", ""), args, user_id=user_id
                                )

                                await openai_ws.send(
                                    json.dumps(
                                        {
                                            "type": "conversation.item.create",
                                            "item": {
                                                "type": "function_call_output",
                                                "call_id": item["call_id"],
                                                "output": result,
                                            },
                                        }
                                    )
                                )
                                await openai_ws.send(
                                    json.dumps({"type": "response.create"})
                                )
                                response_active = True

                        # Forward to frontend
                        try:
                            await client_ws.send_text(message)
                        except Exception:
                            break
                except Exception as e:
                    print(f"Downstream closed: {e}")

            await asyncio.gather(upstream_loop(), downstream_loop())

    except Exception as e:
        print(f"Relay Error: {e}")
