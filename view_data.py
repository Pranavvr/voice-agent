import asyncio
import os
import sys

# Move up and find the backend folder
sys.path.append(os.getcwd())

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from backend.app.models import ChatMessage, User

DATABASE_URL = "postgresql+asyncpg://postgres:secretpassword@localhost:5432/voice_agent_db"

async def view_data():
    engine = create_async_engine(DATABASE_URL)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with session_factory() as session:
        # 1. Show Users
        users = (await session.execute(select(User))).scalars().all()
        print("\n--- USERS IN DATABASE ---")
        if not users:
            print("No users found.")
        for u in users:
            print(f"ID: {u.id} | Name: {u.name}")
            
        # 2. Show Messages
        msgs = (await session.execute(
            select(ChatMessage).order_by(ChatMessage.timestamp.desc()).limit(10)
        )).scalars().all()
        
        print("\n--- RECENT CHAT HISTORY ---")
        if not msgs:
            print("No messages found.")
        for m in reversed(msgs):
            prefix = "AI" if m.role == "assistant" else "ME"
            print(f"[{m.timestamp.strftime('%H:%M:%S')}] {prefix}: {m.content}")
        print("---------------------------\n")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(view_data())
