"""
Virtual Machine management service
"""

import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.vm import VM, VMStatus
from app.models.user import User
from app.config import settings
import requests
import json

logger = logging.getLogger(__name__)

class VMService:
    def __init__(self):
        self.proxmox_api_url = f"https://{settings.PROXMOX_HOST}:{settings.PROXMOX_PORT}/api2/json"
        self.headers = {
            "Authorization": f"PVEAPIToken={settings.PROXMOX_TOKEN}",
            "Content-Type": "application/json"
        }
    
    async def create_and_start_vm(self, db: AsyncSession, user_id: int) -> VM:
        """Create new VM from template and auto-start it"""
        try:
            # Check if user already has VM
            result = await db.execute(
                select(VM).where(
                    (VM.user_id == user_id) &
                    (VM.vm_status != VMStatus.DELETED)
                )
            )
            if result.scalar_one_or_none():
                logger.warning(f"User {user_id} already has active VM")
                return None
            
            # Find next available VMID
            next_vmid = await self._get_next_vmid(db)
            vm_name = f"user-vm-{user_id}-{int(datetime.now(timezone.utc).timestamp())}"
            
            # Clone template
            clone_params = {
                "newid": next_vmid,
                "name": vm_name,
                "storage": settings.VM_STORAGE,
                "full": True,
            }
            
            clone_url = f"{self.proxmox_api_url}/nodes/{settings.PROXMOX_NODE}/qemu/{settings.PROXMOX_TEMPLATE_VMID}/clone"
            response = requests.post(
                clone_url,
                headers=self.headers,
                json=clone_params,
                verify=settings.PROXMOX_VERIFY_SSL,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to clone VM: {response.text}")
                return None
            
            logger.info(f"VM cloned: {next_vmid} for user {user_id}")
            
            # Save to database
            vm = VM(
                user_id=user_id,
                vm_id=next_vmid,
                vm_name=vm_name,
                vm_status=VMStatus.CREATING,
            )
            db.add(vm)
            await db.commit()
            await db.refresh(vm)
            
            # Start VM
            await self._poll_vm_ready(next_vmid)
            await self.start_vm(db, user_id, vm.id)
            
            # Reload from DB
            await db.refresh(vm)
            return vm
            
        except Exception as e:
            logger.error(f"Error creating VM for user {user_id}: {e}")
            return None
    
    async def start_vm(self, db: AsyncSession, user_id: int, vm_id: int) -> bool:
        """Start VM and set runtime timeout"""
        try:
            vm = await self._get_user_vm(db, user_id, vm_id)
            if not vm:
                return False
            
            # Start VM via Proxmox API
            start_url = f"{self.proxmox_api_url}/nodes/{settings.PROXMOX_NODE}/qemu/{vm.vm_id}/status/start"
            response = requests.post(
                start_url,
                headers=self.headers,
                verify=settings.PROXMOX_VERIFY_SSL,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to start VM {vm.vm_id}: {response.text}")
                return False
            
            # Update database
            vm.vm_status = VMStatus.RUNNING
            vm.runtime_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=settings.VM_DEFAULT_TIMEOUT_SECONDS
            )
            await db.commit()
            
            logger.info(f"VM {vm.vm_id} started for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error starting VM: {e}")
            return False
    
    async def stop_vm(self, db: AsyncSession, user_id: int, vm_id: int) -> bool:
        """Stop VM"""
        try:
            vm = await self._get_user_vm(db, user_id, vm_id)
            if not vm:
                return False
            
            stop_url = f"{self.proxmox_api_url}/nodes/{settings.PROXMOX_NODE}/qemu/{vm.vm_id}/status/shutdown"
            response = requests.post(
                stop_url,
                headers=self.headers,
                verify=settings.PROXMOX_VERIFY_SSL,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to stop VM {vm.vm_id}: {response.text}")
                return False
            
            vm.vm_status = VMStatus.STOPPED
            vm.runtime_expires_at = None
            await db.commit()
            
            logger.info(f"VM {vm.vm_id} stopped for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping VM: {e}")
            return False
    
    async def reboot_vm(self, db: AsyncSession, user_id: int, vm_id: int) -> bool:
        """Reboot VM"""
        try:
            vm = await self._get_user_vm(db, user_id, vm_id)
            if not vm:
                return False
            
            reboot_url = f"{self.proxmox_api_url}/nodes/{settings.PROXMOX_NODE}/qemu/{vm.vm_id}/status/reboot"
            response = requests.post(
                reboot_url,
                headers=self.headers,
                verify=settings.PROXMOX_VERIFY_SSL,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to reboot VM {vm.vm_id}: {response.text}")
                return False
            
            logger.info(f"VM {vm.vm_id} rebooted for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error rebooting VM: {e}")
            return False
    
    async def reset_vm(self, db: AsyncSession, user_id: int, vm_id: int) -> VM:
        """Reset VM to fresh template image"""
        try:
            # Delete current VM
            if not await self.delete_vm(db, user_id, vm_id):
                return None
            
            # Create new VM
            vm = await self.create_and_start_vm(db, user_id)
            return vm
            
        except Exception as e:
            logger.error(f"Error resetting VM: {e}")
            return None
    
    async def delete_vm(self, db: AsyncSession, user_id: int, vm_id: int) -> bool:
        """Delete VM"""
        try:
            vm = await self._get_user_vm(db, user_id, vm_id)
            if not vm:
                return False
            
            # Stop first
            if vm.vm_status == VMStatus.RUNNING:
                await self.stop_vm(db, user_id, vm_id)
            
            # Delete via Proxmox API
            delete_url = f"{self.proxmox_api_url}/nodes/{settings.PROXMOX_NODE}/qemu/{vm.vm_id}"
            response = requests.delete(
                delete_url,
                headers=self.headers,
                verify=settings.PROXMOX_VERIFY_SSL,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to delete VM {vm.vm_id}: {response.text}")
                return False
            
            # Mark as deleted in DB
            vm.vm_status = VMStatus.DELETED
            await db.commit()
            
            logger.info(f"VM {vm.vm_id} deleted for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting VM: {e}")
            return False
    
    async def extend_runtime(self, db: AsyncSession, user_id: int, vm_id: int, minutes: int) -> bool:
        """Extend VM runtime"""
        try:
            vm = await self._get_user_vm(db, user_id, vm_id)
            if not vm or vm.vm_status != VMStatus.RUNNING:
                return False
            
            # Max 12 hours from now
            max_time = datetime.now(timezone.utc) + timedelta(hours=12)
            new_expiry = vm.runtime_expires_at + timedelta(minutes=minutes)
            
            if new_expiry > max_time:
                new_expiry = max_time
            
            vm.runtime_expires_at = new_expiry
            await db.commit()
            
            logger.info(f"VM {vm.vm_id} extended by {minutes} minutes for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error extending VM runtime: {e}")
            return False
    
    async def get_vnc_url(self, db: AsyncSession, user_id: int, vm_id: int) -> str:
        """Get noVNC URL for VM console"""
        try:
            vm = await self._get_user_vm(db, user_id, vm_id)
            if not vm:
                return None
            
            vnc_url = f"https://{settings.NOVNC_HOST}:{settings.NOVNC_PORT}/vnc/?path={vm.vm_id}"
            return vnc_url
            
        except Exception as e:
            logger.error(f"Error generating VNC URL: {e}")
            return None
    
    # ===== Helper Methods =====
    
    async def _get_user_vm(self, db: AsyncSession, user_id: int, vm_id: int) -> VM:
        """Get user's VM"""
        result = await db.execute(
            select(VM).where(
                (VM.user_id == user_id) &
                (VM.id == vm_id) &
                (VM.vm_status != VMStatus.DELETED)
            )
        )
        return result.scalar_one_or_none()
    
    async def _get_next_vmid(self, db: AsyncSession) -> int:
        """Get next available VMID"""
        result = await db.execute(select(VM).order_by(VM.vm_id.desc()).limit(1))
        last_vm = result.scalar_one_or_none()
        return (last_vm.vm_id + 1) if last_vm else 200
    
    async def _poll_vm_ready(self, vm_id: int) -> bool:
        """Poll Proxmox until VM is ready"""
        for attempt in range(10):
            try:
                status_url = f"{self.proxmox_api_url}/nodes/{settings.PROXMOX_NODE}/qemu/{vm_id}/status/current"
                response = requests.get(
                    status_url,
                    headers=self.headers,
                    verify=settings.PROXMOX_VERIFY_SSL,
                    timeout=10
                )
                if response.status_code == 200:
                    return True
            except:
                pass
            
            import asyncio
            await asyncio.sleep(2)
        
        return False
