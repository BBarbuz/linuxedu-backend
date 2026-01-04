# from fastapi import APIRouter, Depends, HTTPException, status
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# from typing import List
# import secrets

# from app.database import get_db
# from app.models.user import User
# from app.models import VM
# from app.security import hash_password
# from app.utils.auth import get_current_user, require_role
# from app.schemas.requests import (
#     CreateUserRequest, 
#     CreateUserResponse, 
#     UserResponse
# )
# from sqlalchemy import select
# from app.models import User, VM
# from app.services.vm_services import VMService, ProxmoxService, AnsibleService
# from app.config import settings
# from app.database import get_db
# from app.utils.auth import require_role


# router = APIRouter(prefix="/api/admin", tags=["admin"])

# @router.post("/users/create", response_model=CreateUserResponse)
# async def create_user(
#     request: CreateUserRequest,
#     current_user: User = Depends(require_role("admin")),
#     db: AsyncSession = Depends(get_db)
# ):
#     """Create new user (admin only)"""
    
#     # Check if user already exists
#     result = await db.execute(select(User).where(User.username == request.username))
#     if result.scalar_one_or_none():
#         raise HTTPException(status_code=400, detail="Username already exists")
    
#     # Generate initial password
#     initial_password = secrets.token_urlsafe(12)
    
#     # Create user
#     user = User(
#         username=request.username,
#         email=request.email,
#         password_hash=hash_password(initial_password),
#         role=request.role or "user",
#         is_active=True,
#     )
    
#     db.add(user)
#     await db.commit()
#     await db.refresh(user)
    
#     print(f"✅ Admin {current_user.username} stworzył użytkownika: {user.username} (ID={user.id})")
    
#     return CreateUserResponse(
#         id=user.id,
#         username=user.username,
#         email=user.email,
#         initial_password=initial_password,
#         created_at=user.created_at,
#     )

# @router.get("/users", response_model=List[UserResponse])
# async def list_users(
#     current_user: User = Depends(require_role("admin")),
#     db: AsyncSession = Depends(get_db)
# ):
#     """List all users (admin only)"""
#     result = await db.execute(select(User).order_by(User.created_at.desc()))
#     users = result.scalars().all()
#     return [UserResponse.model_validate(u) for u in users]


# def get_proxmox_service() -> ProxmoxService:
#     return ProxmoxService(settings)

# def get_ansible_service() -> AnsibleService:
#     return AnsibleService(settings)

# def get_vm_service(
#     proxmox: ProxmoxService = Depends(get_proxmox_service),
#     ansible: AnsibleService = Depends(get_ansible_service),
# ) -> VMService:
#     return VMService(proxmox_service=proxmox, ansible_service=ansible)

# @router.delete("/users/{user_id}")
# async def delete_user(
#     user_id: int,
#     current_user: User = Depends(require_role("admin")),
#     db: AsyncSession = Depends(get_db),
#     vm_service: VMService = Depends(get_vm_service),
# ):
#     user = await db.get(User, user_id)
#     if not user:
#         raise HTTPException(status_code=404, detail="User not found")
    
#     if user.id == current_user.id:
#         raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
#     # Take all users vm's
#     result = await db.execute(
#         select(VM).where(VM.user_id == user_id)
#     )
#     vms = result.scalars().all()
    
#     # Delete every VM using VMService (Proxmox destroy + DB + IP)
#     for vm in vms:
#         await vm_service.delete_vm(vm.id, user_id=user_id, db=db)
    
#     # Delete user
#     username = user.username
#     await db.delete(user)
#     await db.commit()
    
#     print(f"✅ Admin {current_user.username} usunął użytkownika: {username}")
#     return {"message": f"User {username} deleted successfully"}

# app/routes/admin.py - ADMIN PANEL z wysyłką maili

import logging
import secrets
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, VM
from app.security import hash_password
from app.utils.auth import require_role
from app.schemas.requests import (
    CreateUserRequest,
    CreateUserResponse,
    UserResponse,
)
from app.services.vm_services import VMService, ProxmoxService, AnsibleService
from app.services.email_service import get_email_service
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_proxmox_service() -> ProxmoxService:
    return ProxmoxService(settings)


def get_ansible_service() -> AnsibleService:
    return AnsibleService(settings)


def get_vm_service(
    proxmox: ProxmoxService = Depends(get_proxmox_service),
    ansible: AnsibleService = Depends(get_ansible_service),
) -> VMService:
    return VMService(proxmox_service=proxmox, ansible_service=ansible)


@router.post("/users/create", response_model=CreateUserResponse)
async def create_user(
    request: CreateUserRequest,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
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
        is_active=True,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    # === NOWE: wyślij email z hasłem ===
    email_service = get_email_service()
    email_sent = email_service.send_password_email(
        to_email=request.email,
        username=request.username,
        password=initial_password,
    )

    if email_sent:
        logger.info(f"✅ Email wysłany do {request.email}")
    else:
        logger.warning(
            f"⚠️ Użytkownik {request.username} utworzony, ale email nie poszedł do {request.email}"
        )

    logger.info(
        f"✅ Admin {current_user.username} stworzył użytkownika: {user.username} (ID={user.id})"
    )

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
    db: AsyncSession = Depends(get_db),
):
    """List all users (admin only)"""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [UserResponse.model_validate(u) for u in users]


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
    vm_service: VMService = Depends(get_vm_service),
):
    """Delete user (admin only)"""

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    # Take all user's VMs
    result = await db.execute(select(VM).where(VM.user_id == user_id))
    vms = result.scalars().all()

    # Delete every VM using VMService (Proxmox destroy + DB + IP)
    for vm in vms:
        await vm_service.delete_vm(vm.id, user_id=user_id, db=db)

    # Delete user
    username = user.username
    await db.delete(user)
    await db.commit()

    logger.info(f"✅ Admin {current_user.username} usunął użytkownika: {username}")
    return {"message": f"User {username} deleted successfully"}
