"""
Virtual Machine Pydantic Schemas
=================================
Request/Response schematy dla API VM.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ============================================================================
# ENUMS (dla Pydantic)
# ============================================================================

class VMStatusSchema(str, Enum):
    """Status VM dla API"""
    CREATED = "created"
    PROVISIONING = "provisioning"
    READY = "ready"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    DELETED = "deleted"


# ============================================================================
# REQUEST SCHEMAS
# ============================================================================

class CreateVMRequest(BaseModel):
    """
    POST /api/vm/create
    Brak parametrów — wszystko jest automatyczne.
    """
    pass


class StartVMRequest(BaseModel):
    """POST /api/vm/{vm_id}/start"""
    pass


class StopVMRequest(BaseModel):
    """POST /api/vm/{vm_id}/stop"""
    pass


class RebootVMRequest(BaseModel):
    """POST /api/vm/{vm_id}/reboot"""
    pass


class ResetVMRequest(BaseModel):
    """
    POST /api/vm/{vm_id}/reset
    Reset do stanu czystego (nowy VMID, stare IP).
    """
    pass


class DeleteVMRequest(BaseModel):
    """DELETE /api/vm/{vm_id}"""
    pass


class ExtendTimeRequest(BaseModel):
    """
    POST /api/vm/{vm_id}/extend
    Przedłużenie czasu działania VM.
    """
    extension_minutes: int = Field(..., ge=5, le=60, description="Minuty (5-60)")

    class Config:
        json_schema_extra = {
            "example": {"extension_minutes": 15}
        }


# ============================================================================
# RESPONSE SCHEMAS
# ============================================================================

class VMResponse(BaseModel):
    """
    Pełne dane maszyny wirtualnej.
    Używane w GET /api/vm/{vm_id} i GET /api/vm
    """
    id: int
    user_id: int
    proxmox_vm_id: int
    vm_name: str
    vm_status: VMStatusSchema
    ip_address: Optional[str] = None
    created_at: datetime
    runtime_expires_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "user_id": 5,
                "proxmox_vm_id": 200,
                "vm_name": "user-vm-5-1702199400",
                "vm_status": "running",
                "ip_address": "192.168.100.100",
                "created_at": "2025-12-10T14:30:00",
                "runtime_expires_at": "2025-12-10T26:30:00",
                "last_active_at": "2025-12-10T14:45:00"
            }
        }


class CreateVMResponse(BaseModel):
    """
    POST /api/vm/create
    Response z danymi nowo utworzonej VM.
    """
    id: int
    proxmox_vm_id: int
    vm_name: str
    ip_address: str
    vm_status: VMStatusSchema = VMStatusSchema.CREATED
    created_at: datetime

    class Config:
        from_attributes = True


class StartVMResponse(BaseModel):
    """POST /api/vm/{vm_id}/start"""
    vm_id: int
    vm_status: VMStatusSchema = VMStatusSchema.RUNNING
    runtime_expires_at: datetime
    message: str = "VM started successfully"


class StopVMResponse(BaseModel):
    """POST /api/vm/{vm_id}/stop"""
    vm_id: int
    vm_status: VMStatusSchema = VMStatusSchema.STOPPED
    message: str = "VM stopped successfully"


class RebootVMResponse(BaseModel):
    """POST /api/vm/{vm_id}/reboot"""
    vm_id: int
    vm_status: VMStatusSchema = VMStatusSchema.RUNNING
    runtime_expires_at: datetime
    message: str = "VM rebooting..."


class ResetVMResponse(BaseModel):
    """POST /api/vm/{vm_id}/reset"""
    vm_id: int
    old_proxmox_vm_id: int
    new_proxmox_vm_id: int
    ip_address: str  # Ta sama IP co przed
    vm_status: VMStatusSchema = VMStatusSchema.READY
    message: str = "VM reset successfully"


class ExtendTimeResponse(BaseModel):
    """POST /api/vm/{vm_id}/extend"""
    vm_id: int
    extension_minutes: int
    new_runtime_expires_at: datetime
    message: str = "Runtime extended successfully"


class DeleteVMResponse(BaseModel):
    """DELETE /api/vm/{vm_id}"""
    vm_id: int
    vm_status: VMStatusSchema = VMStatusSchema.DELETED
    message: str = "VM deleted successfully"


class VNCUrlResponse(BaseModel):
    """
    GET /api/vm/{vm_id}/vnc-url
    URL do noVNC konsoli.
    """
    vnc_url: str
    expires_in_seconds: int
    vm_id: int

    class Config:
        json_schema_extra = {
            "example": {
                "vnc_url": "https://novnc.example.com/vnc/?path=vm-200-token-xyz",
                "expires_in_seconds": 1800,
                "vm_id": 200
            }
        }


class VMStatsResponse(BaseModel):
    """
    GET /api/vm/{vm_id}/stats
    Live statystyki VM (opcjonalnie).
    """
    vm_id: int
    cpu_usage_percent: float
    memory_usage_mb: int
    memory_total_mb: int
    disk_usage_gb: float
    disk_total_gb: float
    uptime_seconds: int
    network_in_bytes: int
    network_out_bytes: int

    class Config:
        json_schema_extra = {
            "example": {
                "vm_id": 200,
                "cpu_usage_percent": 25.5,
                "memory_usage_mb": 512,
                "memory_total_mb": 2048,
                "disk_usage_gb": 5.2,
                "disk_total_gb": 20.0,
                "uptime_seconds": 3600,
                "network_in_bytes": 1024000,
                "network_out_bytes": 512000
            }
        }


class ListVMsResponse(BaseModel):
    """
    GET /api/vm
    Lista VM użytkownika.
    """
    vms: List[VMResponse]
    count: int

    class Config:
        json_schema_extra = {
            "example": {
                "vms": [
                    {
                        "id": 1,
                        "user_id": 5,
                        "proxmox_vm_id": 200,
                        "vm_name": "user-vm-5-1702199400",
                        "vm_status": "running",
                        "ip_address": "192.168.100.100",
                        "created_at": "2025-12-10T14:30:00",
                        "runtime_expires_at": "2025-12-10T26:30:00"
                    }
                ],
                "count": 1
            }
        }


class ErrorResponse(BaseModel):
    """Standardowa odpowiedź błędu"""
    detail: str
    error_code: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_schema_extra = {
            "example": {
                "detail": "User already has a VM",
                "error_code": "VM_ALREADY_EXISTS",
                "timestamp": "2025-12-10T14:30:00"
            }
        }