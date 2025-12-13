# app/routes/tests.py - POPRAWIONY
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from app.database import get_db
from app.models.user import User
from app.models.test import Test, TestTask  # Importowane modele
from app.utils.auth import get_current_user
from app.schemas.requests import TestResponse, TestTaskResponse  # Schematy

router = APIRouter(prefix="/api/tests", tags=["tests"])  # ← DODANY PREFIX!

@router.get("", response_model=List[TestResponse])
async def list_tests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all available tests"""
    result = await db.execute(select(Test).order_by(Test.name))
    tests = result.scalars().all()
    return [TestResponse.model_validate(t) for t in tests]

@router.get("/{test_id}", response_model=TestResponse)
async def get_test(
    test_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get specific test details"""
    result = await db.execute(select(Test).where(Test.id == test_id))
    test = result.scalar_one_or_none()
    if not test:
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")
    return TestResponse.model_validate(test)

@router.get("/{test_id}/tasks", response_model=List[TestTaskResponse])
async def get_test_tasks(
    test_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all tasks for specific test"""
    # Sprawdź czy test istnieje
    test_result = await db.execute(select(Test).where(Test.id == test_id))
    if not test_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")
    
    result = await db.execute(
        select(TestTask)
        .where(TestTask.test_id == test_id)
        .order_by(TestTask.task_number)
    )
    tasks = result.scalars().all()
    return [TestTaskResponse.model_validate(t) for t in tasks]
