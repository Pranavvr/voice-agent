import asyncio
import websockets
import json

async def test_websocket_relay():
    uri = "ws://localhost:8000/ws/chat"
    print(f"🔗 Attempting to connect to FastAPI at {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connected to our local FastAPI relay!\n")
            print("⏳ The FastAPI server is currently connecting to OpenAI secretly in the background.")
            print("⏳ Waiting for the AI's first greeting to stream down the pipe...\n")
            
            # Listen to the first 10 packets that come down from OpenAI
            for _ in range(50):
                response = await websocket.recv()
                event = json.loads(response)
                
                # Show only the subtitles so it's readable
                if event.get("type") == "response.audio_transcript.delta":
                    print(event["delta"], end="", flush=True)
                
                # If the AI says it's done talking, we exit the test
                elif event.get("type") == "response.done":
                    print("\n\n✅ Turn Complete! Check the Uvicorn terminal for the 'INSERT' logs.")
                    break
                    
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket_relay())
