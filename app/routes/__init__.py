# app/routes/__init__.py
from fastapi import APIRouter
from . import auth, users, admin  # ← DODANE admin

def create_router() -> APIRouter:
    root_router = APIRouter()
    root_router.include_router(auth.router)
    root_router.include_router(users.router)
    root_router.include_router(admin.router)  # ← DODANE!
    return root_router
