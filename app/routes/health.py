from fastapi import APIRouter

router = APIRouter(tags=["health"])

@router.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "service": "LinuxEdu Backend"}
