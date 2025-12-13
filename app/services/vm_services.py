"""
Virtual Machine Services
========================
Logika biznesowa zarządzania VM.
Includes: Proxmox API, Ansible, Database operations.
"""

import asyncio
import logging
import subprocess
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.models.vm import VM, VMStatus, VMMetadata, AllocatedIP, IPStatus, VMIDSequence, SSHKey
from app.models.user import User
from app.config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# PROXMOX SERVICE
# ============================================================================

class ProxmoxService:
    """
    Abstrakcja komunikacji z Proxmox REST API.
    """

    def __init__(self, settings):
        self.base_url = f"https://{settings.PROXMOX_HOST}:{settings.PROXMOX_PORT}/api2/json"
        self.host = settings.PROXMOX_HOST
        self.token = settings.PROXMOX_TOKEN
        self.user = settings.PROXMOX_USER
        self.node = settings.PROXMOX_NODE
        self.verify_ssl = settings.PROXMOX_VERIFY_SSL
        self.storage = settings.VM_STORAGE
        self.ceph_pool = settings.CEPH_POOL

    async def _proxmox_request(self, method: str, path: str, data: dict = None, retry_count: int = 3) -> dict:
        """
        Wykonaj żądanie do Proxmox API z retry logic.

        Args:
            method: GET, POST, DELETE, PUT
            path: ścieżka API (bez base_url)
            data: payload JSON (dla POST, PUT)
            retry_count: liczba prób

        Returns:
            Response JSON

        Raises:
            HTTPException na powtarzalny błąd
        """
        try:
            import requests
        except ImportError:
            raise ImportError("requests library required. pip install requests")

        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"PVEAPIToken={self.user}!{self.token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        for attempt in range(retry_count):
            try:
                if method == "GET":
                    response = requests.get(url, headers=headers, verify=self.verify_ssl, timeout=30)
                elif method == "POST":
                    response = requests.post(url, headers=headers, data=data, verify=self.verify_ssl, timeout=30)
                elif method == "DELETE":
                    response = requests.delete(url, headers=headers, verify=self.verify_ssl, timeout=30)
                elif method == "PUT":
                    response = requests.put(url, headers=headers, data=data, verify=self.verify_ssl, timeout=30)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                if response.status_code in [200, 201]:
                    return response.json().get("data", {})
                elif response.status_code >= 500 and attempt < retry_count - 1:
                    # Server error - retry
                    wait_time = 2 ** attempt
                    logger.warning(f"Proxmox API error (5xx), retrying in {wait_time}s: {response.text}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Proxmox API error ({response.status_code}): {response.text}")
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Proxmox error: {response.status_code}"
                    )
            except (asyncio.TimeoutError, Exception) as e:
                if attempt < retry_count - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Proxmox API request failed, retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Proxmox API request failed after {retry_count} attempts: {e}")
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Proxmox service unavailable"
                    )

    async def create_empty_vm(self, vmid: int, vm_name: str) -> bool:
        """Utwórz pustą VM (bez dysku)."""
        path = f"/nodes/{self.node}/qemu"
        data = {
            "vmid": vmid,
            "name": vm_name,
            "memory": 2048,
            "cores": 2,
            "sockets": 1,
            "net0": "virtio,bridge=vmbr0,mtu=1500"
        }
        result = await self._proxmox_request("POST", path, data)
        logger.info(f"✅ Empty VM created: {vmid}")
        return True

    async def import_disk_ceph(self, vmid: int, qcow2_path: str, ceph_pool: str) -> bool:
        """
        Importuj qcow2 do Ceph RBD.
        - qemu-img convert qcow2→raw na Ceph RBD
        - Wymaga SSH na Proxmox node
        """
        rbd_name = f"vm-{vmid}-disk-0"
        
        ssh_cmd = f"""
        set -e
        echo "Converting qcow2 to Ceph RBD: {rbd_name}"
        qemu-img convert -f qcow2 -O raw {qcow2_path} rbd:{ceph_pool}/{rbd_name}
        echo "✅ qcow2→RBD conversion complete"
        """

        try:
            # Wykonaj SSH do Proxmox node'a
            result = await self._ssh_execute(ssh_cmd)
            if not result:
                logger.error(f"❌ Import failed for VM {vmid}")
                return False

            # Przypisz RBD do VM via Proxmox API
            path = f"/nodes/{self.node}/qemu/{vmid}/config"
            data = {
                "scsi0": f"{ceph_pool}:{rbd_name}",
                "scsihw": "virtio-scsi-pci",
                "boot": "c",
                "bootdisk": "scsi0"
            }
            await self._proxmox_request("PUT", path, data)

            logger.info(f"✅ Disk imported for VM {vmid} on Ceph RBD")
            return True

        except Exception as e:
            logger.error(f"❌ Import disk failed: {e}")
            return False

    async def _ssh_execute(self, command: str, timeout_seconds: int = 180) -> bool:
        """Wykonaj komendę SSH na Proxmox node."""
        try:
            process = await asyncio.create_subprocess_shell(
                f"ssh -i /root/.ssh/id_rsa root@{self.host} '{command}'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds
            )

            if process.returncode != 0:
                logger.error(f"SSH error: {stderr.decode()}")
                return False

            logger.debug(f"SSH output: {stdout.decode()}")
            return True

        except asyncio.TimeoutError:
            logger.error(f"SSH command timeout after {timeout_seconds}s")
            return False
        except Exception as e:
            logger.error(f"SSH execution failed: {e}")
            return False

    async def configure_vm(self, vmid: int, ip_address: str, ssh_key: str, hostname: str) -> bool:
        """Configure VM: IP, SSH key, hostname via cloud-init."""
        path = f"/nodes/{self.node}/qemu/{vmid}/config"

        data = {
            "ipconfig0": f"ip={ip_address}/24,gw=192.168.100.1",
            "ciuser": "root",
            "nameserver": "8.8.8.8 8.8.4.4",
            "ide2": f"{settings.VM_CLOUDINIT_STORAGE}:cloudinit",
            "serial0": "socket",
            "vga": "serial0",
            "agent": "enabled=1"
        }

        await self._proxmox_request("PUT", path, data)
        logger.info(f"✅ VM {vmid} configured with IP {ip_address}")
        return True

    async def start_vm(self, vmid: int) -> bool:
        """Start VM."""
        path = f"/nodes/{self.node}/qemu/{vmid}/status/start"
        await self._proxmox_request("POST", path, {})
        logger.info(f"✅ VM started: {vmid}")
        return True

    async def shutdown_vm(self, vmid: int) -> bool:
        """Graceful shutdown VM."""
        path = f"/nodes/{self.node}/qemu/{vmid}/status/shutdown"
        await self._proxmox_request("POST", path, {})
        logger.info(f"✅ VM shutdown: {vmid}")
        return True

    async def reboot_vm(self, vmid: int) -> bool:
        """Reboot VM (graceful)."""
        path = f"/nodes/{self.node}/qemu/{vmid}/status/reboot"
        await self._proxmox_request("POST", path, {})
        logger.info(f"✅ VM rebooted: {vmid}")
        return True

    async def destroy_vm(self, vmid: int, purge: bool = True) -> bool:
        """Destroy VM (remove config + disks)."""
        path = f"/nodes/{self.node}/qemu/{vmid}"
        params = {"purge": 1} if purge else {}

        # First shutdown
        try:
            await self.shutdown_vm(vmid)
            await asyncio.sleep(10)  # Wait for shutdown
        except Exception as e:
            logger.warning(f"Shutdown failed (may be already off): {e}")

        # Then destroy
        await self._proxmox_request("DELETE", path, params)
        
        # Cleanup RBD volumes
        rbd_name = f"vm-{vmid}-disk-0"
        rbd_cmd = f"rbd -p {self.ceph_pool} rm {rbd_name}"
        await self._ssh_execute(rbd_cmd)
        
        logger.info(f"✅ VM destroyed: {vmid}")
        return True

    async def get_vm_status(self, vmid: int) -> str:
        """Get current VM status (running, stopped, etc)."""
        path = f"/nodes/{self.node}/qemu/{vmid}/status/current"
        result = await self._proxmox_request("GET", path)
        status_str = result.get("status", "unknown")
        logger.debug(f"VM {vmid} status: {status_str}")
        return status_str

    async def poll_vm_ready(self, vmid: int, max_attempts: int = 30, interval: int = 1) -> bool:
        """
        Poll VM do czasu aż będzie ready.

        Args:
            vmid: Proxmox VMID
            max_attempts: max liczba sprawdzeń
            interval: sekundy między sprawdzeniami

        Returns:
            True jeśli ready, False na timeout
        """
        for attempt in range(max_attempts):
            try:
                status = await self.get_vm_status(vmid)
                if status == "running":
                    logger.info(f"✅ VM {vmid} is ready after {attempt} attempts")
                    return True
            except Exception as e:
                logger.debug(f"Poll attempt {attempt + 1}: {e}")

            await asyncio.sleep(interval)

        logger.error(f"❌ VM {vmid} did not become ready after {max_attempts} attempts")
        return False

    async def get_vnc_url(self, vmid: int, expiry_seconds: int = 1800) -> str:
        """
        Get temporary VNC URL token.

        Returns:
            URL do noVNC konsoli
        """
        path = f"/nodes/{self.node}/qemu/{vmid}/vncproxy"
        result = await self._proxmox_request("POST", path, {})
        ticket = result.get("ticket", "")
        port = result.get("port", "6080")

        vnc_url = f"https://{settings.PROXMOX_HOST}:{port}/?path=?vncticket={ticket}&port=6080"
        logger.info(f"✅ VNC URL generated for VM {vmid}")
        return vnc_url


# ============================================================================
# ANSIBLE SERVICE
# ============================================================================

class AnsibleService:
    """
    Uruchamianie Ansible playbook'ów do provisioning i veryfikacji.
    """

    def __init__(self, settings):
        self.playbooks_dir = settings.ANSIBLE_PLAYBOOKS_DIR
        self.ssh_key = settings.ANSIBLE_SSH_KEY_PATH
        self.user = settings.ANSIBLE_USER

    async def run_setup_vm(self, ip_address: str, hostname: str) -> bool:
        """
        Uruchom setup-vm.yml playbook.
        - Setup SSH key
        - Install packages
        - Configure fail2ban
        """
        playbook = f"{self.playbooks_dir}/setup-vm.yml"
        cmd = [
            "ansible-playbook",
            playbook,
            f"-i {ip_address},",  # Inventory inline
            f"-u {self.user}",
            f"-e 'hostname={hostname}'",
            f"--private-key={self.ssh_key}"
        ]

        try:
            result = subprocess.run(
                " ".join(cmd),
                shell=True,
                capture_output=True,
                text=True,
                timeout=300  # 5 minut
            )

            if result.returncode == 0:
                logger.info(f"✅ Ansible setup-vm completed for {ip_address}")
                return True
            else:
                logger.error(f"❌ Ansible setup-vm failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"❌ Ansible setup-vm timeout for {ip_address}")
            return False
        except Exception as e:
            logger.error(f"❌ Ansible setup-vm error: {e}")
            return False

    async def run_verify_test(self, test_id: int, ip_address: str) -> Optional[Dict]:
        """
        Uruchom verify-test-{id}.yml playbook.
        Zwraca JSON z wynikami.
        """
        playbook = f"{self.playbooks_dir}/verify-test-{test_id}.yml"
        cmd = [
            "ansible-playbook",
            playbook,
            f"-i {ip_address},",
            f"-u {self.user}",
            f"--private-key={self.ssh_key}",
            "-vv"
        ]

        try:
            result = subprocess.run(
                " ".join(cmd),
                shell=True,
                capture_output=True,
                text=True,
                timeout=600  # 10 minut
            )

            if result.returncode == 0:
                # Parse output JSON
                import json
                try:
                    # Output będzie w formacie JSON w stdout
                    output_json = json.loads(result.stdout)
                    logger.info(f"✅ Ansible verify-test-{test_id} completed")
                    return output_json
                except json.JSONDecodeError:
                    logger.error(f"❌ Could not parse Ansible JSON output")
                    return None
            else:
                logger.error(f"❌ Ansible verify-test-{test_id} failed: {result.stderr}")
                return None

        except subprocess.TimeoutExpired:
            logger.error(f"❌ Ansible verify-test-{test_id} timeout")
            return None
        except FileNotFoundError:
            logger.error(f"❌ Playbook not found: {playbook}")
            return None
        except Exception as e:
            logger.error(f"❌ Ansible error: {e}")
            return None


# ============================================================================
# VM SERVICE
# ============================================================================

class VMService:
    """
    Logika biznesowa dla zarządzania VM.
    Orkiestruje Proxmox, Ansible i bazę danych.
    """

    def __init__(self, proxmox_service: ProxmoxService, ansible_service: AnsibleService):
        self.proxmox = proxmox_service
        self.ansible = ansible_service

    # ========================================================================
    # CREATE VM - MAIN PIPELINE
    # ========================================================================

    async def create_vm(self, db: AsyncSession, user_id: int) -> Optional[VM]:
        """
        Nowy pipeline z Ceph RBD:
        1. Walidacja
        2. Alokacja VMID + IP
        3. Rezerwacja (INSERT DB)
        4. create_empty_vm()
        5. import_disk_ceph() ← qemu-img convert qcow2→RBD
        6. configure_vm()
        7. start_vm()
        8. poll_vm_ready()
        9. Ansible provisioning
        10. Finalizacja
        """
        try:
            # 1. Walidacja
            result = await db.execute(
                select(VM).where(
                    (VM.user_id == user_id) &
                    (VM.vm_status != VMStatus.DELETED)
                )
            )
            if result.scalar_one_or_none():
                logger.warning(f"User {user_id} already has active VM")
                return None

            # 2. Alokacja VMID + IP (SELECT FOR UPDATE)
            vmid_result = await db.execute(
                select(VMIDSequence).with_for_update()
            )
            vmid_seq = vmid_result.scalar_one()
            new_vmid = vmid_seq.next_id
            vmid_seq.next_id += 1

            ip_result = await db.execute(
                select(AllocatedIP)
                .where(AllocatedIP.status == IPStatus.FREE)
                .with_for_update()
                .limit(1)
            )
            allocated_ip = ip_result.scalar_one()
            allocated_ip.status = IPStatus.ALLOCATED

            # 3. Rezerwacja
            vm = VM(
                user_id=user_id,
                proxmox_vm_id=new_vmid,
                vm_name=f"user-vm-{user_id}-{int(time.time())}",
                vm_status=VMStatus.CREATED,
                ip_address=str(allocated_ip.ip_address),
                created_at=datetime.utcnow()
            )
            db.add(vm)
            await db.commit()

            # 4. Create empty VM
            if not await self.proxmox.create_empty_vm(new_vmid, vm.vm_name):
                vm.vm_status = VMStatus.FAILED
                await db.commit()
                return None

            # 5. Import qcow2→Ceph RBD
            if not await self.proxmox.import_disk_ceph(
                new_vmid,
                settings.VM_QCOW2_PATH,
                settings.CEPH_POOL
            ):
                vm.vm_status = VMStatus.FAILED
                await db.commit()
                return None

            # 6. Configure VM
            if not await self.proxmox.configure_vm(
                new_vmid,
                str(allocated_ip.ip_address),
                "",  # SSH key from cloud-init
                vm.vm_name
            ):
                vm.vm_status = VMStatus.FAILED
                await db.commit()
                return None

            # 7. Start VM
            if not await self.proxmox.start_vm(new_vmid):
                vm.vm_status = VMStatus.FAILED
                await db.commit()
                return None

            # 8. Poll ready
            await self.proxmox.poll_vm_ready(new_vmid)

            # 9. Ansible provisioning
            vm.vm_status = VMStatus.PROVISIONING
            await db.commit()

            hostname = f"user-vm-{user_id}"
            if not await self.ansible.run_setup_vm(str(allocated_ip.ip_address), hostname):
                vm.vm_status = VMStatus.FAILED
                await db.commit()
                return None

            # 10. Finalizacja
            vm.vm_status = VMStatus.READY
            vm.runtime_expires_at = datetime.utcnow() + timedelta(
                seconds=settings.VM_DEFAULT_TIMEOUT_SECONDS
            )
            vm.last_active_at = datetime.utcnow()
            await db.commit()
            await db.refresh(vm)

            logger.info(f"✅ VM {new_vmid} created for user {user_id}")
            return vm

        except Exception as e:
            logger.error(f"❌ Error creating VM: {e}")
            return None

    # ========================================================================
    # OPERACJE NA VM
    # ========================================================================

    async def start_vm(self, vm_id: int, user_id: int, db: AsyncSession) -> VM:
        """Start VM + ustaw timer 12h."""
        vm = await self._get_user_vm(vm_id, user_id, db)

        if vm.vm_status == VMStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="VM is already running"
            )

        await self.proxmox.start_vm(vm.proxmox_vm_id)

        vm.vm_status = VMStatus.RUNNING
        vm.runtime_expires_at = datetime.utcnow() + timedelta(hours=12)
        vm.last_active_at = datetime.utcnow()

        await db.commit()
        await db.refresh(vm)

        logger.info(f"✅ VM started: {vm.proxmox_vm_id}")
        return vm

    async def stop_vm(self, vm_id: int, user_id: int, db: AsyncSession) -> VM:
        """Stop VM."""
        vm = await self._get_user_vm(vm_id, user_id, db)

        await self.proxmox.shutdown_vm(vm.proxmox_vm_id)

        vm.vm_status = VMStatus.STOPPED
        vm.runtime_expires_at = None
        vm.last_active_at = datetime.utcnow()

        await db.commit()
        await db.refresh(vm)

        logger.info(f"✅ VM stopped: {vm.proxmox_vm_id}")
        return vm

    async def reboot_vm(self, vm_id: int, user_id: int, db: AsyncSession) -> VM:
        """Reboot VM (nie resetuje timer)."""
        vm = await self._get_user_vm(vm_id, user_id, db)

        if vm.vm_status != VMStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="VM is not running"
            )

        await self.proxmox.reboot_vm(vm.proxmox_vm_id)
        vm.last_active_at = datetime.utcnow()

        await db.commit()

        logger.info(f"✅ VM rebooted: {vm.proxmox_vm_id}")
        return vm

    async def reset_vm(self, vm_id: int, user_id: int, db: AsyncSession) -> VM:
        """
        Reset VM do stanu czystego.
        - Nowy VMID
        - Stare IP
        - Ponowny import qcow2→Ceph RBD
        """
        old_vm = await self._get_user_vm(vm_id, user_id, db)
        old_vm_id = old_vm.proxmox_vm_id
        old_ip = old_vm.ip_address

        # Alokacja nowego VMID
        result = await db.execute(
            select(VMIDSequence).with_for_update()
        )
        seq = result.scalar_one()
        new_vm_id = seq.next_id
        seq.next_id += 1

        await db.commit()

        # Proxmox: create empty + import disk + destroy stary
        try:
            hostname = f"user-vm-{user_id}"
            vm_name = f"user-vm-{user_id}-{int(time.time())}"

            # Create empty
            await self.proxmox.create_empty_vm(new_vm_id, vm_name)

            # Import disk from qcow2
            if not await self.proxmox.import_disk_ceph(new_vm_id, settings.VM_QCOW2_PATH, settings.CEPH_POOL):
                raise RuntimeError("Disk import failed")

            # Configure
            await self.proxmox.configure_vm(new_vm_id, old_ip, "", hostname)

            # Destroy old
            await self.proxmox.destroy_vm(old_vm_id)

        except Exception as e:
            logger.error(f"❌ Reset failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Reset error: {str(e)}"
            )

        # Ansible provisioning
        try:
            success = await self.ansible.run_setup_vm(old_ip, hostname)
            if not success:
                raise RuntimeError("Ansible provisioning failed")
        except Exception as e:
            logger.error(f"❌ Reset ansible failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Provisioning error"
            )

        # Update DB
        old_vm.proxmox_vm_id = new_vm_id
        old_vm.vm_status = VMStatus.READY
        old_vm.runtime_expires_at = None
        old_vm.last_active_at = datetime.utcnow()

        await db.commit()
        await db.refresh(old_vm)

        logger.info(f"✅ VM reset: {old_vm_id} → {new_vm_id}")
        return old_vm

    async def delete_vm(self, vm_id: int, user_id: int, db: AsyncSession) -> VM:
        """
        Usuń VM i zwolnij zasoby.
        - Proxmox: destroy VM (+ RBD cleanup)
        - DB: mark as DELETED
        - IP: zwolnij
        """
        vm = await self._get_user_vm(vm_id, user_id, db)

        # Proxmox destroy (też czyści RBD)
        try:
            await self.proxmox.destroy_vm(vm.proxmox_vm_id)
        except Exception as e:
            logger.warning(f"⚠️  Proxmox destroy failed (may be OK): {e}")

        # Update status
        vm.vm_status = VMStatus.DELETED
        vm.runtime_expires_at = None

        # Zwolnij IP
        ip_result = await db.execute(
            select(AllocatedIP).where(AllocatedIP.ip_address == vm.ip_address)
        )
        ip_record = ip_result.scalar_one_or_none()
        if ip_record:
            ip_record.status = IPStatus.FREE

        await db.commit()

        logger.info(f"✅ VM deleted: {vm.proxmox_vm_id}")
        return vm

    async def extend_time(
        self,
        vm_id: int,
        user_id: int,
        extension_minutes: int,
        db: AsyncSession
    ) -> VM:
        """
        Przedłuż czas działania VM.
        - extension_minutes: 5-60
        - max total: 12h od teraz
        """
        if extension_minutes < 5 or extension_minutes > 60:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Extension must be between 5 and 60 minutes"
            )

        vm = await self._get_user_vm(vm_id, user_id, db)

        if vm.vm_status != VMStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="VM is not running"
            )

        # Max limit: 12 hours from now
        max_runtime = datetime.utcnow() + timedelta(hours=12)
        new_expiry = vm.runtime_expires_at + timedelta(minutes=extension_minutes)

        if new_expiry > max_runtime:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot extend beyond 12 hours limit"
            )

        vm.runtime_expires_at = new_expiry
        vm.last_active_at = datetime.utcnow()

        await db.commit()
        await db.refresh(vm)

        logger.info(f"✅ VM extended: {vm.proxmox_vm_id}, new expiry: {new_expiry}")
        return vm

    async def get_user_vm(self, vm_id: int, user_id: int, db: AsyncSession) -> VM:
        """Pobierz VM użytkownika."""
        return await self._get_user_vm(vm_id, user_id, db)

    async def list_user_vms(self, user_id: int, db: AsyncSession) -> List[VM]:
        """List wszystkie VM użytkownika."""
        result = await db.execute(
            select(VM)
            .where((VM.user_id == user_id) & (VM.vm_status != VMStatus.DELETED))
            .order_by(VM.created_at.desc())
        )
        return result.scalars().all()

    async def get_vnc_url(self, vm_id: int, user_id: int, db: AsyncSession) -> str:
        """Pobierz VNC URL dla VM."""
        vm = await self._get_user_vm(vm_id, user_id, db)

        if vm.vm_status != VMStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="VM is not running"
            )

        vnc_url = await self.proxmox.get_vnc_url(vm.proxmox_vm_id, expiry_seconds=1800)
        return vnc_url

    # ========================================================================
    # CLEANUP & MAINTENANCE
    # ========================================================================

    async def cleanup_inactive_vms(self, db: AsyncSession):
        """
        Auto-delete VM po 14 dniach nieaktywności.
        Uruchamiać co godzinę via APScheduler.
        """
        cutoff_date = datetime.utcnow() - timedelta(days=settings.VM_AUTO_DELETE_DAYS)

        result = await db.execute(
            select(VM).where(
                (VM.last_active_at < cutoff_date) &
                (VM.vm_status != VMStatus.DELETED)
            )
        )
        inactive_vms = result.scalars().all()

        for vm in inactive_vms:
            try:
                await self.delete_vm(vm.id, vm.user_id, db)
                logger.info(f"✅ Auto-deleted inactive VM: {vm.proxmox_vm_id}")
            except Exception as e:
                logger.error(f"❌ Failed to auto-delete VM {vm.proxmox_vm_id}: {e}")

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    async def _get_user_vm(self, vm_id: int, user_id: int, db: AsyncSession) -> VM:
        """
        Pobierz VM i sprawdź permissions.
        """
        result = await db.execute(
            select(VM).where(VM.id == vm_id)
        )
        vm = result.scalar_one_or_none()

        if not vm:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="VM not found"
            )

        if vm.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this VM"
            )

        return vm

        """
VM Service - Kluczowe fragmenty z integracją Ceph + HA + Monitoring

To jest fragment pokazujący kluczowe zmiany. Full file znajduje się w instrukcji.
"""

# ============================================================================
# FRAGMENT 1: Alokacja zasobów z Ceph health check
# ============================================================================

async def allocate_resources(db: AsyncSession, proxmox) -> tuple[int, str, str]:
    """Alokuj VMID, IP i node. Wybierz nod z load balancing."""
    from app.services.ceph_service import get_ceph_service
    from app.services.load_balancing_service import get_load_balancing_service
    
    ceph = get_ceph_service()
    lb = get_load_balancing_service()
    
    # 1. NOWE: Wybierz nod z najmniejszym obciążeniem
    selected_node = await lb.select_best_node()
    logger.info(f"Selected node for VM: {selected_node}")
    
    try:
        # 2. Sprawdzaj Ceph health na wybranym nodzie
        await ceph.check_ceph_health(selected_node)
        
        # 3. Sprawdzaj Ceph disk space
        if not await ceph.validate_disk_space_for_vm(
            settings.VM_DEFAULT_DISK_GB,
            selected_node
        ):
            raise HTTPException(
                status_code=507,
                detail="Brak miejsca na Ceph dla nowej VM"
            )
        
        # 4. Sprawdzaj czy nod jest здorow
        is_healthy = await lb.is_node_healthy(selected_node)
        if not is_healthy:
            logger.warning(
                f"Node {selected_node} above threshold, "
                f"but no better options available"
            )
        
        # 5. Alokuj VMID
        result = await db.execute(
            select(VMIDSequence)
            .with_for_update(nowait=True)
            .limit(1)
        )
        seq = result.scalar_one()
        new_vm_id = seq.next_vm_id
        seq.next_vm_id += 1
        seq.last_allocated_at = datetime.now()
        await db.commit()
        
        # 6. Alokuj IP
        ip_result = await db.execute(
            select(AllocatedIP)
            .where(AllocatedIP.status == 'free')
            .with_for_update(nowait=True)
            .limit(1)
        )
        ip_record = ip_result.scalar_one_or_none()
        
        if not ip_record:
            seq.next_vm_id -= 1
            await db.commit()
            raise HTTPException(
                status_code=507,
                detail="Brak dostępnych adresów IP"
            )
        
        ip_address = ip_record.ip_address
        ip_record.status = 'allocated'
        ip_record.user_id = None
        await db.commit()
        
        logger.info(f"✅ Resources allocated: VMID={new_vm_id}, IP={ip_address}, Node={selected_node}")
        return new_vm_id, ip_address, selected_node
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resource allocation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ============================================================================
# FRAGMENT 2: Tworzenie VM w Proxmoxie z Ceph dyskiem
# ============================================================================

async def create_vm_in_proxmox(
    proxmox,
    vm_id: int,
    vm_name: str,
    ip_address: str,
    node: str,
    ssh_public_key: str
) -> bool:
    """
    Stwórz VM w Proxmoxie z:
    - Głównym dyskiem na Ceph RBD
    - Cloud-init na local-lvm
    - HA włączonym
    """
    try:
        # Pobierz template path dla tego nodu
        template_path = settings.VM_QCOW2_PATHS.get(
            node,
            settings.VM_QCOW2_PATH
        )
        
        logger.info(
            f"Creating VM {vm_id} on {node} from {template_path}"
        )
        
        # Cloud-init config YAML
        cloud_init_data = f"""#cloud-config
hostname: {f'linuxedu-vm-{vm_id}'}
manage_etc_hosts: localhost
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: false
      addresses:
        - {ip_address}/24
      gateway4: 192.168.100.1
      nameservers:
        addresses: [8.8.8.8, 8.8.4.4]

users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh-authorized-keys:
      - {ssh_public_key}

package_update: true
packages:
  - curl
  - wget
  - net-tools
  - openssh-server

final_message: "System ready at $TIMESTAMP"
"""
        
        # Parametry tworzenia VM
        create_params = {
            "newid": vm_id,
            "name": vm_name,
            "ide2": f"{settings.VM_CLOUDINIT_STORAGE}:cloudinit",  # Cloud-init na local
            "cicustom": f"user=snippets/{vm_id}-user.yml",  # Custom cloud-init
            "ciuser": "ubuntu",
            "cipassword": "ignored",  # SSH key używany
            "cores": settings.VM_DEFAULT_CORES,
            "memory": settings.VM_DEFAULT_MEMORY_MB,
            "sockets": 1,
            "cpu": "host",
            "agent": 1,
        }
        
        # Disk config: Ceph RBD dla głównego dysku
        scsi_disk = (
            f"{settings.VM_STORAGE}:vm-{vm_id}-disk-0,"
            f"size={settings.VM_DEFAULT_DISK_GB}G,discard=on,ssd=1"
        )
        create_params["scsi0"] = scsi_disk
        create_params["scsi_controller"] = settings.VM_SCSI_CONTROLLER
        
        # Network
        create_params["net0"] = f"virtio,bridge=vmbr1,firewall=1"
        
        # Stwórz VM poprzez clone z template'u
        logger.info(f"Cloning template to VM {vm_id}...")
        
        clone_task = proxmox.nodes(node).qemu(100).clone.post(
            newid=vm_id,
            name=vm_name,
            full=1,  # Full clone (nie linked clone)
            storage=settings.VM_STORAGE,  # Docelowy storage: Ceph
            target=node,
        )
        
        # Czekaj na completion
        task_id = clone_task.get('data')
        await _wait_for_proxmox_task(proxmox, node, task_id, timeout=300)
        
        # Zaktualizuj konfigurację VM (nie da się w clone, trzeba po)
        logger.info(f"Updating VM {vm_id} configuration...")
        
        proxmox.nodes(node).qemu(vm_id).config.put(**{
            "cores": settings.VM_DEFAULT_CORES,
            "memory": settings.VM_DEFAULT_MEMORY_MB,
            "net0": "virtio,bridge=vmbr1,firewall=1",
            "ide2": f"{settings.VM_CLOUDINIT_STORAGE}:cloudinit",
        })
        
        # Startuj VM
        logger.info(f"Starting VM {vm_id}...")
        proxmox.nodes(node).qemu(vm_id).status.start.post()
        
        logger.info(f"✅ VM {vm_id} created and started successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to create VM {vm_id}: {e}")
        raise


# ============================================================================
# FRAGMENT 3: Włączenie HA dla VM
# ============================================================================

async def enable_ha_for_new_vm(vm_id: int, node: str):
    """Włącz HA dla nowo stworzonej VM"""
    try:
        from app.services.ha_service import get_ha_service
        
        ha = get_ha_service()
        success = await ha.enable_ha_for_vm(vm_id, node)
        
        if success:
            logger.info(f"✅ HA enabled for VM {vm_id}")
        else:
            logger.warning(f"⚠️  HA not enabled for VM {vm_id} (optional)")
        
        return success
    except Exception as e:
        logger.warning(f"Could not enable HA: {e}")
        return False


# ============================================================================
# FRAGMENT 4: Reset VM z obsługą migracji
# ============================================================================

async def reset_vm(
    user_id: int,
    vm_id: int,
    db: AsyncSession,
    proxmox
) -> VM:
    """
    Reset VM - tworzy nową VM z templatu, usuwa starą.
    Zachowuje IP i node jeśli możliwe.
    """
    try:
        # Pobierz starą VM
        result = await db.execute(
            select(VM).where(
                (VM.id == vm_id) &
                (VM.user_id == user_id)
            )
        )
        old_vm = result.scalar_one_or_none()
        
        if not old_vm:
            raise HTTPException(status_code=404, detail="VM not found")
        
        old_proxmox_id = old_vm.proxmox_vm_id
        old_ip = old_vm.ip_address
        old_node = old_vm.node
        
        logger.info(f"Resetting VM {old_proxmox_id} (keeping IP {old_ip})...")
        
        # Sprawdzaj czy jest Ceph space
        from app.services.ceph_service import get_ceph_service
        ceph = get_ceph_service()
        await ceph.check_ceph_health(old_node)
        
        # Alokuj nowy VMID (ale reuse IP!)
        result = await db.execute(
            select(VMIDSequence)
            .with_for_update(nowait=True)
        )
        seq = result.scalar_one()
        new_vm_id = seq.next_vm_id
        seq.next_vm_id += 1
        await db.commit()
        
        # Stwórz nową VM z nowym ID
        new_vm_name = f"user-vm-{user_id}-{int(datetime.now().timestamp())}-reset"
        
        await create_vm_in_proxmox(
            proxmox=proxmox,
            vm_id=new_vm_id,
            vm_name=new_vm_name,
            ip_address=old_ip,
            node=old_node,
            ssh_public_key=await get_default_ssh_key(db)
        )
        
        # Provisioning Ansible
        success = await provision_vm_with_ansible(
            new_vm_id,
            old_ip,
            proxmox
        )
        
        if not success:
            logger.error("Ansible provisioning failed during reset")
            # Cleanup nowej VM
            try:
                proxmox.nodes(old_node).qemu(new_vm_id).delete()
            except:
                pass
            raise HTTPException(
                status_code=500,
                detail="Failed to provision new VM"
            )
        
        # Update DB: zmień referencje na nową VM
        old_vm.proxmox_vm_id = new_vm_id
        old_vm.vm_status = VMStatus.RUNNING
        old_vm.runtime_expires_at = datetime.now() + timedelta(hours=12)
        old_vm.last_active_at = datetime.now()
        
        # Włącz HA dla nowej VM
        await enable_ha_for_new_vm(new_vm_id, old_node)
        
        await db.commit()
        await db.refresh(old_vm)
        
        # Usuń starą VM (async, nie blokuj)
        asyncio.create_task(
            _cleanup_old_vm_async(proxmox, old_node, old_proxmox_id)
        )
        
        logger.info(
            f"✅ VM reset complete: {old_proxmox_id} → {new_vm_id} "
            f"on {old_node}, IP: {old_ip}"
        )
        
        return old_vm
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reset VM failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Reset failed: {str(e)}"
        )


async def _cleanup_old_vm_async(proxmox, node: str, vm_id: int):
    """Asynchronicznie usuń starą VM"""
    try:
        await asyncio.sleep(10)  # Czekaj 10s żeby VM się dobrze bootowała
        
        logger.info(f"Cleaning up old VM {vm_id} on {node}...")
        proxmox.nodes(node).qemu(vm_id).delete()
        logger.info(f"✅ Old VM {vm_id} deleted")
    except Exception as e:
        logger.error(f"Failed to cleanup old VM {vm_id}: {e}")


async def _wait_for_proxmox_task(proxmox, node: str, task_id: str, timeout: int = 300):
    """Czekaj na completion Proxmox task'u"""
    import time
    start = time.time()
    
    while time.time() - start < timeout:
        try:
            task_status = proxmox.nodes(node).tasks(task_id).status.get()
            
            if task_status.get('status') == 'stopped':
                exitstatus = task_status.get('exitstatus', '')
                if exitstatus == 'OK':
                    logger.info(f"✅ Task {task_id} completed")
                    return True
                else:
                    raise Exception(f"Task failed: {exitstatus}")
            
            await asyncio.sleep(1)
        except Exception as e:
            if "not found" in str(e):
                # Task już ukończony
                return True
            raise
    
    raise TimeoutError(f"Task {task_id} timed out after {timeout}s")