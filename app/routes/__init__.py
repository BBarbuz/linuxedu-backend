from fastapi import APIRouter
from . import auth, users, admin, tests, vms

def create_router() -> APIRouter:
    root_router = APIRouter()
    root_router.include_router(auth.router)
    root_router.include_router(users.router)
    root_router.include_router(admin.router)
    root_router.include_router(tests.router)
    root_router.include_router(vms.router)
    return root_router
