import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

# We look for a DATABASE_URL environment variable. 
# If none exists, we automatically fallback to our local Docker connection.
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql+asyncpg://postgres:secretpassword@localhost:5432/voice_agent_db"
)

# Create the async engine
engine = create_async_engine(DATABASE_URL, echo=True)

# Create the session factory
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

async def get_db():
    """Dependency injection to provide a database session to our endpoints."""
    async with AsyncSessionLocal() as session:
        yield session
