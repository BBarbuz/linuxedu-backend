from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_ignore_empty=True,
        extra='ignore'
    )
    
    # Application
    ENVIRONMENT: str = "production"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    
    # Database
    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 10
    
    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # ===== PROXMOX =====
    PROXMOX_HOST: str
    PROXMOX_PORT: int = 8006
    PROXMOX_USER: str = "root@pam"
    PROXMOX_TOKEN: str
    PROXMOX_TOKEN_ID: str
    PROXMOX_VERIFY_SSL: bool
    PROXMOX_NODES: List[str] = ["pve", "pve2", "pve3"]
    PROXMOX_PRIMARY_NODE: str = "pve"
    PROXMOX_NODE: str = "pve"  # Dla kompatybilności
    
    # ===== CEPH STORAGE =====
    CEPH_POOL: str = "CephStorage"  # ✅ POPRAWNIE! ID z Proxmoxu
    CEPH_MONITOR_HOSTS: str = "192.168.0.11:6789,192.168.0.12:6789,192.168.0.13:6789"
    CEPH_KEYRING_PATH: str = "/etc/ceph/ceph.client.admin.keyring"
    CEPH_CONFIG_PATH: str = "/etc/ceph/ceph.conf"
    CEPH_MIN_FREE_GB: int = 10
    CEPH_HEALTH_CHECK_INTERVAL: int = 60
    
    # ===== VM STORAGE =====
    VM_STORAGE: str = "CephStorage"  # ✅ POPRAWNIE! Główny dysk: Ceph RBD
    VM_CLOUDINIT_STORAGE: str = "local-lvm"  # Cloud-init: local
    VM_SCSI_CONTROLLER: str = "virtio-scsi-pci"
    VM_QCOW2_PATH: str = "/var/lib/vz/template/qcow2/linuxedu-template.qcow2"
    VM_QCOW2_PATHS: dict = {
        "pve": "/var/lib/vz/template/qcow2/linuxedu-template.qcow2",
        "pve2": "/var/lib/vz/template/qcow2/linuxedu-template.qcow2",
        "pve3": "/var/lib/vz/template/qcow2/linuxedu-template.qcow2",
    }
    VM_IMPORT_TIMEOUT_SECONDS: int = 180
    VM_DEFAULT_TIMEOUT_SECONDS: int = 43200  # 12h
    VM_IP_RANGE: str = "192.168.100.100/200"
    VM_DEFAULT_CORES: int = 2
    VM_DEFAULT_MEMORY_MB: int = 2048
    VM_DEFAULT_DISK_GB: int = 20
    VM_CLOUDINIT_DISK_GB: int = 2
    VM_AUTO_DELETE_DAYS: int = 14
    
    # ===== HA CONFIGURATION =====
    HA_ENABLED: bool = True
    HA_GROUP: str = "default"
    HA_MIGRATION_DELAY: int = 60
    
    # ===== LOAD BALANCING =====
    LOAD_BALANCING_ENABLED: bool = True  # ✅ NOWE: Load balancing
    CPU_THRESHOLD_PERCENT: float = 80.0  # Jeśli nod >80% CPU, nie tworz tu
    MEMORY_THRESHOLD_PERCENT: float = 80.0  # Jeśli nod >80% RAM, nie tworz tu
    
    # ===== VM MONITORING =====
    VM_NODE_CHECK_INTERVAL: int = 30
    VM_MIGRATION_ALERT_ENABLED: bool = True
    
    # ===== ANSIBLE =====
    ANSIBLE_USER: str = "root"
    ANSIBLE_SSH_KEY_PATH: str = "/root/.ssh/ansible_key"
    ANSIBLE_PLAYBOOKS_DIR: str = "/opt/linuxedu/backend/playbooks"
    ANSIBLE_TIMEOUT_SECONDS: int = 600
    ANSIBLE_RETRIES: int = 3
    ANSIBLE_PLAYBOOKS_PATH: str = "/opt/linuxedu/backend/playbooks"  # Dla kompatybilności
    ANSIBLE_VERBOSITY: int = 0
    ANSIBLE_EXECUTION_TIMEOUT_SECONDS: int = 600
    
    # CORS
    ALLOWED_ORIGINS: List[str] = ["https://192.168.0.129:3000", "http://localhost:3000"]

settings = Settings()
print("✅ Config loaded successfully!")