"""
High Availability Service - konfiguracja HA dla VM
"""
import logging
from fastapi import HTTPException
from proxmoxer import ProxmoxAPI
from app.config import settings

logger = logging.getLogger(__name__)


class HAService:
    """Obsługa High Availability w Proxmoxie"""
    
    def __init__(self, proxmox: ProxmoxAPI):
        self.proxmox = proxmox
        self.enabled = settings.HA_ENABLED
        self.group = settings.HA_GROUP
        self.migration_delay = settings.HA_MIGRATION_DELAY
    
    async def enable_ha_for_vm(self, vm_id: int, node: str) -> bool:
        """
        Włącz HA dla VM.
        HA gwarantuje automatyczną restartę VM na innym nodzie jeśli bieżący umrze.
        
        Zwraca True jeśli HA została włączona.
        Raises HTTPException jeśli błąd konfiguracji.
        """
        if not self.enabled:
            logger.info(f"HA disabled, skipping configuration for VM {vm_id}")
            return False
        
        try:
            # Postaw VM na node
            ha_config = {
                "state": "started",  # Auto-start na innym nodzie
                "group": self.group,  # Grupa HA (default)
                "comment": f"HA enabled for LinuxEdu VM {vm_id}",
                "max_relocate": 1,  # Maksymalnie przenieś 1x
                "max_restart": 3,  # Maksymalnie restartuj 3x
            }
            
            # API Proxmoxa: PUT /cluster/ha/resources/{sid}
            # Format: {type}:{vmid} np. vm:123
            resource_id = f"vm:{vm_id}"
            
            response = self.proxmox.cluster.ha.resources(resource_id).put(**ha_config)
            
            logger.info(f"✅ HA enabled for VM {vm_id} on node {node}: {response}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to enable HA for VM {vm_id}: {e}")
            # HA jest optional, nie powoduje błędu
            return False
    
    async def disable_ha_for_vm(self, vm_id: int) -> bool:
        """Wyłącz HA dla VM"""
        if not self.enabled:
            return False
        
        try:
            resource_id = f"vm:{vm_id}"
            self.proxmox.cluster.ha.resources(resource_id).delete()
            logger.info(f"✅ HA disabled for VM {vm_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to disable HA for VM {vm_id}: {e}")
            return False
    
    async def check_ha_status(self, vm_id: int) -> dict:
        """Sprawdź status HA dla VM"""
        try:
            resource_id = f"vm:{vm_id}"
            status = self.proxmox.cluster.ha.resources(resource_id).status.get()
            return {
                "vm_id": vm_id,
                "ha_enabled": True,
                "status": status.get('data', {})
            }
        except Exception as e:
            logger.debug(f"Could not get HA status for VM {vm_id}: {e}")
            return {
                "vm_id": vm_id,
                "ha_enabled": False,
                "status": None
            }
    
    async def get_ha_config_for_vm(self, vm_id: int) -> dict:
        """Pobierz konfigurację HA dla VM"""
        try:
            resource_id = f"vm:{vm_id}"
            config = self.proxmox.cluster.ha.resources(resource_id).get()
            return config.get('data', {})
        except Exception as e:
            logger.debug(f"No HA config for VM {vm_id}: {e}")
            return {}


# Singleton instance
ha_service = None


def init_ha_service(proxmox: ProxmoxAPI):
    """Inicjuj HA serwis"""
    global ha_service
    ha_service = HAService(proxmox)
    logger.info("✅ HA service initialized")


def get_ha_service() -> HAService:
    """Pobierz HA serwis"""
    global ha_service
    if ha_service is None:
        raise RuntimeError("HA service not initialized")
    return ha_service