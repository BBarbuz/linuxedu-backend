from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from datetime import datetime, timedelta
import uuid
from app.database import get_db
from app.models.user import User
from app.models.vm import VM, VMStatus
from app.utils.auth import get_current_user
from app.schemas.requests import VMResponse

router = APIRouter(prefix="/api/vm", tags=["vms"])

@router.post("/create")
async def create_vm(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Stwórz nową VM dla użytkownika"""
    
    # Sprawdź czy user już ma VM
    result = await db.execute(
        select(VM).where(
            VM.user_id == current_user.id,
            VM.status != VMStatus.DELETED
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User already has a VM")
    
    # Generuj VM ID i nazwę
    proxmox_vm_id = int(str(uuid.uuid4())[:8], 16) % 1000 + 100
    vm_name = f"user-vm-{current_user.id}-{int(datetime.now().timestamp())}"
    
    # Stwórz VM w bazie
    vm = VM(
        user_id=current_user.id,
        proxmox_vm_id=proxmox_vm_id,
        vm_name=vm_name,
        status=VMStatus.CREATED
    )
    
    db.add(vm)
    await db.commit()
    await db.refresh(vm)
    
    print(f"✅ VM created: {vm_name} (ID={proxmox_vm_id})")
    
    return {
        "id": vm.id,
        "proxmox_vm_id": vm.proxmox_vm_id,
        "vm_name": vm.vm_name,
        "status": "creating"
    }

@router.get("")
async def list_vms(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Pobierz listę VMs użytkownika"""
    result = await db.execute(
        select(VM).where(VM.user_id == current_user.id)
    )
    vms = result.scalars().all()
    return [VMResponse.model_validate(vm) for vm in vms]

@router.post("/{vm_id}/start")
async def start_vm(
    vm_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Uruchom VM"""
    vm = await db.get(VM, vm_id)
    
    if not vm or vm.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="VM not found")
    
    vm.status = VMStatus.RUNNING
    vm.runtime_expires_at = datetime.now() + timedelta(hours=12)
    
    await db.commit()
    await db.refresh(vm)
    
    print(f"✅ VM started: {vm.vm_name}")
    
    return {
        "status": "running",
        "runtime_expires_at": vm.runtime_expires_at
    }

@router.post("/{vm_id}/stop")
async def stop_vm(
    vm_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Zatrzymaj VM"""
    vm = await db.get(VM, vm_id)
    
    if not vm or vm.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="VM not found")
    
    vm.status = VMStatus.STOPPED
    vm.runtime_expires_at = None
    
    await db.commit()
    
    print(f"✅ VM stopped: {vm.vm_name}")
    
    return {"status": "stopped"}

@router.post("/{vm_id}/extend")
async def extend_vm_time(
    vm_id: int,
    extension_minutes: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Przedłuż czas działania VM"""
    
    if extension_minutes < 5 or extension_minutes > 60:
        raise HTTPException(
            status_code=400,
            detail="Extension must be between 5 and 60 minutes"
        )
    
    vm = await db.get(VM, vm_id)
    
    if not vm or vm.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="VM not found")
    
    if vm.status != VMStatus.RUNNING:
        raise HTTPException(status_code=400, detail="VM not running")
    
    max_runtime = datetime.now() + timedelta(hours=12)
    new_expiry = vm.runtime_expires_at + timedelta(minutes=extension_minutes)
    
    if new_expiry > max_runtime:
        raise HTTPException(
            status_code=400,
            detail="Cannot extend beyond 12 hours limit"
        )
    
    vm.runtime_expires_at = new_expiry
    
    await db.commit()
    await db.refresh(vm)
    
    print(f"✅ VM extended: {vm.vm_name}")
    
    return {
        "status": "extended",
        "new_expiry": vm.runtime_expires_at
    }

@router.delete("/{vm_id}")
async def delete_vm(
    vm_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Usuń VM"""
    vm = await db.get(VM, vm_id)
    
    if not vm or vm.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="VM not found")
    
    vm.status = VMStatus.DELETED
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

    await db.commit()
    
    print(f"✅ VM deleted: {vm.vm_name}")
    
    return {"message": "VM deleted"}
