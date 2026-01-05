"""
Virtual Machine API Routes
==========================
Endpointy dla operacji na maszynach wirtualnych.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status, Path
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.user import User
from app.utils.auth import get_current_user
from app.schemas.vm_schemas import (
    CreateVMRequest, CreateVMResponse,
    StartVMRequest, StartVMResponse,
    StopVMRequest, StopVMResponse,
    RebootVMRequest, RebootVMResponse,
    ResetVMRequest, ResetVMResponse,
    DeleteVMRequest, DeleteVMResponse,
    ExtendTimeRequest, ExtendTimeResponse,
    ListVMsResponse, VMResponse, VNCUrlResponse, VMStatsResponse
)
from app.services.vm_services import VMService, ProxmoxService, AnsibleService
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vms", tags=["vms"])


def create_router():
    """
    Create router for VMs operations.
    """
    router = APIRouter(prefix="/api/vms", tags=["virtual_machines"])

    # Initialize services
    proxmox_service = ProxmoxService(settings)
    ansible_service = AnsibleService(settings)
    vm_service = VMService(proxmox_service, ansible_service)

    @router.post(
        "/create",
        response_model=CreateVMResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create a new virtual machine",
        description="""
        Creates a new VM for the logged-in user.

        **Pipeline:**
        1. Validation: check if the user already has a VM
        2. Allocation: assign VMID + IP from the pool
        3. Database reservation
        4. Clone the template in Proxmox
        5. Configure IP, SSH, cloud-init
        6. Start the VM
        7. Ansible provisioning

        **Duration:** ~3-5 minutes
        """
    )

    # ========================================================================
    # CREATE VM
    # ========================================================================

    async def create_vm(
        _: CreateVMRequest = None,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """Create new VM for user"""
        try:
            vm = await vm_service.create_vm(db=db, user_id=current_user.id)
            if vm is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User already has an active VM or VM creation failed",
                )
            return CreateVMResponse(
                id=vm.id,
                proxmox_vm_id=vm.proxmox_vm_id,
                vm_name=vm.vm_name,
                ip_address=vm.ip_address,
                vm_status=vm.vm_status.value,
                created_at=vm.created_at,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating VM: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create VM: {str(e)}",
            )

    # ========================================================================
    # LIST VMs
    # ========================================================================

    @router.get(
        "",
        response_model=ListVMsResponse,
        summary="Get user's VM list",
        description="Returns all non-deleted VMs assigned to the logged-in user."
    )
    async def list_vms(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ):
        """Get user's VM list"""
        try:
            vms = await vm_service.list_user_vms(db, current_user.id)
            
            vm_responses = [
                VMResponse(
                    id=vm.id,
                    user_id=vm.user_id,
                    proxmox_vm_id=vm.proxmox_vm_id,
                    vm_name=vm.vm_name,
                    vm_status=vm.vm_status.value,
                    ip_address=str(vm.ip_address) if vm.ip_address is not None else None,
                    created_at=vm.created_at,
                    runtime_expires_at=vm.runtime_expires_at,
                    last_active_at=vm.last_active_at
                )
                for vm in vms
            ]

            return ListVMsResponse(vms=vm_responses, count=len(vm_responses))

        except Exception as e:
            logger.error(f"Error listing VMs: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to list VMs"
            )

    # ========================================================================
    # GET VM DETAILS
    # ========================================================================

    @router.get(
    "/{vm_id}",
    response_model=VMResponse,
    summary="Deatailed VM",
    )
    async def get_vm(
        vm_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        try:
            vm = await vm_service.get_user_vm(vm_id, current_user.id, db)
            return VMResponse(
                id=vm.id,
                user_id=vm.user_id,
                proxmox_vm_id=vm.proxmox_vm_id,
                vm_name=vm.vm_name,
                vm_status=vm.vm_status.value,
                ip_address=str(vm.ip_address) if vm.ip_address else None,
                created_at=vm.created_at,
                runtime_expires_at=vm.runtime_expires_at,
                last_active_at=vm.last_active_at,
            )
        except Exception as e:
            logger.error(f"Error getting VM: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get VM"
            )
    
    @router.get(
    "/{vm_id}/stats",
    response_model=VMStatsResponse,
    summary="VM statistics",
    description="Fetch live VM statistics (CPU, RAM, disk, network)."
    )
    async def get_vm_stats(
        vm_id: int = Path(..., ge=1),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """Get VM statistics"""
        try:
            # Get VM z bazy
            vm = await vm_service.get_user_vm(vm_id, current_user.id, db)
            if not vm:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="VM not found"
                )
            
            # Get statistics z Proxmoxa
            stats = await vm_service.get_vm_stats(vm.proxmox_vm_id, vm.node)
            
            return VMStatsResponse(
                vm_id=vm_id,
                cpu_usage_percent=stats.get('cpu_usage_percent', 0),
                memory_usage_mb=stats.get('memory_usage_mb', 0),
                memory_total_mb=stats.get('memory_total_mb', 0),
                disk_usage_gb=stats.get('disk_usage_gb', 0),
                disk_total_gb=stats.get('disk_total_gb', 0),
                uptime_seconds=stats.get('uptime_seconds', 0),
                network_in_bytes=stats.get('network_in_bytes', 0),
                network_out_bytes=stats.get('network_out_bytes', 0),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting VM {vm_id} stats: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch VM statistics"
            )

    # ========================================================================
    # START VM
    # ========================================================================

    @router.post(
        "/{vm_id}/start",
        response_model=StartVMResponse,
        summary="Start VM",
        description="""
        Starts the VM and sets a 12-hour timer.

        After starting:
        - Status changes to RUNNING
        - runtime_expires_at = now + 12h
        - VM will stop automatically after 12 hours
        """
    )
    async def start_vm(
        vm_id: int,
        _: StartVMRequest = None,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ):
        """Start VM."""
        try:
            vm = await vm_service.start_vm(vm_id, current_user.id, db)

            return StartVMResponse(
                vm_id=vm.id,
                vm_status=vm.vm_status.value,
                runtime_expires_at=vm.runtime_expires_at,
                message="VM started successfully"
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error starting VM: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to start VM"
            )

    # ========================================================================
    # STOP VM
    # ========================================================================

    @router.post(
        "/{vm_id}/stop",
        response_model=StopVMResponse,
        summary="Stop VM",
        description="Graceful shutdown VM."
    )
    async def stop_vm(
        vm_id: int,
        _: StopVMRequest = None,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ):
        """Stop VM."""
        try:
            vm = await vm_service.stop_vm(vm_id, current_user.id, db)

            return StopVMResponse(
                vm_id=vm.id,
                vm_status=vm.vm_status.value,
                message="VM stopped successfully"
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error stopping VM: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to stop VM"
            )

    # ========================================================================
    # REBOOT VM
    # ========================================================================

    @router.post(
        "/{vm_id}/reboot",
        response_model=RebootVMResponse,
        summary="Reboot VM",
        description="""
        Graceful VM reboot (does not reset the 12h timer).
        Duration: ~30-60 seconds
        """
    )
    async def reboot_vm(
        vm_id: int,
        _: RebootVMRequest = None,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ):
        """Reboot VM."""
        try:
            vm = await vm_service.reboot_vm(vm_id, current_user.id, db)

            return RebootVMResponse(
                vm_id=vm.id,
                vm_status=vm.vm_status.value,
                runtime_expires_at=vm.runtime_expires_at,
                message="VM rebooting..."
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error rebooting VM: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to reboot VM"
            )

    # ========================================================================
    # RESET VM
    # ========================================================================

    @router.post(
        "/{vm_id}/reset",
        response_model=ResetVMResponse,
        summary="Reset VM",
        description="""
        Reset VM to clean state.

        What happens:
        - New VMID in Proxmox
        - Same IP address (released during reset)
        - All user changes are removed
        - 12h timer resets

        Duration: ~3-5 minutes
        """
    )
    async def reset_vm(
        vm_id: int,
        _: ResetVMRequest = None,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ):
        """Reset VM."""
        try:
            vm = await vm_service.reset_vm(vm_id, current_user.id, db, settings)

            return ResetVMResponse(
                vm_id=vm.id,
                old_proxmox_vm_id=vm.proxmox_vm_id - 1,
                new_proxmox_vm_id=vm.proxmox_vm_id,
                ip_address=vm.ip_address,
                vm_status=vm.vm_status.value,
                message="VM reset successfully"
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error resetting VM: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to reset VM"
            )

    # ========================================================================
    # EXTEND TIME
    # ========================================================================


    @router.post(
        "/{vm_id}/extend",
        response_model=ExtendTimeResponse,
        summary="Extend VM runtime",
        description="""
        Extend the VM runtime by 5-240 minutes (4 hours max).
        
        Conditions:
        - extension_minutes: 5-240 minutes (4 hours max per request)
        - Max total: 8 hours from now
        - VM must be RUNNING
        """,
    )
    async def extend_time(
        vm_id: int,
        request: ExtendTimeRequest,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ):
        """Extends the VM runtime by 5-240 minutes."""
        try:
            vm = await vm_service.extend_time(
                vm_id,
                current_user.id,
                request.extension_minutes,
                db
            )

            return ExtendTimeResponse(
                vm_id=vm.id,
                extension_minutes=request.extension_minutes,
                new_runtime_expires_at=vm.runtime_expires_at,
                message="Runtime extended successfully"
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error extending VM time: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to extend VM time"
            )


    # ========================================================================
    # DELETE VM
    # ========================================================================

    @router.delete(
        "/{vm_id}",
        response_model=DeleteVMResponse,
        summary="Delete VM",
        description="""
        Deletes the VM and releases all resources.

        Operation:
        - Graceful shutdown in Proxmox
        - Removal of disk and configuration from Proxmox
        - IP address release
        - Marked as DELETED in the database
        """
    )
    async def delete_vm(
        vm_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ):
        """Delete VM."""
        try:
            vm = await vm_service.delete_vm(vm_id, current_user.id, db)

            return DeleteVMResponse(
                vm_id=vm.id,
                vm_status=vm.vm_status.value,
                message="VM deleted successfully"
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting VM: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete VM"
            )

    # ========================================================================
    # VNC URL
    # ========================================================================

    @router.get(
        "/{vmid}/vnc-url",
        response_model=VNCUrlResponse,
        summary="Get URL to noVNC console",
        tags=["virtual_machines"],
        description="Generates a temporary token for noVNC console access to the VM.\n\nToken valid for 120 minutes.",
    )
    async def get_vnc_url(
        vmid: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """Get URL to noVNC console"""
        try:
            vncurl = await vm_service.get_vnc_url(vmid, current_user.id, db)
            
            if not vncurl:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to generate VNC URL"
                )
            
            return VNCUrlResponse(
                vnc_url=vncurl,
                expires_in_seconds=7200,
                vm_id=vmid,
                    )

            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting VNC URL: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate VNC URL: {str(e)}"
            )


    return router