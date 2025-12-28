import logging
from typing import List, Dict, Any
from app.config import settings
from app.services.proxmox_client import get_proxmox_client

logger = logging.getLogger(__name__)

class LoadBalancingService:
    """
    Prosty load balancing BEZ Redis (działa natychmiast).
    Rozszerzysz później o Redis.
    """
    
    def __init__(self):
        self.proxmox = get_proxmox_client()
    
    def get_all_nodes_load(self) -> List[Dict[str, Any]]:
        """
        Pobierz obciążenie wszystkich węzłów (bez cache).
        """
        try:
            nodes_statuses = self.proxmox.get_all_nodes_status()
            nodes_load = []
            
            for status in nodes_statuses:
                node_name = status["node"]
                
                try:
                    cpu_percent = (status.get("cpu", 0) * 100)
                    memory_total = status.get("maxmemory", 1)
                    memory_used = status.get("memory", 0)
                    memory_percent = (memory_used / memory_total * 100) if memory_total > 0 else 0
                    
                    if status.get("status") != "online":
                        cpu_percent = 100
                        memory_percent = 100
                    
                    nodes_load.append({
                        "node": node_name,
                        "status": status.get("status", "unknown"),
                        "cpu_percent": cpu_percent,
                        "memory_percent": memory_percent,
                        "average_load": (cpu_percent + memory_percent) / 2,
                        "uptime": status.get("uptime", 0),
                    })
                
                except Exception as e:
                    logger.error(f'❌ Error processing node {node_name}: {e}')
                    nodes_load.append({
                        "node": node_name,
                        "status": "error",
                        "cpu_percent": 100,
                        "memory_percent": 100,
                        "average_load": 100,
                        "uptime": 0,
                    })
            
            nodes_load.sort(key=lambda x: x["average_load"])
            logger.info(f'📊 Cluster load: {[(n["node"], f"{n["average_load"]:.1f}%") for n in nodes_load]}')
            return nodes_load
        
        except Exception as e:
            logger.error(f'❌ Error getting nodes load: {e}')
            return self._get_fallback_nodes()
    
    def _get_fallback_nodes(self) -> List[Dict[str, Any]]:
        """Fallback: domyślne węzły"""
        return [
            {
                "node": node,
                "status": "unknown",
                "cpu_percent": 50,
                "memory_percent": 50,
                "average_load": 50,
                "uptime": 0,
            }
            for node in settings.PROXMOX_NODES
        ]
    
    def get_best_node(self) -> str:
        """Zwróć najmniej obciążony węzeł"""
        nodes_load = self.get_all_nodes_load()
        
        if not nodes_load:
            logger.warning(f'⚠️ No nodes available, using PRIMARY: {settings.PROXMOX_PRIMARY_NODE}')
            return settings.PROXMOX_PRIMARY_NODE
        
        best_node = nodes_load[0]
        
        if (best_node["cpu_percent"] < settings.CPU_THRESHOLD_PERCENT and
            best_node["memory_percent"] < settings.MEMORY_THRESHOLD_PERCENT):
            logger.info(f'✅ Selected node: {best_node["node"]} (CPU: {best_node["cpu_percent"]:.1f}%, RAM: {best_node["memory_percent"]:.1f}%)')
            return best_node["node"]
        
        logger.warning(f'⚠️ All nodes overloaded! Using best: {best_node["node"]}')
        return best_node["node"]

# Singleton
_load_balancing_service = None

def init_load_balancing_service(proxmox=None):
    global _load_balancing_service
    _load_balancing_service = LoadBalancingService()
    logger.info("✅ Load balancing service initialized (no Redis)")

def get_load_balancing_service():
    global _load_balancing_service
    if _load_balancing_service is None:
        _load_balancing_service = LoadBalancingService()
    return _load_balancing_service