from enum import Enum
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class VMStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    DELETED = "deleted"

class VM(Base):
    __tablename__ = "user_vms"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    proxmox_vm_id = Column(Integer, unique=True, nullable=False)
    vm_name = Column(String(255), nullable=False)
    status = Column(SQLEnum(VMStatus), default=VMStatus.CREATED)
    created_at = Column(DateTime, server_default=func.now())
    runtime_expires_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="vms")
