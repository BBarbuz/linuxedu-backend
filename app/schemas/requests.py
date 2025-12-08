from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

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

class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = ""
    role: str
    is_active: bool

    class Config:
        from_attributes = True

class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str
    role: str = "user"

class CreateUserResponse(BaseModel):
    id: int
    username: str
    email: str
    initial_password: str
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
