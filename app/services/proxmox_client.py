import logging
import time
from typing import Dict, Any, List
from proxmoxer import ProxmoxAPI
import urllib3
from app.config import settings

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

class ProxmoxClient:
    """
    Prosty Proxmox client BEZ nowych settings (działa natychmiast).
    """
    
    def __init__(self):
        self.primary_client = None
        self.node_clients = {}
        self._initialize_clients()
    
    def _initialize_clients(self):
        """Inicjalizuj połączenia do Proxmoxa"""
        try:
            # Główny client
            self.primary_client = self._create_client(settings.PROXMOX_HOST)
            logger.info(f"✅ Primary Proxmox client connected: {settings.PROXMOX_HOST}")
        except Exception as e:
            logger.error(f"❌ Failed to connect to primary Proxmox: {e}")
            raise
        
        # Per-node clients
        nodes = getattr(settings, 'PROXMOX_NODES', ['pve', 'pve2', 'pve3'])
        for i, node_name in enumerate(nodes):
            node_ip = f"192.168.0.{11 + i}"  # Domyślne IPs
            try:
                self.node_clients[node_name] = self._create_client(node_ip)
                logger.info(f"✅ Node client connected: {node_name} ({node_ip})")
            except Exception as e:
                logger.warning(f"⚠️ Failed to connect to {node_name}: {e}")
    
    def _create_client(self, host: str) -> ProxmoxAPI:
        """Stwórz Proxmox client"""
        verify_ssl = getattr(settings, 'PROXMOX_VERIFY_SSL', False)
        
        # Token parsing
        if ':' in settings.PROXMOX_TOKEN:
            token_id, token_value = settings.PROXMOX_TOKEN.split(':', 1)
        else:
            token_id = getattr(settings, 'PROXMOX_TOKEN_ID', 'default')
            token_value = settings.PROXMOX_TOKEN
        
        client = ProxmoxAPI(
            host=host,
            user=settings.PROXMOX_USER,
            token_name=token_id,
            token_value=token_value,
            verify_ssl=verify_ssl,
            timeout=30,  # Hardcoded timeout
        )
        
        # Test connection
        client.login()
        return client
    
    def get_node_status(self, node: str) -> Dict[str, Any]:
        """Pobierz status węzła"""
        client = self.node_clients.get(node) or self.primary_client
        try:
            return client.nodes(node).status.get()
        except Exception as e:
            logger.error(f"❌ Failed to get status for node {node}: {e}")
            raise
    
    def get_all_nodes_status(self) -> List[Dict[str, Any]]:
        """Pobierz status wszystkich węzłów"""
        nodes = getattr(settings, 'PROXMOX_NODES', ['pve', 'pve2', 'pve3'])
        statuses = []
        
        for node in nodes:
            try:
                status = self.get_node_status(node)
                statuses.append({
                    "node": node,
                    "status": status.get("status", "unknown"),
                    "cpu": status.get("cpu", 0),
                    "maxcpu": status.get("maxcpu", 0),
                    "memory": status.get("memory", 0),
                    "maxmemory": status.get("maxmemory", 0),
                    "uptime": status.get("uptime", 0),
                })
            except Exception as e:
                logger.error(f"❌ Could not get status for node {node}: {e}")
                statuses.append({
                    "node": node,
                    "status": "offline",
                    "cpu": 0,
                    "maxcpu": 0,
                    "memory": 0,
                    "maxmemory": 0,
                    "uptime": 0,
                })
        
        return statuses

# Singleton
_proxmox_client = None

def get_proxmox_client():
    global _proxmox_client
    if _proxmox_client is None:
        _proxmox_client = ProxmoxClient()
    return _proxmox_client