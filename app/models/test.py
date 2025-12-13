# app/models/test.py
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum
from app.database import Base

class TestDifficulty(str, Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"

class Test(Base):
    __tablename__ = "tests"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    difficulty = Column(SQLEnum(TestDifficulty), nullable=False)
    category = Column(String(50), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Relationships (później)
    # tasks = relationship("TestTask", back_populates="test")

class TestTask(Base):
    __tablename__ = "test_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey("tests.id"), nullable=False)
    task_number = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    checklist = Column(JSON, nullable=True)
    command_hint = Column(Text, nullable=True)
