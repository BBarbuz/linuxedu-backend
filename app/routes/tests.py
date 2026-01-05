"""
Test Routes - REFACTORED
Endpointy API do zarządzania testami i ich uruchomiania

NOWE ENDPOINTY:
- POST /api/tests/{test_id}/run - Uruchamia test validation na VM użytkownika
- GET /api/tests/{test_id}/results - Pobiera wyniki testu
- GET /api/tests/results/latest - Pobiera ostatnie wyniki wszystkich testów
"""

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.test import Test, TestTask, TestResult
from app.utils.auth import get_current_user
from app.schemas.requests import TestResponse, TestTaskResponse
from app.services.test_service import TestService
from app.services.vm_services import AnsibleService
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tests", tags=["tests"])

# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================

def get_ansible_service() -> AnsibleService:
    # settings jest modułem/globalem, NIE dependency
    return AnsibleService(settings)

def get_test_service(
    ansible_service: AnsibleService = Depends(get_ansible_service),
) -> TestService:
    return TestService(ansible_service=ansible_service)


# ============================================================================
# TEST LISTING & DETAILS
# ============================================================================

@router.get("", response_model=List[TestResponse])
async def list_tests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all available tests.
    
    Returns tests ordered by name.
    """
    try:
        result = await db.execute(select(Test).order_by(Test.name))
        tests = result.scalars().all()
        return [TestResponse.model_validate(t) for t in tests]
    except Exception as e:
        logger.error(f"[LIST_TESTS] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list tests"
        )


@router.get("/{test_id}", response_model=TestResponse)
async def get_test(
    test_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get specific test details.
    """
    try:
        result = await db.execute(select(Test).where(Test.id == test_id))
        test = result.scalar_one_or_none()
        if not test:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Test {test_id} not found"
            )
        return TestResponse.model_validate(test)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GET_TEST] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get test"
        )


@router.get("/{test_id}/tasks", response_model=List[TestTaskResponse])
async def get_test_tasks(
    test_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all tasks for specific test.
    
    Returns tasks ordered by task_number.
    """
    try:
        # Verify test exists
        test_result = await db.execute(select(Test).where(Test.id == test_id))
        if not test_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Test {test_id} not found"
            )
        
        # Get tasks
        result = await db.execute(
            select(TestTask)
            .where(TestTask.test_id == test_id)
            .order_by(TestTask.task_number)
        )
        tasks = result.scalars().all()
        return [TestTaskResponse.model_validate(t) for t in tasks]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GET_TEST_TASKS] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get test tasks"
        )


# ============================================================================
# TEST EXECUTION - RUN VERIFICATION
# ============================================================================

@router.post("/{test_id}/run")
async def run_test_verification(
    test_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    test_service: TestService = Depends(get_test_service),
):
    """
    Run test verification on user's VM.
    
    **Pipeline:**
    1. Verify test exists
    2. Get user's active RUNNING VM
    3. Execute Ansible verify-test-{id}.yml playbook
    4. Parse JSON output from playbook
    5. Save results to database
    
    **Response:** Returns 202 ACCEPTED (operation in progress)
    
    **Playbook output format (required):**
    ```json
    {
        "passed_tasks": 5,
        "total_tasks": 7,
        "failed_tasks": 2,
        "details": {
            "task_1": {"status": "passed", "message": "..."},
            "task_2": {"status": "failed", "message": "..."}
        }
    }
    ```
    """
    try:
        logger.info(
            f"[RUN_TEST] User {current_user.username} (ID:{current_user.id}) "
            f"requesting test {test_id} execution"
        )
        
        # 1. Verify test exists
        result = await db.execute(select(Test).where(Test.id == test_id))
        test = result.scalar_one_or_none()
        if not test:
            logger.warning(f"[RUN_TEST] Test {test_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Test {test_id} not found"
            )
        
        # 2. Execute test validation
        test_result = await test_service.run_test_validation(
            db=db,
            user_id=current_user.id,
            test_id=test_id
        )
        
        if test_result is None:
            logger.error(f"[RUN_TEST] Execution failed for test {test_id}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Test execution failed. Check if VM is running."
            )
        
        # 3. Return result
        logger.info(
            f"[RUN_TEST] ✅ Test {test_id} executed successfully. "
            f"Result ID: {test_result.id}, Status: {test_result.status}"
        )
        
        return {
            "id": test_result.id,
            "test_id": test_result.test_id,
            "user_id": test_result.user_id,
            "status": test_result.status,
            "score": test_result.score,
            "completed_at": test_result.completed_at,
            "result_json": test_result.result_json
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[RUN_TEST] ❌ Unexpected error: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during test execution"
        )


# ============================================================================
# TEST RESULTS
# ============================================================================

@router.get("/{test_id}/results", response_model=List[dict])
async def get_test_results(
    test_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all test results for current user on specific test.
    
    Returns results ordered by completed_at (newest first).
    """
    try:
        result = await db.execute(
            select(TestResult)
            .where(
                (TestResult.user_id == current_user.id) &
                (TestResult.test_id == test_id)
            )
            .order_by(TestResult.completed_at.desc())
        )
        results = result.scalars().all()
        
        return [
            {
                "id": r.id,
                "test_id": r.test_id,
                "status": r.status,
                "score": r.score,
                "started_at": r.started_at,
                "completed_at": r.completed_at,
                "result_json": r.result_json
            }
            for r in results
        ]
    except Exception as e:
        logger.error(f"[GET_RESULTS] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve test results"
        )


@router.get("/results/latest", response_model=dict)
async def get_latest_test_results(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get latest test result for each test type for current user.
    
    Returns summary statistics and latest result for each test.
    """
    try:
        # Get all unique tests
        result = await db.execute(select(Test))
        all_tests = result.scalars().all()
        
        test_results = {}
        for test in all_tests:
            result = await db.execute(
                select(TestResult)
                .where(
                    (TestResult.user_id == current_user.id) &
                    (TestResult.test_id == test.id)
                )
                .order_by(TestResult.completed_at.desc())
                .limit(1)
            )
            latest = result.scalar_one_or_none()
            
            if latest:
                test_results[f"test_{test.id}"] = {
                    "test_name": test.name,
                    "status": latest.status,
                    "score": latest.score,
                    "completed_at": latest.completed_at
                }
        
        return {
            "user_id": current_user.id,
            "username": current_user.username,
            "results": test_results
        }
    except Exception as e:
        logger.error(f"[GET_LATEST_RESULTS] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve latest results"
        )


@router.get("/result/{result_id}", response_model=dict)
async def get_result_details(
    result_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed test result by result ID.
    
    Returns full result_json with task details.
    """
    try:
        result = await db.execute(
            select(TestResult)
            .where(
                (TestResult.id == result_id) &
                (TestResult.user_id == current_user.id)
            )
        )
        test_result = result.scalar_one_or_none()
        
        if not test_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Result {result_id} not found"
            )
        
        return {
            "id": test_result.id,
            "test_id": test_result.test_id,
            "user_id": test_result.user_id,
            "status": test_result.status,
            "score": test_result.score,
            "started_at": test_result.started_at,
            "completed_at": test_result.completed_at,
            "result_json": test_result.result_json
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GET_RESULT_DETAILS] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve result details"
        )