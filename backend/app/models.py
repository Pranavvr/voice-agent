from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from app.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, index=True) # e.g., "user_123"
    name = Column(String)
    preferences = Column(Text, nullable=True) # JSON string or plain text

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"))
    role = Column(String) # "user" or "assistant"
    content = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
