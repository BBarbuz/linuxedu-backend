# app/routes/__init__.py
from fastapi import APIRouter
from . import auth, users, admin, tests, vms  # ← DODANE tests

def create_router() -> APIRouter:
    root_router = APIRouter()
    root_router.include_router(auth.router)
    root_router.include_router(users.router)
    root_router.include_router(admin.router)
    root_router.include_router(tests.router)  # ← DODANE!
    root_router.include_router(vms.router)  # ← DODANE!
    return root_router
