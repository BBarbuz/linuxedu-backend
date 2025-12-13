"""
Load Balancing Service - wybór noda z najmniejszym obciążeniem
"""
import logging
from typing import Optional, List
from fastapi import HTTPException
from proxmoxer import ProxmoxAPI
from app.config import settings

logger = logging.getLogger(__name__)


class LoadBalancingService:
    """Wybór noda na podstawie obciążenia CPU i RAM"""
    
    def __init__(self, proxmox: ProxmoxAPI):
        self.proxmox = proxmox
        self.enabled = settings.LOAD_BALANCING_ENABLED
        self.cpu_threshold = settings.CPU_THRESHOLD_PERCENT
        self.memory_threshold = settings.MEMORY_THRESHOLD_PERCENT
    
    async def select_best_node(self) -> str:
        """
        Wybierz nod z najmniejszym obciążeniem.
        
        Returns: nazwa noda (np. "pve", "pve2")
        Raises: HTTPException(503) jeśli żaden nod nie spełnia kryteriów
        """
        if not self.enabled:
            logger.info("Load balancing disabled, using primary node")
            return settings.PROXMOX_PRIMARY_NODE
        
        try:
            nodes_stats = await self.get_all_nodes_load()
            
            if not nodes_stats:
                logger.warning("No nodes available, using primary node")
                return settings.PROXMOX_PRIMARY_NODE
            
            # Filtruj nody poniżej progu
            available_nodes = [
                n for n in nodes_stats
                if n['cpu_percent'] < self.cpu_threshold
                and n['memory_percent'] < self.memory_threshold
                and n['status'] == 'online'
            ]
            
            if not available_nodes:
                logger.warning(
                    f"All nodes above threshold "
                    f"(CPU: {self.cpu_threshold}%, MEM: {self.memory_threshold}%). "
                    f"Using least loaded node anyway."
                )
                # Wybierz najmniej obciążony nod nawet jeśli powyżej progu
                available_nodes = sorted(
                    [n for n in nodes_stats if n['status'] == 'online'],
                    key=lambda x: x['cpu_percent'] + x['memory_percent']
                )
            
            if not available_nodes:
                raise HTTPException(
                    status_code=503,
                    detail="No available nodes in cluster"
                )
            
            # Wybierz nod z najmniejszym obciążeniem
            best_node = available_nodes[0]
            
            logger.info(
                f"✅ Selected node: {best_node['node']} "
                f"(CPU: {best_node['cpu_percent']:.1f}%, "
                f"MEM: {best_node['memory_percent']:.1f}%)"
            )
            
            return best_node['node']
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Node selection failed: {e}")
            logger.warning(f"Falling back to primary node: {settings.PROXMOX_PRIMARY_NODE}")
            return settings.PROXMOX_PRIMARY_NODE
    
    async def get_all_nodes_load(self) -> List[dict]:
        """
        Pobierz obciążenie wszystkich nodów.
        
        Returns:
            [
                {
                    "node": "pve",
                    "status": "online",
                    "cpu_percent": 25.5,
                    "memory_percent": 45.2,
                    "uptime": 3600,
                    "cpu_usage": 2.5,  # cores used
                    "memory_usage": 8192  # MB used
                },
                ...
            ]
        """
        try:
            nodes_stats = []
            
            for node_name in settings.PROXMOX_NODES:
                try:
                    node_status = self.proxmox.nodes(node_name).status.get()
                    
                    # Wylicz procenty
                    cpu_percent = (node_status.get('cpu', 0) * 100)
                    memory_total = node_status.get('maxmemory', 1)
                    memory_used = node_status.get('memory', 0)
                    memory_percent = (memory_used / memory_total * 100) if memory_total > 0 else 0
                    
                    nodes_stats.append({
                        "node": node_name,
                        "status": node_status.get('status', 'unknown'),
                        "cpu_percent": cpu_percent,
                        "memory_percent": memory_percent,
                        "uptime": node_status.get('uptime', 0),
                        "cpu_usage": node_status.get('cpu', 0),
                        "memory_usage": memory_used,
                        "memory_max": memory_total,
                    })
                    
                except Exception as e:
                    logger.warning(f"Could not get status for node {node_name}: {e}")
                    nodes_stats.append({
                        "node": node_name,
                        "status": "offline",
                        "cpu_percent": 100,  # Traktuj offline nod jako pełny
                        "memory_percent": 100,
                        "uptime": 0,
                        "cpu_usage": 0,
                        "memory_usage": 0,
                        "memory_max": 0,
                    })
            
            return sorted(
                nodes_stats,
                key=lambda x: (x['cpu_percent'] + x['memory_percent']) / 2
            )
            
        except Exception as e:
            logger.error(f"Error getting nodes load: {e}")
            return []
    
    async def get_node_load(self, node: str) -> dict:
        """Pobierz obciążenie konkretnego noda"""
        try:
            node_status = self.proxmox.nodes(node).status.get()
            
            cpu_percent = (node_status.get('cpu', 0) * 100)
            memory_total = node_status.get('maxmemory', 1)
            memory_used = node_status.get('memory', 0)
            memory_percent = (memory_used / memory_total * 100) if memory_total > 0 else 0
            
            return {
                "node": node,
                "status": node_status.get('status', 'unknown'),
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "uptime": node_status.get('uptime', 0),
                "cpu_usage": node_status.get('cpu', 0),
                "memory_usage": memory_used,
                "memory_max": memory_total,
                "load": f"{cpu_percent:.1f}% CPU, {memory_percent:.1f}% RAM"
            }
        except Exception as e:
            logger.error(f"Error getting load for node {node}: {e}")
            raise
    
    async def count_vms_on_node(self, node: str) -> int:
        """Policz ile VM jest aktualnie na nodzie"""
        try:
            vm_list = self.proxmox.nodes(node).qemu.get()
            # Filtruj user VM (id >= 200)
            user_vms = [vm for vm in vm_list if vm.get('vmid', 0) >= 200]
            return len(user_vms)
        except Exception as e:
            logger.error(f"Error counting VMs on {node}: {e}")
            return 0
    
    async def is_node_healthy(self, node: str) -> bool:
        """Sprawdzenie czy nod jest здorow"""
        try:
            load = await self.get_node_load(node)
            
            # Nod jest здorow jeśli:
            # 1. Online
            # 2. Poniżej progów CPU i RAM
            is_healthy = (
                load['status'] == 'online' and
                load['cpu_percent'] < self.cpu_threshold and
                load['memory_percent'] < self.memory_threshold
            )
            
            return is_healthy
        except Exception as e:
            logger.error(f"Health check failed for {node}: {e}")
            return False


# Singleton
load_balancing_service = None


def init_load_balancing_service(proxmox: ProxmoxAPI):
    """Inicjuj load balancing serwis"""
    global load_balancing_service
    load_balancing_service = LoadBalancingService(proxmox)
    logger.info("✅ Load balancing service initialized")


def get_load_balancing_service() -> LoadBalancingService:
    """Pobierz load balancing serwis"""
    global load_balancing_service
    if load_balancing_service is None:
        raise RuntimeError("Load balancing service not initialized")
    return load_balancing_service