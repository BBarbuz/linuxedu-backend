# app/routes/admin.py - ADMIN PANEL
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import secrets

from app.database import get_db
from app.models.user import User
from app.security import hash_password
from app.utils.auth import get_current_user, require_role
from app.schemas.requests import (
    CreateUserRequest, 
    CreateUserResponse, 
    UserResponse
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

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
    initial_password = secrets.token_urlsafe(12)
    
    # Create user
    user = User(
        username=request.username,
        email=request.email,
        password_hash=hash_password(initial_password),
        role=request.role or "user",
        is_active=True,  # Aktywuj od razu
    )
    
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    print(f"✅ Admin {current_user.username} stworzył użytkownika: {user.username} (ID={user.id})")
    
    return CreateUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        initial_password=initial_password,
        created_at=user.created_at,
    )

@router.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    """List all users (admin only)"""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
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
    
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    username = user.username
    await db.delete(user)
    await db.commit()
    
    print(f"✅ Admin {current_user.username} usunął użytkownika: {username}")
    return {"message": f"User {username} deleted successfully"}
