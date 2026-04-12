import os
import json
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from app.database import engine, Base, AsyncSessionLocal
from app import models, crud
from app.config import SYSTEM_PROMPT, TOOLS_CONFIG

load_dotenv(dotenv_path="../.env") # Load the .env from the root folder

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WS_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime"

# --- REAL TOOL DEFINITIONS ---
async def fetch_user_history(user_id: str):
    """Fetches real history from PostgreSQL."""
    async with AsyncSessionLocal() as db:
        history = await crud.get_recent_history(db, user_id)
        if not history:
            return "No previous history found for this user."
        
        formatted = "\n".join([f"{m.role}: {m.content}" for m in history])
        return f"Recent history for {user_id}:\n{formatted}"

def web_search(query: str):
    """Fallback mock search result (Tavily integration coming later)."""
    return f"Search results for {query}: LangGraph is a powerful framework, but Direct WebSocket is faster for voice."

# --- FASTAPI LIFECYCLE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(title="Voice Agent Backend", lifespan=lifespan)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# --- THE WEBSOCKET RELAY ---
@app.websocket("/ws/chat")
async def websocket_relay(client_ws: WebSocket):
    await client_ws.accept()
    print("Client connected")
    
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1"
    }
    
    # Grab user info from query params (e.g., ws://.../ws/chat?user_id=p_1&name=Pranav)
    user_id = client_ws.query_params.get("user_id", "guest_user")
    user_name = client_ws.query_params.get("name", "User") # Default to "User" if missing
    current_assistant_transcript = ""

    print(f"Connection request: {user_name} ({user_id})")

    # Ensure the user exists in the DB so we don't hit Foreign Key errors
    try:
        async with AsyncSessionLocal() as db:
            await crud.get_or_create_user(db, user_id, name=user_name)
            print(f"User {user_id} ({user_name}) verified in DB")
    except Exception as e:
        print(f"User verification failed: {e}")
    
    try:
        async with websockets.connect(WS_URL, additional_headers=headers) as openai_ws:
            print("OpenAI connection established")
            await openai_ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "instructions": SYSTEM_PROMPT,
                    "modalities": ["text", "audio"],
                    "voice": "alloy",
                    "tools": TOOLS_CONFIG,
                    "tool_choice": "auto",
                    "input_audio_transcription": {"model": "whisper-1"} # Enable server-side transcription
                }
            }))
            await openai_ws.send(json.dumps({"type": "response.create"}))
            
            async def upstream_loop():
                try:
                    while True:
                        data = await client_ws.receive_text()
                        await openai_ws.send(data)
                except Exception as e:
                    print(f"Upstream closed: {e}")
                    
            async def downstream_loop():
                nonlocal current_assistant_transcript
                try:
                    while True:
                        message = await openai_ws.recv()
                        event = json.loads(message)
                        
                        # 1. Log AI Transcript Deltas
                        if event.get("type") == "response.audio_transcript.delta":
                            delta = event.get("delta", "")
                            current_assistant_transcript += delta
                            # print(f"DEBUG Delta: {delta}") # Too noisy, skip

                        # 2. Log User Transcription Completion
                        if event.get("type") == "conversation.item.input_audio_transcription.completed":
                            user_text = event.get("transcript", "").strip()
                            if user_text:
                                try:
                                    async with AsyncSessionLocal() as db:
                                        await crud.save_chat_message(db, user_id, "user", user_text)
                                except Exception as db_err:
                                    print(f"User DB Save Error: {db_err}")

                        # 3. Save AI Message on Completion
                        if event.get("type") == "response.done":
                            if current_assistant_transcript:
                                async with AsyncSessionLocal() as db:
                                    await crud.save_chat_message(db, user_id, "assistant", current_assistant_transcript)
                                current_assistant_transcript = "" # Reset for next turn

                            # Check for tool calls
                            output = event.get("response", {}).get("output", [])
                            for item in output:
                                if item.get("type") == "function_call":
                                    func_name = item["name"]
                                    args = json.loads(item["arguments"])
                                    call_id = item["call_id"]
                                    
                                    print(f"Tool called: {func_name}")
                                    if func_name == "get_user_history":
                                        result = await fetch_user_history(args.get("user_id", user_id))
                                    elif func_name == "web_search":
                                        result = web_search(args.get("query", ""))
                                    
                                    await openai_ws.send(json.dumps({
                                        "type": "conversation.item.create",
                                        "item": {
                                            "type": "function_call_output",
                                            "call_id": call_id,
                                            "output": result
                                        }
                                    }))
                                    await openai_ws.send(json.dumps({"type": "response.create"}))

                        # Forward to frontend
                        try:
                            await client_ws.send_text(message)
                        except:
                            break
                except Exception as e:
                    print(f"Downstream closed: {e}")
                    
            await asyncio.gather(upstream_loop(), downstream_loop())
            
    except Exception as e:
        print(f"Relay Error: {e}")
