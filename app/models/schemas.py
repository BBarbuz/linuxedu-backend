"""
Pydantic request/response schemas for API validation
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

# ===== Authentication Schemas =====
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=255)
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

class RefreshRequest(BaseModel):
    refresh_token: str

# ===== User Schemas =====
class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str

# ===== VM Schemas =====
class VMResponse(BaseModel):
    id: int
    user_id: int
    vm_id: int
    vm_name: str
    vm_status: str
    created_at: datetime
    runtime_expires_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class ExtendTimeRequest(BaseModel):
    extension_minutes: int = Field(..., ge=5, le=60)

class VNCUrlResponse(BaseModel):
    vnc_url: str
    expires_in_minutes: int

# ===== Test Schemas =====
class TestTaskResponse(BaseModel):
    task_number: int
    title: str
    description: str
    checklist: Optional[List[str]]
    command_hint: Optional[str]

class TestResponse(BaseModel):
    id: int
    name: str
    description: str
    difficulty: str
    category: str
    
    class Config:
        from_attributes = True

class TestResultResponse(BaseModel):
    id: int
    test_id: int
    score: str
    status: str
    completed_at: Optional[datetime]
    result_json: Optional[Dict[str, Any]]
    
    class Config:
        from_attributes = True

# ===== Admin Schemas =====
class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=255)
    email: EmailStr
    role: str = "student"

class CreateUserResponse(BaseModel):
    id: int
    username: str
    email: str
    initial_password: str
    created_at: datetime
    
    class Config:
        from_attributes = True
