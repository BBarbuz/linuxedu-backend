# from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
# from sqlalchemy.orm import sessionmaker, declarative_base
# from app.config import settings

# Base = declarative_base()


# DATABASE_URL = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
# engine = create_async_engine(DATABASE_URL, echo=False)

# AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# async def get_db():
#     async with AsyncSessionLocal() as session:
#         try:
#             yield session
#             await session.commit()
#         except Exception:
#             await session.rollback()
#             raise
#         finally:
#             await session.close()

# print("✅ Database ready!")

"""
Database initialization with proper transaction handling
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

Base = declarative_base()

DATABASE_URL = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    """
    Database session dependency with proper transaction handling.
    
    ✅ NAPRAWKA z błędu: SQLAlchemy Transaction Aborted
    
    Poprzednio transakcja mogła utknąć w stanie 'aborted' jeśli:
    - Wyjątek rzucony podczas session.commit()
    - Nie było rollback() w finally
    
    Teraz:
    - Rollback dzieje się zawsze w case wyjątku
    - Commit tylko jeśli funkcja zakończyła się bez błędu
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            # Jeśli wyjątek w funkcji użytkownika → rollback
            await session.rollback()
            raise
        else:
            # Tylko jeśli wszystko ok → spróbuj commit
            try:
                await session.commit()
            except Exception:
                # Jeśli commit się nie powiedzie → rollback
                await session.rollback()
                raise
        finally:
            # Zawsze zamknij session
            await session.close()

print("✅ Database ready!")