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
from app.services.proxmox_client import get_proxmox_client

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
        self.token_id = settings.PROXMOX_TOKEN_ID
        self.template_vmid = settings.PROXMOX_TEMPLATE_VMID
        self.client = get_proxmox_client().primary_client

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
            "Authorization": f"PVEAPIToken={self.user}!{self.token_id}={self.token}",
            "Content-Type": "application/x-www-form-urlencoded",
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
                    data = response.json().get("data", {})
                    return data
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

    async def _ssh_execute(self, command: str, timeout_seconds: int = 180) -> bool:
        """Wykonaj komendę SSH na Proxmox node."""
        try:
            process = await asyncio.create_subprocess_shell(
                f"ssh -i /root/.ssh/id_ed25519 root@{self.host} '{command}'",
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
            "ipconfig0": f"ip={ip_address}/24,gw=192.168.100.0",
            "ciuser": "root",
            "nameserver": "8.8.8.8 8.8.4.4",
            "agent": "enabled=1"
        }

        await self._proxmox_request("PUT", path, data)
        logger.info(f"✅ VM {vmid} configured with IP {ip_address}")
        return True

    async def start_vm(self, vmid: int, max_wait: int = 60) -> bool:
        """
        Start VM w Proxmoxie i poczekaj aż naprawdę będzie 'running'.
        max_wait – maksymalny czas w sekundach na dojście do running.
        """
        path = f"/nodes/{self.node}/qemu/{vmid}/status/start"

        # 1. Wyślij start – wynik zawiera UPID taska (lub pusty dict)
        result = await self._proxmox_request("POST", path, {})

        # UPID może być w data lub data["upid"] (zależnie od wersji)
        upid = None
        if isinstance(result, str):
            upid = result
        elif isinstance(result, dict):
            upid = result.get("upid") or result.get("data")

        if upid:
            logger.info(f"Start task UPID for VM {vmid}: {upid}")

        # 2. Sprawdzaj status VM aż będzie 'running' lub timeout
        for _ in range(max_wait):
            status = await self.get_vm_status(vmid)
            if status == "running":
                logger.info(f"VM {vmid} is running")
                return True
            await asyncio.sleep(1)

        logger.error(f"VM {vmid} did not reach 'running' state within {max_wait}s")
        return False

    async def shutdown_vm(self, vmid: int, max_wait: int = 60) -> bool:
        """
        Graceful shutdown VM i poczekaj aż status będzie 'stopped'.
        max_wait – maksymalny czas w sekundach na wyłączenie VM.
        """
        path = f"/nodes/{self.node}/qemu/{vmid}/status/shutdown"

        # 1. Wyślij żądanie shutdown – może zwrócić UPID
        result = await self._proxmox_request("POST", path, {})

        upid = None
        if isinstance(result, str):
            upid = result
        elif isinstance(result, dict):
            upid = result.get("upid") or result.get("data")

        if upid:
            logger.info(f"Shutdown task UPID for VM {vmid}: {upid}")

        # 2. Sprawdzaj status VM aż będzie 'stopped' albo timeout
        for _ in range(max_wait):
            status = await self.get_vm_status(vmid)
            if status == "stopped":
                logger.info(f"✅ VM {vmid} is stopped")
                return True
            await asyncio.sleep(1)

        logger.error(f"VM {vmid} did not reach 'stopped' state within {max_wait}s")
        return False

    async def reboot_vm(self, vmid: int, max_wait: int = 120) -> bool:
        """
        Graceful reboot VM i poczekaj aż wróci do 'running'.
        max_wait – maksymalny czas w sekundach na restart VM.
        """
        path = f"/nodes/{self.node}/qemu/{vmid}/status/reboot"

        # 1. Wyślij żądanie reboot – może zwrócić UPID
        result = await self._proxmox_request("POST", path, {})

        upid = None
        if isinstance(result, str):
            upid = result
        elif isinstance(result, dict):
            upid = result.get("upid") or result.get("data")

        if upid:
            logger.info(f"Reboot task UPID for VM {vmid}: {upid}")

        # 2. Sprawdzaj status VM: najpierw stopped, potem running
        for _ in range(max_wait):
            status = await self.get_vm_status(vmid)
            
            if status == "running":
                logger.info(f"✅ VM {vmid} rebooted and running")
                return True
            elif status == "stopped":
                logger.debug(f"VM {vmid} shutting down during reboot...")
            
            await asyncio.sleep(2)  # dłuższy interwał dla reboot

        logger.error(f"❌ VM {vmid} did not reboot successfully within {max_wait}s")
        return False


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
        
        logger.info(f"VM destroyed: {vmid}")
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
                    logger.info(f"VM {vmid} is ready after {attempt} attempts")
                    return True
            except Exception as e:
                logger.debug(f"Poll attempt {attempt + 1}: {e}")

            await asyncio.sleep(interval)

        logger.error(f"❌ VM {vmid} did not become ready after {max_attempts} attempts")
        return False

    async def get_vnc_url(self, vmid: int, expiry_seconds: int = 1800) -> str:
        """
        Get VNC URL w formacie Proxmox noVNC
        """
        try:
            vncurl = (
                f"https://{settings.PROXMOX_HOST}:8006/?"
                f"console=kvm&"
                f"novnc=1&"
                f"node={self.node}&"
                f"vmid={vmid}&"
                f"vmname=user-vm-{vmid}&"
                f"resize=off"
            )
            
            logger.info(f"VNC URL generated for VM {vmid}: {vncurl}")
            return vncurl
            
        except Exception as e:
            logger.error(f"Failed to get VNC URL for VM {vmid}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate VNC URL: {str(e)}",
            )

    async def clone_vm(
        self,
        template_vmid: int,
        new_vmid: int,
        name: str,
        target_node: str,
        pool: Optional[str],
        full: bool,
        storage: str,
        max_wait: int = 3600,   # max 60 min
    ) -> bool:
        """
        Klonuj VM z template_vmid do new_vmid i poczekaj na zakończenie taska.
        Zwraca True, jeśli Proxmox zakończył klon z exitstatus=OK.
        """
        params = {
            "newid": new_vmid,
            "name": name,
            "target": target_node,
            "full": int(full),
            "storage": storage,
        }
        if pool:
            params["pool"] = pool

        path = f"/nodes/{target_node}/qemu/{template_vmid}/clone"

        # 1. POST /clone – wynik powinien zawierać UPID taska
        result = await self._proxmox_request("POST", path, data=params)

        # UPID może być stringiem albo w polu "upid"/"data"
        upid = None
        if isinstance(result, str):
            upid = result
        elif isinstance(result, dict):
            upid = result.get("upid") or result.get("data")

        if not upid:
            logger.error("No UPID returned for clone task")
            return False

        logger.info(f"Clone task UPID for VM {new_vmid}: {upid}")

        # 2. Poll status: GET /nodes/{node}/tasks/{upid}/status
        for _ in range(max_wait):
            status = await self._proxmox_request(
                "GET",
                f"/nodes/{target_node}/tasks/{upid}/status",
            )

            task_status = status.get("status")
            exit_status = status.get("exitstatus")

            if task_status == "stopped":
                if exit_status == "OK":
                    logger.info(f"✅ Clone task finished OK: {upid}")
                    return True
                else:
                    logger.error(f"Clone failed: {exit_status}")
                    return False

            await asyncio.sleep(1)

        logger.error(f"Clone task timeout after {max_wait}s: {upid}")
        return False


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
        self.client = proxmox_service.client

    # ========================================================================
    # CREATE VM - MAIN PIPELINE
    # ========================================================================

    async def create_vm(self, db: AsyncSession, user_id: int) -> Optional[VM]:
        """
        Pipeline:
        1. Walidacja (brak aktywnej VM)
        2. Alokacja VMID + IP
        3. Rezerwacja w DB (CREATING)
        4. Klon z template (z potwierdzeniem)
        5. Ustawienie CREATED (VM istnieje w Proxmox)
        6. Konfiguracja cloud-init
        7. Start VM (z potwierdzeniem)
        8. Ansible provisioning
        9. Finalizacja (READY)
        """
        try:
            # 1. Walidacja – pomijamy DELETED i NULL
            result = await db.execute(
                select(VM).where(
                    (VM.user_id == user_id) &
                    (VM.vm_status.isnot(None)) &
                    (VM.vm_status != VMStatus.DELETED)
                )
            )
            if result.scalar_one_or_none():
                logger.warning(f"User {user_id} already has active VM")
                return None

            # 2. Alokacja VMID + IP
            vmid_result = await db.execute(
                select(VMIDSequence).with_for_update()
            )
            vmid_seq = vmid_result.scalar_one_or_none()
            new_vmid = vmid_seq.next_id
            vmid_seq.next_id += 1

            ip_result = await db.execute(
                select(AllocatedIP)
                .where(AllocatedIP.status == IPStatus.FREE)
                .with_for_update()
                .limit(1)
            )
            allocated_ip = ip_result.scalar_one_or_none()
            if not allocated_ip:
                logger.error("No free IPs")
                return None
            allocated_ip.status = IPStatus.ALLOCATED

            # 3. Rezerwacja w DB – VM jest w stanie CREATING (kopiowanie w toku)
            vm = VM(
                user_id=user_id,
                proxmox_vm_id=new_vmid,
                vm_name=f"user-vm-{user_id}-{int(time.time())}",
                vm_status=VMStatus.CREATING,
                ip_address=str(allocated_ip.ip_address),
                created_at=datetime.utcnow(),
                node=settings.PROXMOX_PRIMARY_NODE,
            )
            db.add(vm)
            await db.commit()
            await db.refresh(vm)

            # 4. Klon z szablonu + POTWIERDZENIE (UPID + polling)
            ok = await self.proxmox.clone_vm(
                template_vmid=settings.PROXMOX_TEMPLATE_VMID,
                new_vmid=new_vmid,
                name=vm.vm_name,
                target_node=vm.node,
                pool=None,
                full=True,
                storage=settings.CEPH_POOL,
            )
            if not ok:
                vm.vm_status = VMStatus.FAILED
                await db.commit()
                return None

            # 5. Po udanym klonie: VM jest utworzona w Proxmox → status CREATED
            vm.vm_status = VMStatus.CREATED
            await db.commit()
            await db.refresh(vm)

            # 6. Configure VM (cloud-init: IP, hostname, ssh key)
            ok = await self.proxmox.configure_vm(
                new_vmid,
                str(allocated_ip.ip_address),
                "",  # SSH key
                vm.vm_name
            )
            if not ok:
                vm.vm_status = VMStatus.FAILED
                await db.commit()
                return None

            # 7. Start VM (start_vm z potwierdzeniem running)
            ok = await self.proxmox.start_vm(new_vmid)
            if not ok:
                vm.vm_status = VMStatus.FAILED
                await db.commit()
                return None

            # 8. Finalizacja
            vm.vm_status = VMStatus.READY
            vm.runtime_expires_at = datetime.utcnow() + timedelta(
                seconds=settings.VM_DEFAULT_TIMEOUT_SECONDS
            )
            vm.last_active_at = datetime.utcnow()
            await db.commit()
            await db.refresh(vm)

            logger.info(
                f"✅ VM {new_vmid} created (clone from {settings.PROXMOX_TEMPLATE_VMID}) "
                f"for user {user_id}"
            )
            return vm

        except Exception as e:
            logger.error(f"❌ Error creating VM: {e}")
            return None


    # ========================================================================
    # OPERACJE NA VM
    # ========================================================================

    async def start_vm(self, vm_id: int, user_id: int, db: AsyncSession) -> VM:
        """Start VM + ustaw timer 12h, z potwierdzeniem że VM faktycznie ruszyła."""
        vm = await self._get_user_vm(vm_id, user_id, db)

        if vm.vm_status == VMStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="VM is already running"
            )

        # 1. Start w Proxmoxie + oczekiwanie na 'running'
        ok = await self.proxmox.start_vm(vm.proxmox_vm_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to start VM in Proxmox"
            )

        # 2. Aktualizacja BD – dopiero PO potwierdzeniu running
        vm.vm_status = VMStatus.RUNNING
        vm.runtime_expires_at = datetime.utcnow() + timedelta(hours=12)
        vm.last_active_at = datetime.utcnow()

        await db.commit()
        await db.refresh(vm)

        logger.info(f"✅ VM started: {vm.proxmox_vm_id}")
        return vm

    async def stop_vm(self, vm_id: int, user_id: int, db: AsyncSession) -> VM:
        """Stop VM z potwierdzeniem z Proxmoxa."""
        vm = await self._get_user_vm(vm_id, user_id, db)

        ok = await self.proxmox.shutdown_vm(vm.proxmox_vm_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to shutdown VM in Proxmox",
            )

        vm.vm_status = VMStatus.STOPPED
        vm.runtime_expires_at = None
        vm.last_active_at = datetime.utcnow()

        await db.commit()
        await db.refresh(vm)

        logger.info(f"✅ VM stopped: {vm.proxmox_vm_id}")
        return vm

    async def reboot_vm(self, vm_id: int, user_id: int, db: AsyncSession) -> VM:
        """Reboot VM (nie resetuje timer), z potwierdzeniem."""
        vm = await self._get_user_vm(vm_id, user_id, db)

        if vm.vm_status != VMStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="VM is not running"
            )

        # 1. Reboot w Proxmoxie + oczekiwanie na 'running'
        ok = await self.proxmox.reboot_vm(vm.proxmox_vm_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to reboot VM in Proxmox"
            )

        # 2. Aktualizacja DB – dopiero PO potwierdzeniu running
        vm.last_active_at = datetime.utcnow()

        await db.commit()
        await db.refresh(vm)

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
        seq = result.scalar_one_or_none()
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

    async def list_user_vms(self, db: AsyncSession, user_id: int) -> List[VM]:
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

    async def get_vm_stats(self, proxmox_vm_id: int, node: str) -> dict:
        """Pobierz live statystyki VM z Proxmoxa"""
        try:
            logger.debug(f"Fetching stats for VM {proxmox_vm_id} on node {node}")
            
            vmstatus = self.client.nodes(node).qemu(proxmox_vm_id).status.current.get()
            
            return {
                'cpu_usage_percent': float(vmstatus.get('cpu', 0)) * 100,
                'memory_usage_mb': float(vmstatus.get('mem', 0)) / (1024**2),
                'memory_total_mb': float(vmstatus.get('maxmem', 0)) / (1024**2),
                'disk_usage_gb': 0.0,
                'disk_total_gb': 0.0,
                'uptime_seconds': int(vmstatus.get('uptime', 0)),
                'network_in_bytes': int(vmstatus.get('netin', 0)),
                'network_out_bytes': int(vmstatus.get('netout', 0)),
            }
        except Exception as e:
            logger.error(f"Error getting stats for VM {proxmox_vm_id}: {e}")
            raise