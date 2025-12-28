"""
LinuxEdu Backend - Main Application Entry Point
With Load Balancing, Ceph Storage, and HA Support
"""
import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.routes import create_router
from app.routes.vms import create_router as create_vm_router
from app.services.load_balancing_service import init_load_balancing_service
from app.services.proxmox_client import get_proxmox_client
from app.services.ceph_service import init_ceph_service
from app.services.ha_service import init_ha_service
from app.services.vm_monitoring_service import init_vm_monitoring_service, get_vm_monitoring_service
from app.database import AsyncSessionLocal
from proxmoxer import ProxmoxAPI

logger = logging.getLogger(__name__)

app = FastAPI(
    title="LinuxEdu Backend",
    description="Educational Platform for Linux Administration"
)

# ===== CORS Configuration =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://192.168.0.129:3000",
        "https://localhost:3000",
        "http://localhost:3000",
        "http://192.168.0.129:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600,
)

# ===== Routes =====
app.include_router(create_router())
app.include_router(create_vm_router())

# ===== Health Check =====
@app.get("/")
async def root():
    return {"message": "LinuxEdu Backend ✅", "docs": "/docs"}

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "LinuxEdu"}

# ===== STARTUP EVENT =====
@app.on_event("startup")
async def startup_event():
    """Inicjuj wszystkie serwisy"""
    
    logger.info("🚀 Starting LinuxEdu Backend...")
    
    try:
        # ===== Init Proxmox API =====
        proxmox_token = settings.PROXMOX_TOKEN
        if not proxmox_token or proxmox_token == 'YOUR-TOKEN-NAME':
            logger.error("❌ CRITICAL: PROXMOX_TOKEN not configured in .env!")
            logger.error("   Please set PROXMOX_TOKEN=<token-id>:<token-uuid> in .env file")
            raise ValueError("PROXMOX_TOKEN not properly configured")

        if ':' in proxmox_token:
            token_id, token_value = proxmox_token.split(':', 1)
        else:
            token_id = 'default'
            token_value = proxmox_token
        
        proxmox = ProxmoxAPI(
            settings.PROXMOX_HOST,
            user=settings.PROXMOX_USER,
            token_name=settings.PROXMOX_TOKEN_ID,   # było "YOUR-TOKEN-NAME"
            token_value=settings.PROXMOX_TOKEN,     # secret z .env
            verify_ssl=settings.PROXMOX_VERIFY_SSL,
        )

        
        logger.info("✅ Proxmox API connected")
        
        # ===== Init Services =====
        init_ceph_service(proxmox)
        logger.info("✅ Ceph service initialized")
        
        init_ha_service(proxmox)
        logger.info("✅ HA service initialized")
        
        init_vm_monitoring_service(proxmox)
        logger.info("✅ VM monitoring service initialized")
        
        init_load_balancing_service(proxmox)
        logger.info("✅ Load balancing service initialized")
        
        # ===== Start Background Tasks =====
        asyncio.create_task(
            get_vm_monitoring_service().monitor_vm_migrations(
                AsyncSessionLocal(),
                proxmox
            )
        )
        logger.info("✅ VM monitoring started")
        
        asyncio.create_task(_periodic_cluster_health_check())
        logger.info("✅ Cluster health check started")
        
        logger.info("🎉 Backend startup complete!")
        
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}", exc_info=True)
        raise

# ===== PERIODIC CLUSTER HEALTH CHECK =====
async def _periodic_cluster_health_check():
    """Periodic check: log obciążenie cluster'a"""
    while True:
        try:
            await asyncio.sleep(120)  # Co 2 minuty
            
            lb = get_load_balancing_service()
            nodes_load = await lb.get_all_nodes_load()
            
            logger.info("📊 Cluster load status:")
            for node in nodes_load:
                logger.info(
                    f"  {node['node']}: "
                    f"CPU {node['cpu_percent']:.1f}%, "
                    f"RAM {node['memory_percent']:.1f}% - {node['status']}"
                )
        except Exception as e:
            logger.error(f"Cluster health check error: {e}")
            await asyncio.sleep(120)

# ===== SHUTDOWN EVENT =====
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup na zamknięciu"""
    logger.info("🛑 Shutting down backend...")