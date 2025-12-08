from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base
from app.models.user import User

"""
Virtual Machine management routes
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.user import User
from app.models.vm import VM
from app.models.schemas import VMResponse, ExtendTimeRequest, VNCUrlResponse
from app.services.vm_service import VMService
from app.utils.auth import get_current_user

router = APIRouter()
vm_service = VMService()

@router.post("/create", response_model=VMResponse)
async def create_vm(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create new VM from template and auto-start"""
    vm = await vm_service.create_and_start_vm(db, current_user.id)
    if not vm:
        raise HTTPException(status_code=400, detail="Failed to create VM")
    return VMResponse.model_validate(vm)

@router.post("/{vm_id}/start")
async def start_vm(
    vm_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Start VM"""
    success = await vm_service.start_vm(db, current_user.id, vm_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start VM")
    return {"message": "VM started successfully"}

@router.post("/{vm_id}/stop")
async def stop_vm(
    vm_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Stop VM"""
    success = await vm_service.stop_vm(db, current_user.id, vm_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to stop VM")
    return {"message": "VM stopped successfully"}

@router.post("/{vm_id}/reboot")
async def reboot_vm(
    vm_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Reboot VM"""
    success = await vm_service.reboot_vm(db, current_user.id, vm_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to reboot VM")
    return {"message": "VM rebooted successfully"}

@router.post("/{vm_id}/reset")
async def reset_vm(
    vm_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Reset VM to fresh template image"""
    vm = await vm_service.reset_vm(db, current_user.id, vm_id)
    if not vm:
        raise HTTPException(status_code=400, detail="Failed to reset VM")
    return VMResponse.model_validate(vm)

@router.post("/{vm_id}/extend")
async def extend_time(
    vm_id: int,
    request: ExtendTimeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Extend VM runtime"""
    success = await vm_service.extend_runtime(db, current_user.id, vm_id, request.extension_minutes)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to extend time")
    return {"message": "Time extended successfully"}

@router.delete("/{vm_id}")
async def delete_vm(
    vm_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete VM"""
    success = await vm_service.delete_vm(db, current_user.id, vm_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete VM")
    return {"message": "VM deleted successfully"}

@router.get("/{vm_id}/vnc-url", response_model=VNCUrlResponse)
async def get_vnc_url(
    vm_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get noVNC console URL"""
    url = await vm_service.get_vnc_url(db, current_user.id, vm_id)
    if not url:
        raise HTTPException(status_code=400, detail="Failed to generate VNC URL")
    return VNCUrlResponse(vnc_url=url, expires_in_minutes=30)
