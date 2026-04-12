from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app import models

async def save_chat_message(db: AsyncSession, user_id: str, role: str, content: str):
    """Asynchronously save a chat message to the database."""
    new_message = models.ChatMessage(
        user_id=user_id,
        role=role,
        content=content
    )
    db.add(new_message)
    await db.commit()
    await db.refresh(new_message)
    return new_message

async def get_recent_history(db: AsyncSession, user_id: str, limit: int = 10):
    """Fetch the most recent chat messages for a user."""
    result = await db.execute(
        select(models.ChatMessage)
        .where(models.ChatMessage.user_id == user_id)
        .order_by(models.ChatMessage.timestamp.desc())
        .limit(limit)
    )
    # Reverse so they are in chronological order
    messages = result.scalars().all()
    return messages[::-1]

async def get_or_create_user(db: AsyncSession, user_id: str, name: str = "Pranav"):
    """Check if user exists, otherwise create them."""
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        user = models.User(id=user_id, name=name)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    
    return user
