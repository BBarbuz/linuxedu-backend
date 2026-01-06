import logging
from typing import List, Dict, Any
from app.config import settings
from app.services.proxmox_client import get_proxmox_client

logger = logging.getLogger(__name__)

class LoadBalancingService:
    def __init__(self):
        self.proxmox = get_proxmox_client()
    
    def get_all_nodes_load(self) -> List[Dict[str, Any]]:
        try:
            nodes_statuses = self.proxmox.get_all_nodes_status()
            nodes_load: List[Dict[str, Any]] = []

            for status in nodes_statuses:
                node_name = status.get("node", "unknown")
                node_status = status.get("status", "unknown")

                try:
                    # CPU: 0–1
                    raw_cpu = status.get("cpu", 0) or 0
                    try:
                        cpu_fraction = float(raw_cpu)
                    except (TypeError, ValueError):
                        cpu_fraction = 0.0
                    cpu_percent = max(0.0, min(cpu_fraction * 100.0, 100.0))

                    # RAM
                    mem_info = status.get("memory") or {}
                    raw_total = mem_info.get("total", 0) or 0
                    raw_used = mem_info.get("used", 0) or 0

                    try:
                        memory_total = float(raw_total)
                    except (TypeError, ValueError):
                        memory_total = 0.0
                    try:
                        memory_used = float(raw_used)
                    except (TypeError, ValueError):
                        memory_used = 0.0

                    if memory_total > 0:
                        memory_percent = max(
                            0.0, min(memory_used / memory_total * 100.0, 100.0)
                        )
                    else:
                        memory_percent = 0.0

                    has_resources = memory_total > 0

                    # If nothing as 100%
                    if not has_resources:
                        cpu_percent = 100.0
                        memory_percent = 100.0

                    average_load = (cpu_percent + memory_percent) / 2.0

                    nodes_load.append(
                        {
                            "node": node_name,
                            "status": node_status,
                            "cpu_percent": cpu_percent,
                            "memory_percent": memory_percent,
                            "average_load": average_load,
                            "uptime": status.get("uptime", 0) or 0,
                        }
                    )

                    logger.info(
                        f"✅ Success processing node {node_name}: "
                        f"CPU={cpu_percent:.1f}%, RAM={memory_percent:.1f}% "
                        f"(status={node_status})"
                    )

                except Exception as e:
                    logger.error(f"❌ Error processing node {node_name}: {e}")
                    nodes_load.append(
                        {
                            "node": node_name,
                            "status": "error",
                            "cpu_percent": 100.0,
                            "memory_percent": 100.0,
                            "average_load": 100.0,
                            "uptime": 0,
                        }
                    )

            nodes_load.sort(key=lambda x: x["average_load"])
            return nodes_load

        except Exception as e:
            logger.error(f"❌ Error getting nodes load: {e}")
            return self._get_fallback_nodes()


    
    def _get_fallback_nodes(self) -> List[Dict[str, Any]]:
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

def get_load_balancing_service():
    global _load_balancing_service
    if _load_balancing_service is None:
        _load_balancing_service = LoadBalancingService()
    return _load_balancing_service