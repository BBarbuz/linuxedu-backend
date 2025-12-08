from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import os
import json

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
    APP_VERSION: str = "1.0.0"
    
    # Database - PEŁNE POLA!
    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30          # ← DODANE!
    DB_POOL_RECYCLE: int = 3600        # ← DODANE!
    DB_ECHO: bool = False
    DB_ECHO_SQL: bool = False          # ← DODANE!
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # Proxmox
    PROXMOX_HOST: str
    PROXMOX_PORT: int = 8006
    PROXMOX_USER: str = "root@pam"
    PROXMOX_TOKEN: str
    PROXMOX_VERIFY_SSL: bool = False
    PROXMOX_TEMPLATE_VMID: int = 100
    PROXMOX_NODE: str = "pve"
    VM_STORAGE: str = "local-lvm"
    VM_DEFAULT_TIMEOUT_SECONDS: int = 43200
    
    # CORS
    ALLOWED_ORIGINS: List[str]
    
    # Ansible
    ANSIBLE_HOST: str = "localhost"
    ANSIBLE_USER: str = "ubuntu"
    ANSIBLE_SSH_KEY_PATH: str = "/opt/linuxedu/backend/ssh_keys/id_rsa"

settings = Settings()
print("✅ Config loaded successfully!")
