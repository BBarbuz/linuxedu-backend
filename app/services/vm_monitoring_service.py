"""
VM Monitoring Service - monitorowanie migracji i stanu VM
"""
import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from fastapi import HTTPException
from proxmoxer import ProxmoxAPI

from app.config import settings
from app.models import VM
from app.models.vm import VMStatus
from app.services.vm_services import ProxmoxService

logger = logging.getLogger(__name__)


class VMMonitoringService:
    """Monitoring pozycji VM - sprawdzanie na którym nodzie VM się znajduje"""
    
    def __init__(self, proxmox: ProxmoxAPI):
        self.proxmox = proxmox
        self.check_interval = settings.VM_NODE_CHECK_INTERVAL
        self.migration_alert_enabled = settings.VM_MIGRATION_ALERT_ENABLED
        self.proxmox_service = ProxmoxService(settings)

    
    async def get_vm_location(self, vm_id: int, node: str = None) -> dict:
        """Async wrapper na sync funkcję"""
        try:
            location = await asyncio.to_thread(
                self._check_vm_on_node_sync,
                vm_id,
                node
            )
            if location:
                return location
            
            # Szukaj na innych nodach
            for check_node in settings.PROXMOX_NODES:
                location = await asyncio.to_thread(
                    self._check_vm_on_node_sync,
                    vm_id,
                    check_node
                )
                if location:
                    return location
            
            raise HTTPException(status_code=404)
        except Exception as e:
            logger.error(f"Error getting VM location: {e}")
            raise

    
    async def monitor_vm_migrations(self, db: AsyncSession, proxmox: ProxmoxAPI):
        """Monitorowanie migracji VM"""
        logger.info("🔍 Starting VM migration monitor...")
        logger.info(f"📋 PROXMOX_NODES: {settings.PROXMOX_NODES}")

        
        while True:
            session_active = True
            try:
                # 1. POBIERZ VM
                result = await db.execute(
                    select(VM).where(
                        VM.vm_status.in_([
                            VMStatus.RUNNING, 
                            VMStatus.STOPPED, 
                            VMStatus.CREATED, 
                            VMStatus.READY
                        ])
                    )
                )
                vms = result.scalars().all()
                logger.debug(f"Checking {len(vms)} VMs for migration...")
                
                for vm in vms:
                    try:
                        # 2. TIMEOUT na pobieranie lokacji (30 sekund max)
                        try:
                            location = await asyncio.wait_for(
                                self.get_vm_location(vm.proxmox_vm_id),  # Szuka na WSZYSTKICH nodach!
                                timeout=10.0
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"Timeout checking VM {vm.proxmox_vm_id}")
                            continue
                        
                        if not location:
                            continue
                        
                        current_node = location.get('current_node')
                        
                        # 3. ZMIANA NOXA?
                        if current_node and current_node != vm.node:
                            old_node = vm.node
                            vm.node = current_node
                            
                            logger.warning(
                                f"🚀 VM {vm.proxmox_vm_id} MIGRATED: "
                                f"{old_node} → {current_node}"
                            )
                            
                            # Alert
                            if self.migration_alert_enabled:
                                await self._send_migration_alert(
                                    vm.id, vm.user_id, old_node, current_node
                                )
                            
                            await db.flush()  # ← FLUSH przed commit!
                            await db.commit()
                            logger.info(f"✅ VM {vm.proxmox_vm_id} migration recorded")

                        else:
                            # ✅ WSZYSTKO OK - log DEBUG (tylko jeśli DEBUG włączony)
                            logger.debug(f"✅ VM {vm.proxmox_vm_id} OK on {current_node}")
                        
                    except Exception as e:
                        logger.debug(f"Error checking VM {vm.proxmox_vm_id}: {e}")
                        await db.rollback()  # ← Rollback na błąd!
                        continue
                
                # 4. CZEKAJ
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"VM migration monitor error: {e}", exc_info=True)
                try:
                    await db.rollback()
                except:
                    pass
                await asyncio.sleep(self.check_interval)

    def _check_vm_on_node_sync(self, vm_id: int, node: str) -> dict:
        """
        SYNC wersja - będzie w threadzie, nie blokuje event loop
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
            return None


    async def monitor_vm_status_continuous(self, db: AsyncSession):
        """
        Co 5 sekund sprawdza RUNNING/STOPPED status VM z Proxmoxa
        i aktualizuje bazę danych
        """
        logger.info("Starting continuous VM status monitor (every 5 seconds)")
        
        while True:
            try:
                # 1. POBIERZ wszystkie VM z bazy (nie deleted)
                db.expire_all()
                result = await db.execute(
                    select(VM).where(
                        VM.vm_status.in_([VMStatus.RUNNING, VMStatus.STOPPED, VMStatus.CREATED, VMStatus.READY, VMStatus.CREATING])
                    )
                )
                vms = result.scalars().all()
                
                for vm in vms:
                    try:
                        # 2. SPRAWDZAJ status na Proxmoxie (z funkcji już istniejącej)
                        proxmox_status = await self.proxmox_service.get_vm_status(vm.proxmox_vm_id, node=vm.node)
                        is_locked = await self.proxmox_service.is_vm_locked(vm.proxmox_vm_id, node=vm.node)
                        # 3. PORÓWNAJ z bazą
                        if vm.vm_status.value != proxmox_status:
                            old_status = vm.vm_status.value
                            
                            # 4. UPDATE BAZA
                            if proxmox_status == "running":
                                vm.vm_status = VMStatus.RUNNING
                            elif proxmox_status == "stopped" and not is_locked:
                                vm.vm_status = VMStatus.STOPPED
                             
                            await db.commit()
                            
                            logger.warning(
                                f"VM {vm.proxmox_vm_id} status changed: "
                                f"{old_status} → {proxmox_status}"
                            )
                    
                    except Exception as e:
                        logger.debug(f"Error monitoring VM {vm.proxmox_vm_id}: {e}")
                        continue
                
                # 5. CZEKAJ 5 sekund
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Continuous VM status monitor error: {e}")
                await asyncio.sleep(5)

    async def monitor_vm_expiration(self, db: AsyncSession):
        """
        Co 60s sprawdza czy jakieś VM przekroczyły runtime_expires_at
        i automatycznie je wyłącza.
        
        Background task uruchamiany w main.py przy starcie.
        """
        logger.info("🕐 Starting VM expiration monitor (check every 60s)")
        
        while True:
            try:
                # Pobierz wszystkie RUNNING VM z expired timeout
                db.expire_all()  # Odśwież cache SQLAlchemy
                result = await db.execute(
                    select(VM).where(
                        VM.vm_status == VMStatus.RUNNING,
                        VM.runtime_expires_at.isnot(None),
                        VM.runtime_expires_at < datetime.utcnow()
                    )
                )
                expired_vms = result.scalars().all()
                
                if expired_vms:
                    logger.info(f"⏰ Found {len(expired_vms)} expired VMs to shutdown")
                
                for vm in expired_vms:
                    try:
                        time_overdue = datetime.utcnow() - vm.runtime_expires_at
                        logger.warning(
                            f"⏰ VM {vm.proxmox_vm_id} (user {vm.user_id}) expired "
                            f"{time_overdue.total_seconds():.0f}s ago, shutting down..."
                        )
                        
                        # Wyłącz VM w Proxmoxie (graceful shutdown)
                        ok = await self.proxmox_service.shutdown_vm(
                            vm.proxmox_vm_id, 
                            vm.node, 
                            max_wait=60
                        )
                        
                        if ok:
                            vm.vm_status = VMStatus.STOPPED
                            vm.runtime_expires_at = None
                            await db.commit()
                            await db.refresh(vm)
                            logger.info(f"✅ VM {vm.proxmox_vm_id} auto-shutdown completed")
                        else:
                            logger.error(f"❌ Failed to shutdown VM {vm.proxmox_vm_id}, will retry")
                    
                    except Exception as e:
                        logger.error(f"❌ Error auto-shutting VM {vm.proxmox_vm_id}: {e}")
                        await db.rollback()
                        continue
                
                # Czekaj 60 sekund przed następnym sprawdzeniem
                await asyncio.sleep(60)
            
            except Exception as e:
                logger.error(f"VM expiration monitor error: {e}", exc_info=True)
                await asyncio.sleep(60)
    
        async def monitor_vm_expiration(self, db: AsyncSession):
            """
            Co 60s sprawdza czy jakieś VM przekroczyły runtime_expires_at
            i automatycznie je wyłącza.
            """
            logger.info("🕐 Starting VM expiration monitor (check every 60s)")
            
            while True:
                try:
                    # Pobierz wszystkie RUNNING VM z expired timeout
                    db.expire_all()
                    result = await db.execute(
                        select(VM).where(
                            VM.vm_status == VMStatus.RUNNING,
                            VM.runtime_expires_at.isnot(None),
                            VM.runtime_expires_at < datetime.utcnow()
                        )
                    )
                    expired_vms = result.scalars().all()
                    
                    if expired_vms:
                        logger.info(f"⏰ Found {len(expired_vms)} expired VMs to shutdown")
                    
                    for vm in expired_vms:
                        try:
                            time_overdue = datetime.utcnow() - vm.runtime_expires_at
                            logger.warning(
                                f"⏰ VM {vm.proxmox_vm_id} (user {vm.user_id}) expired "
                                f"{time_overdue.total_seconds():.0f}s ago, shutting down..."
                            )
                            
                            # Wyłącz VM w Proxmoxie (graceful shutdown)
                            ok = await self.proxmox_service.shutdown_vm(
                                vm.proxmox_vm_id, 
                                vm.node, 
                                max_wait=60
                            )
                            
                            if ok:
                                vm.vm_status = VMStatus.STOPPED
                                vm.runtime_expires_at = None
                                await db.commit()
                                await db.refresh(vm)
                                logger.info(f"✅ VM {vm.proxmox_vm_id} auto-shutdown completed")
                            else:
                                logger.error(f"❌ Failed to shutdown VM {vm.proxmox_vm_id}, will retry")
                        
                        except Exception as e:
                            logger.error(f"❌ Error auto-shutting VM {vm.proxmox_vm_id}: {e}")
                            await db.rollback()
                            continue
                    
                    # Czekaj 60 sekund
                    await asyncio.sleep(60)
                
                except Exception as e:
                    logger.error(f"VM expiration monitor error: {e}", exc_info=True)
                    await asyncio.sleep(60)


    async def cleanup_inactive_vms(self, db: AsyncSession):
        """
        Co 24h usuwa VM nieaktywne przez 14+ dni.
        """
        logger.info(f"🧹 Starting VM cleanup monitor (check every 24h, delete after {settings.VM_AUTO_DELETE_DAYS} days)")
        
        while True:
            try:
                cutoff_date = datetime.utcnow() - timedelta(days=settings.VM_AUTO_DELETE_DAYS)
                #cutoff_date = datetime.utcnow() - timedelta(minutes=3)

                db.expire_all()
                result = await db.execute(
                    select(VM).where(
                        VM.last_active_at < cutoff_date,
                        VM.vm_status != VMStatus.DELETED
                    )
                )
                inactive_vms = result.scalars().all()
                
                if inactive_vms:
                    logger.info(f"🧹 Found {len(inactive_vms)} inactive VMs to delete")
                
                for vm in inactive_vms:
                    try:
                        logger.info(
                            f"🗑️ Auto-deleting VM {vm.proxmox_vm_id} "
                            f"(inactive since {vm.last_active_at})"
                        )
                        
                        # Shutdown if running
                        if vm.vm_status == VMStatus.RUNNING:
                            await self.proxmox_service.shutdown_vm(
                                vm.proxmox_vm_id, vm.node, max_wait=60
                            )
                        
                        # Destroy in Proxmoxie
                        await self.proxmox_service.destroy_vm(
                            vm.proxmox_vm_id, vm.node, purge=True
                        )
                        
                        # Mark as deleted
                        vm.vm_status = VMStatus.DELETED
                        await db.commit()
                        
                        logger.info(f"✅ VM {vm.proxmox_vm_id} auto-deleted")
                    
                    except Exception as e:
                        logger.error(f"❌ Failed to delete VM {vm.proxmox_vm_id}: {e}")
                        await db.rollback()
                        continue
                
                # Wait 24h
                await asyncio.sleep(86400)
                #await asyncio.sleep(120) 
            
            except Exception as e:
                logger.error(f"VM cleanup monitor error: {e}", exc_info=True)
                await asyncio.sleep(3600)


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
