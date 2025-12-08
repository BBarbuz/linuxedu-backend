from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="student")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships - WAŻNE!
    vms = relationship("VM", back_populates="user", cascade="all, delete-orphan")
    #test_results = relationship("TestResult", back_populates="user", cascade="all, delete-orphan")
    #audit_logs = relationship("AuditLog", back_populates="user", cascade="all, delete-orphan")
