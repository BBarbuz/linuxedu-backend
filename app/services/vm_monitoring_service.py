"""
VM Monitoring Service - monitorowanie migracji i stanu VM
"""
import asyncio
import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from fastapi import HTTPException
from proxmoxer import ProxmoxAPI

from app.config import settings
from app.models import VM

logger = logging.getLogger(__name__)


class VMMonitoringService:
    """Monitoring pozycji VM - sprawdzanie na którym nodzie VM się znajduje"""
    
    def __init__(self, proxmox: ProxmoxAPI):
        self.proxmox = proxmox
        self.check_interval = settings.VM_NODE_CHECK_INTERVAL
        self.migration_alert_enabled = settings.VM_MIGRATION_ALERT_ENABLED
    
    async def get_vm_location(self, vm_id: int, node: str = None) -> dict:
        """
        Pobierz informacje o lokalizacji VM w Proxmoxie.
        
        Returns:
            {
                "vm_id": 123,
                "current_node": "pve2",
                "status": "running",
                "cpu_usage": 15.5,
                "memory_usage": 1024,
                "uptime": 3600
            }
        """
        try:
            # Jeśli znamy node, sprawdzaj tam najpierw
            if node:
                try:
                    result = self._check_vm_on_node(vm_id, node)
                    if result:
                        return result
                except:
                    pass
            
            # Szukaj VM na wszystkich nodach
            for check_node in settings.PROXMOX_NODES:
                try:
                    result = self._check_vm_on_node(vm_id, check_node)
                    if result:
                        return result
                except:
                    continue
            
            raise HTTPException(
                status_code=404,
                detail=f"VM {vm_id} nie znaleziona na żadnym nodzie"
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting VM location: {e}")
            raise HTTPException(
                status_code=503,
                detail=f"Nie można pobrać informacji o VM: {str(e)}"
            )
    
    def _check_vm_on_node(self, vm_id: int, node: str) -> dict:
        """
        Sprawdź czy VM istnieje na konkretnym nodzie i pobierz info.
        Zwraca None jeśli VM nie istnieje na tym nodzie.
        """
        try:
            vm_info = self.proxmox.nodes(node).qemu(vm_id).status.current.get()
            
            return {
                "vm_id": vm_id,
                "current_node": node,
                "status": vm_info.get('status'),
                "uptime": vm_info.get('uptime', 0),
                "cpu_usage": vm_info.get('cpu', 0),
                "memory_usage": vm_info.get('mem', 0),
                "memory_max": vm_info.get('maxmem', 0),
            }
        except Exception:
            # VM nie na tym nodzie
            return None
    
    async def monitor_vm_migrations(self, db: AsyncSession, proxmox: ProxmoxAPI):
        """
        Periodycznie sprawdzaj czy VM nie migratory na inny nod.
        
        Jeśli VM została zmigrowna, zaktualizuj BD i wyślij alert.
        Ta funkcja powinna być uruchomiana jako background task.
        """
        logger.info("🔍 Starting VM migration monitor...")
        
        while True:
            try:
                # Pobierz wszystkie aktywne VM
                result = await db.execute(
                    select(VM).where(
                        (VM.vm_status.in_(["running", "stopped"]))
                    )
                )
                vms = result.scalars().all()
                
                for vm in vms:
                    try:
                        # Sprawdź aktualną lokalizację
                        location = await self.get_vm_location(
                            vm.proxmox_vm_id,
                            node=vm.node  # Szukaj najpierw na znanych nodzie
                        )
                        
                        current_node = location.get('current_node')
                        
                        # Sprawdź czy VM się migratory
                        if current_node != vm.node:
                            old_node = vm.node
                            vm.node = current_node
                            
                            logger.warning(
                                f"🚀 VM {vm.proxmox_vm_id} MIGRATED: "
                                f"{old_node} → {current_node}"
                            )
                            
                            # Alert jeśli włączony
                            if self.migration_alert_enabled:
                                await self._send_migration_alert(
                                    vm.id, vm.user_id, old_node, current_node
                                )
                            
                            await db.commit()
                        
                    except Exception as e:
                        logger.debug(f"Error monitoring VM {vm.proxmox_vm_id}: {e}")
                        continue
                
                # Czekaj przed następną iteracją
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"VM monitoring error: {e}")
                await asyncio.sleep(self.check_interval)
    
    async def _send_migration_alert(
        self,
        vm_record_id: int,
        user_id: int,
        old_node: str,
        new_node: str
    ):
        """Wyślij alert o migracji VM"""
        logger.info(
            f"Alert: VM migrated - user={user_id}, "
            f"{old_node} → {new_node}"
        )
        # TODO: Implementuj wysłanie notyfikacji (email, websocket, itp)
        # np. send_user_notification(user_id, "VM foi migrada")
    
    async def get_node_status(self, node: str) -> dict:
        """Pobierz status noda"""
        try:
            node_status = self.proxmox.nodes(node).status.get()
            
            return {
                "node": node,
                "status": node_status.get('status'),
                "uptime": node_status.get('uptime', 0),
                "cpu_usage": node_status.get('cpu', 0),
                "memory_usage": node_status.get('memory', 0),
                "memory_max": node_status.get('maxmemory', 0),
            }
        except Exception as e:
            logger.error(f"Error getting node status: {e}")
            raise
    
    async def get_cluster_status(self) -> dict:
        """Pobierz status całego clustera"""
        try:
            nodes_status = []
            for node in settings.PROXMOX_NODES:
                try:
                    status = await self.get_node_status(node)
                    nodes_status.append(status)
                except:
                    nodes_status.append({
                        "node": node,
                        "status": "offline",
                        "memory_usage": 0,
                        "cpu_usage": 0
                    })
            
            return {
                "timestamp": datetime.now().isoformat(),
                "nodes": nodes_status,
                "healthy": all(n.get('status') == 'online' for n in nodes_status)
            }
        except Exception as e:
            logger.error(f"Error getting cluster status: {e}")
            raise


# Singleton
vm_monitoring_service = None


def init_vm_monitoring_service(proxmox: ProxmoxAPI):
    """Inicjuj monitoring serwis"""
    global vm_monitoring_service
    vm_monitoring_service = VMMonitoringService(proxmox)
    logger.info("✅ VM monitoring service initialized")


def get_vm_monitoring_service() -> VMMonitoringService:
    """Pobierz monitoring serwis"""
    global vm_monitoring_service
    if vm_monitoring_service is None:
        raise RuntimeError("VM monitoring service not initialized")
    return vm_monitoring_service