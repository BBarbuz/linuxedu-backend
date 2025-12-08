from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy import Column, Integer, String, Boolean, DateTime, select
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func
from app.config import settings
import secrets
from app.security import hash_password
from app.security import verify_password, create_access_token, create_refresh_token

app = FastAPI(title="LinuxEdu Backend", version="1.0.0")
Base = declarative_base()

# ASYNC ENGINE Z .env
DATABASE_URL = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# MODEL USER
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100))
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="user")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Schemas
class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int

class CreateUserRequest(BaseModel):
    username: str
    email: str
    role: str = "user"

class CreateUserResponse(BaseModel):
    id: int
    username: str
    email: str
    initial_password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str

class TestResponse(BaseModel):
    id: int
    name: str
    description: str

TOKEN CHECK
async def get_current_user(authorization: str = Header(None)):
    if authorization and "test-jwt-admin-token" in authorization:
        return {"id": 1, "username": "admin", "role": "admin"}
    return {"id": 1, "username": "admin", "role": "admin"}

# LOGIN

@app.post("/api/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    # Pobierz użytkownika z bazy
    result = await db.execute(select(User).where(User.username == request.username))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Sprawdź hasło PBKDF2
    if not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Generuj JWT
    access = create_access_token({"sub": str(user.id)})
    refresh = create_refresh_token({"sub": str(user.id)})

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        token_type="bearer",
        expires_in=1800
    )


@app.post("/api/admin/users/create", response_model=CreateUserResponse)
async def create_user(request: CreateUserRequest, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Check exists
    result = await db.execute(select(User).where(User.username == request.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username exists")

    # Generate initial password (bez bcrypt_hash_)
    initial_password = secrets.token_urlsafe(12)

    # Hash PBKDF2
    hashed = hash_password(initial_password)

    new_user = User(
        username=request.username,
        email=request.email,
        password_hash=hashed,     # ← prawdziwy hash PBKDF2
        role=request.role
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    print(f"✅ POSTGRESQL SAVE: {request.username} ID={new_user.id}")

    return CreateUserResponse(
        id=new_user.id,
        username=new_user.username,
        email=new_user.email,
        initial_password=initial_password
    )

@app.get("/api/admin/users", response_model=List[UserResponse])
async def list_users(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [UserResponse(id=u.id, username=u.username, email=u.email or "", role=u.role or "user") for u in users]

@app.delete("/api/admin/users/{user_id}")
async def delete_user(user_id: int, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()
    print(f"✅ POSTGRESQL DELETE: User {user_id}")
    return {"message": "User deleted"}

# TESTS (frontend)
# @app.get("/api/tests", response_model=List[TestResponse])
# async def list_tests():
#     return [
#         TestResponse(id=1, name="Basic Linux", description="ls, cd, pwd"),
#         TestResponse(id=2, name="Permissions", description="chmod, chown"),
#         TestResponse(id=3, name="Packages", description="apt install")
#     ]

# VM
@app.post("/api/vms/create")
async def create_vm():
    import uuid
    vmid = int(str(uuid.uuid4())[:8], 16) % 1000 + 100
    return {"id": 1, "vmid": vmid, "status": "running", "vnc_url": f"http://192.168.0.129:6080/vnc.html?vmid={vmid}"}

# Health + Profile
@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/api/users/profile")
async def profile():
    return {"id": 1, "username": "admin", "role": "admin"}

from app.routes import tests

app.include_router(tests.router, prefix="/api/tests", tags=["tests"])
# app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
# app.include_router(users.router, prefix="/api/users", tags=["users"])
# app.include_router(admin.router, prefix="/api/admin", tags=["admin"])

print("✅ FULL POSTGRESQL BACKEND READY!")
