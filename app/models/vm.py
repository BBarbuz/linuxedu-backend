from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, 
    Enum as SQLEnum, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import INET
from datetime import datetime
from enum import Enum
from app.database import Base


# ============================================================================
# ENUMS
# ============================================================================

class VMStatus(str, Enum):
    """Status maszyny wirtualnej"""
    CREATING = "creating"
    CREATED = "created"
    PROVISIONING = "provisioning"
    READY = "ready"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    DELETED = "deleted"


class IPStatus(str, Enum):
    """Status adresu IP"""
    FREE = "free"
    ALLOCATED = "allocated"
    RESERVED = "reserved"


class SSHKeyType(str, Enum):
    """Typ klucza SSH"""
    ED25519 = "ed25519"
    RSA = "rsa"


# ============================================================================
# MODELS
# ============================================================================

class VM(Base):
    __tablename__ = "users_vms"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign Keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Proxmox Identifiers
    proxmox_vm_id = Column(Integer, nullable=False, unique=True, index=True)
    vm_name = Column(String(255), nullable=False)

    # Status
    vm_status = Column(SQLEnum(VMStatus), nullable=False, default=VMStatus.CREATED)

    # Node Name
    node = Column(String(255), nullable=False, default="inz1borysmaciej")  

    # Network
    ip_address = Column(INET, nullable=True, unique=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    runtime_expires_at = Column(DateTime, nullable=True)
    last_active_at = Column(DateTime, nullable=True)
    auto_delete_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="vms")
    vm_metadata = relationship("VMMetadata", back_populates="vm", cascade="all, delete-orphan")

    # Constraints
    __table_args__ = (
        UniqueConstraint("user_id", "proxmox_vm_id", name="uq_user_vm_id"),
    )

    def __repr__(self):
        return f"<VM(id={self.id}, user_id={self.user_id}, proxmox_vm_id={self.proxmox_vm_id}, status={self.vm_status})>"


class VMMetadata(Base):
    __tablename__ = "vms_metadata"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign Keys
    vm_id = Column(Integer, ForeignKey("users_vms.proxmox_vm_id"), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ssh_key_id = Column(Integer, ForeignKey("ssh_keys.id"), nullable=True)

    # Details
    vm_name = Column(String(255), nullable=False)
    node = Column(String(50), nullable=False, default="inz1borysmaciej")
    status = Column(String(20), nullable=False, default="provisioning")
    ip_address = Column(INET, nullable=True)
    template_id = Column(Integer, nullable=False, default=100)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    vm = relationship("VM", back_populates="vm_metadata")
    ssh_key = relationship("SSHKey")

    def __repr__(self):
        return f"<VMMetadata(vm_id={self.vm_id}, node={self.node}, status={self.status})>"


class AllocatedIP(Base):
    __tablename__ = "allocated_ips"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(INET, nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    vm_id = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="free")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    released_at = Column(DateTime, nullable=True)

class VMIDSequence(Base):
    __tablename__ = "vm_id_sequence"

    # Primary Key
    id = Column(Integer, primary_key=True, default=1)

    # Counter
    next_id = Column(Integer, nullable=False, default=200)
    last_allocated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<VMIDSequence(next_id={self.next_id})>"


class SSHKey(Base):
    __tablename__ = "ssh_keys"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Details
    key_name = Column(String(255), nullable=False, unique=True)
    public_key = Column(Text, nullable=False)
    key_type = Column(SQLEnum(SSHKeyType), nullable=False)
    fingerprint = Column(String(255), nullable=True, unique=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<SSHKey(name={self.key_name}, type={self.key_type}, active={self.is_active})>"