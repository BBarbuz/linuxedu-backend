from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum as SAEnum, text
from enum import Enum
from app.database import Base
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

class UserRole(str, Enum):
    admin = "admin"
    instructor = "instructor"
    student = "student"
    user = "user"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String, default="user")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # RELACJA - DODANE!
    vms = relationship("VM", back_populates="user")
