from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base
from app.models.user import User

"""
Admin management routes
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models.user import User
from app.models.schemas import CreateUserRequest, CreateUserResponse, UserResponse
from app.security import generate_initial_password, hash_password
from app.utils.auth import get_current_user, require_role
from app.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

@router.post("/users/create", response_model=CreateUserResponse)
async def create_user(
    request: CreateUserRequest,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    """Create new user (admin only)"""
    
    # Check if user already exists
    result = await db.execute(select(User).where(User.username == request.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Generate initial password
    password = generate_initial_password()
    
    # Create user
    user = User(
        username=request.username,
        email=request.email,
        password_hash=hash_password(password),
        role=request.role,
        is_active=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    logger.info(f"User created by admin: {user.username}")
    
    return CreateUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        initial_password=password,
        created_at=user.created_at,
    )

@router.get("/users", response_model=list[UserResponse])
async def list_users(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    """List all users (admin only)"""
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [UserResponse.model_validate(u) for u in users]

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    """Delete user (admin only)"""
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    await db.delete(user)
    await db.commit()
    
    logger.info(f"User deleted by admin: {user.username}")
    
    return {"message": "User deleted successfully"}
