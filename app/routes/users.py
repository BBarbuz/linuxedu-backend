# app/routes/users.py - PROFIL UŻYTKOWNIKA
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User
from app.utils.auth import get_current_user
from app.schemas.requests import UserResponse

router = APIRouter(prefix="/api/users", tags=["users"])

@router.get("/profile", response_model=UserResponse)
async def get_profile(current_user: User = Depends(get_current_user)):
    """Pobierz profil zalogowanego użytkownika"""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email or "",
        role=current_user.role,
        is_active=current_user.is_active
    )