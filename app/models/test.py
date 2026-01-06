from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from enum import Enum
from app.database import Base
from datetime import datetime, timedelta

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    DateTime,
)

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

class TestTask(Base):
    __tablename__ = "test_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey("tests.id"), nullable=False)
    task_number = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    checklist = Column(JSON, nullable=True)
    command_hint = Column(Text, nullable=True)

class TestResult(Base):
    __tablename__ = "test_results"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    test_id = Column(Integer, ForeignKey("tests.id", ondelete="CASCADE"), nullable=False)

    started_at = Column(DateTime, nullable=True, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    result_json = Column(JSONB, nullable=True)
    score = Column(String(50), nullable=True)
    status = Column(String(20), nullable=True, default="in_progress")

    test = relationship("Test", backref="results")
    user = relationship("User", backref="test_results")

class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"
    IN_PROGRESS = "in_progress"
