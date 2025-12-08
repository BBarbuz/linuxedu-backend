"""
LinuxEdu Backend - MINIMAL AUTH ONLY
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routes import create_router

app = FastAPI(title="LinuxEdu Backend (Auth Only)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(create_router())

@app.get("/")
async def root():
    return {"message": "LinuxEdu Backend - AUTH ONLY", "docs": "/docs"}

@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": "auth-only"}

