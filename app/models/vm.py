"""
Virtual Machine ORM model
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
from enum import Enum

from app.database import Base

class VMStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    DELETED = "deleted"
    CREATING = "creating"
    DELETING = "deleting"

class VM(Base):
    __tablename__ = "users_vms"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    vm_id = Column(Integer, unique=True, nullable=False)  # Proxmox VMID
    vm_name = Column(String(255), nullable=False)
    vm_status = Column(SQLEnum(VMStatus), default=VMStatus.STOPPED, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    max_runtime = Column(Integer, default=43200, nullable=False)  # 12 hours in seconds
    runtime_expires_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="vms")
    
    def is_running(self) -> bool:
        return self.vm_status == VMStatus.RUNNING
