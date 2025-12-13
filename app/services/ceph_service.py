"""
Ceph Storage Service - Health checks i operacje na storage
"""
import logging
from typing import Optional
from fastapi import HTTPException
from app.config import settings
from proxmoxer import ProxmoxAPI

logger = logging.getLogger(__name__)


class CephService:
    """Obsługa Ceph storage - health checks, monitoring"""
    
    def __init__(self, proxmox: ProxmoxAPI):
        self.proxmox = proxmox
        self.pool = settings.CEPH_POOL
        self.min_free_gb = settings.CEPH_MIN_FREE_GB
    
    async def check_ceph_health(self, node: str = "pve") -> bool:
        """
        Sprawdź status Ceph clustera.
        Zwraca True jeśli Ceph jest healthy i ma wolną przestrzeń.
        
        Raises:
            HTTPException(507) - Insufficient storage
            HTTPException(503) - Ceph unavailable
        """
        try:
            # Pobierz informacje o storage'u
            storage_info = await self._get_storage_info(node)
            
            # Sprawdź czy storage jest enabled
            if not storage_info.get('enabled', False):
                logger.error(f"Ceph storage {self.pool} nie jest enabled na nodzie {node}")
                raise HTTPException(
                    status_code=503,
                    detail=f"Ceph storage {self.pool} jest niedostępny"
                )
            
            # Sprawdź wolną przestrzeń
            available_gb = self._bytes_to_gb(storage_info.get('avail', 0))
            if available_gb < self.min_free_gb:
                logger.warning(
                    f"Mało miejsca na Ceph: {available_gb:.1f}GB, "
                    f"minimum: {self.min_free_gb}GB"
                )
                raise HTTPException(
                    status_code=507,
                    detail=f"Brak wystarczającej przestrzeni na Ceph. "
                           f"Dostępne: {available_gb:.1f}GB, "
                           f"wymagane: {self.min_free_gb}GB"
                )
            
            logger.info(f"✅ Ceph health check OK: {available_gb:.1f}GB wolne")
            return True
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Ceph health check failed: {e}")
            raise HTTPException(
                status_code=503,
                detail=f"Nie można sprawdzić statusu Ceph: {str(e)}"
            )
    
    async def _get_storage_info(self, node: str) -> dict:
        """Pobierz informacje o storage'u z Proxmoxa"""
        try:
            # Proxmox API: /nodes/{node}/storage/{storage}/status
            result = self.proxmox.nodes(node).storage(self.pool).status.get()
            return result.get('data', {})
        except Exception as e:
            logger.error(f"Failed to get storage info for {self.pool} on {node}: {e}")
            raise
    
    async def get_ceph_disk_usage(self, node: str = "pve") -> dict:
        """Zwróć informacje o użyciu dysku na Ceph"""
        try:
            info = await self._get_storage_info(node)
            
            total_gb = self._bytes_to_gb(info.get('maxvol', 0))
            used_gb = self._bytes_to_gb(info.get('used', 0))
            available_gb = self._bytes_to_gb(info.get('avail', 0))
            
            usage_percent = (used_gb / total_gb * 100) if total_gb > 0 else 0
            
            return {
                "pool": self.pool,
                "total_gb": round(total_gb, 2),
                "used_gb": round(used_gb, 2),
                "available_gb": round(available_gb, 2),
                "usage_percent": round(usage_percent, 2),
                "healthy": available_gb >= self.min_free_gb
            }
        except Exception as e:
            logger.error(f"Error getting disk usage: {e}")
            raise
    
    async def validate_disk_space_for_vm(self, disk_gb: int, node: str = "pve") -> bool:
        """
        Sprawdź czy jest wystarczająco miejsca na Ceph dla nowej VM.
        Bierze pod uwagę reserve dla innych operacji.
        """
        try:
            info = await self._get_storage_info(node)
            available_gb = self._bytes_to_gb(info.get('avail', 0))
            
            # Potrzebujemy: dysk VM + cloud-init + rezerwa 5GB
            required_gb = disk_gb + settings.VM_CLOUDINIT_DISK_GB + 5
            
            if available_gb < required_gb:
                logger.warning(
                    f"Brak miejsca: potrzeba {required_gb}GB, "
                    f"dostępne: {available_gb:.1f}GB"
                )
                return False
            
            return True
        except Exception as e:
            logger.error(f"Disk space validation failed: {e}")
            raise
    
    async def cleanup_orphaned_volumes(self, node: str = "pve"):
        """
        Usuń sierote volume'y (VM została usunięta, a dysk został)
        Ta operacja powinna być rarytasem - głównie dla emergency cleanup
        """
        try:
            logger.info(f"Cleaning orphaned volumes on {self.pool}...")
            # Implementacja: lista wszystkich volume'ów, sprawdzenie czy VM istnieje
            # TODO: Implementation
            pass
        except Exception as e:
            logger.error(f"Cleanup orphaned volumes failed: {e}")
            raise
    
    @staticmethod
    def _bytes_to_gb(bytes_val: int) -> float:
        """Konwertuj bajty na GB"""
        return bytes_val / (1024 ** 3)


# Singleton instance
ceph_service: Optional[CephService] = None


def init_ceph_service(proxmox: ProxmoxAPI):
    """Inicjuj Ceph serwis"""
    global ceph_service
    ceph_service = CephService(proxmox)
    logger.info("✅ Ceph service initialized")


def get_ceph_service() -> CephService:
    """Pobierz Ceph serwis"""
    if ceph_service is None:
        raise RuntimeError("Ceph service not initialized")
    return ceph_service