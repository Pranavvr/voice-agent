import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal

async def check_messages():
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT user_id, role, content, created_at FROM messages ORDER BY created_at DESC LIMIT 5"))
        messages = result.fetchall()
        
        print("\n--- RECENT DATABASE MESSAGES ---")
        if not messages:
            print("No messages found yet. Try speaking to the agent first!")
        else:
            for m in messages:
                print(f"[{m.user_id}] {m.role.upper()}: {m.content[:50]}... ({m.created_at})")
        print("--------------------------------\n")

if __name__ == "__main__":
    asyncio.run(check_messages())
