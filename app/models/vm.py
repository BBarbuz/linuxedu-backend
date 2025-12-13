"""
Virtual Machine Management Models
=====================================
Modele ORM dla zarządzania maszynami wirtualnymi.
Oprte na specyfikacji: Wymagania_VMs.pdf v2.0
"""

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
    CREATED = "created"              # Zarezerwowana w BD, przed Proxmoxem
    PROVISIONING = "provisioning"    # Ansible setup w toku
    READY = "ready"                  # Gotowa do użytku
    RUNNING = "running"              # Uruchomiona (timer 12h aktywny)
    STOPPED = "stopped"              # Zatrzymana
    FAILED = "failed"                # Błąd provisioning
    DELETED = "deleted"              # Oznaczona do usunięcia


class IPStatus(str, Enum):
    """Status adresu IP"""
    FREE = "free"                    # Dostępny do przydzielenia
    ALLOCATED = "allocated"          # Przydzielony VM
    RESERVED = "reserved"            # Zarezerwowany


class SSHKeyType(str, Enum):
    """Typ klucza SSH"""
    ED25519 = "ed25519"
    RSA = "rsa"


# ============================================================================
# MODELS
# ============================================================================

class VM(Base):
    """
    Tabela: users_vms
    Mapowanie użytkownika na maszynę wirtualną.
    """
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
    """
    Tabela: vms_metadata
    Szczegółowe metadane maszyny wirtualnej.
    """
    __tablename__ = "vms_metadata"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign Keys
    vm_id = Column(Integer, ForeignKey("users_vms.proxmox_vm_id"), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ssh_key_id = Column(Integer, ForeignKey("ssh_keys.id"), nullable=True)

    # Details
    vm_name = Column(String(255), nullable=False)
    node = Column(String(50), nullable=False, default="pve")  # Proxmox node name
    status = Column(String(20), nullable=False, default="provisioning")  # provisioning, ready, deleted
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
    """
    Tabela: allocated_ips
    Zarządzanie pulą adresów IP dla VM.
    """
    __tablename__ = "allocated_ips"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Details
    ip_address = Column(INET, nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    vm_id = Column(Integer, nullable=True)
    status = Column(SQLEnum(IPStatus), nullable=False, default=IPStatus.FREE, index=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    released_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<AllocatedIP(ip={self.ip_address}, status={self.status})>"


class VMIDSequence(Base):
    """
    Tabela: vm_id_sequence
    Licznik dla unikalnych VMID w Proxmoxie.
    Zawsze dokładnie jeden rekord (id=1).
    """
    __tablename__ = "vm_id_sequence"

    # Primary Key (zawsze 1)
    id = Column(Integer, primary_key=True, default=1)

    # Counter
    next_vm_id = Column(Integer, nullable=False, default=200)
    last_allocated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<VMIDSequence(next_id={self.next_vm_id})>"


class SSHKey(Base):
    """
    Tabela: ssh_keys
    Klucze SSH używane przez Ansible do provisioning'u VM.
    """
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