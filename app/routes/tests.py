import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User
from app.models.test import Test, TestTask, TestResult
from app.utils.auth import get_current_user
from app.schemas.requests import TestResponse, TestTaskResponse, TestResultAdminResponse
from app.services.test_service import TestService
from app.services.vm_services import AnsibleService
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tests", tags=["tests"])

# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================

def get_ansible_service() -> AnsibleService:
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


@router.get("/results/global", response_model=List[TestResultAdminResponse])
async def get_all_global_results(
    # BŁĄD BYŁ TUTAJ:
    # Zamiast: current_user: User = Depends(require_role("admin")),
    # Użyj:
    current_user: User = Depends(get_current_user), 
    db: AsyncSession = Depends(get_db)
):
    """
    Get all test results. Accessible by Admins AND Instructors.
    """
    
    # 1. Sprawdzenie uprawnień (TERAZ TO ZADZIAŁA)
    # Ponieważ użyliśmy get_current_user, kod wejdzie tutaj i sprawdzi warunek:
    if current_user.role not in ["admin", "instructor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Requires 'admin' or 'instructor' role."
        )

    # 2. Pobieranie danych (bez zmian)
    test_service = TestService()
    results = await test_service.get_all_results_for_admin(db)
    
    # 3. Mapowanie (bez zmian)
    response_data = []
    for res in results:
        current_score = 0
        max_score = 0
        
        if res.result_json and isinstance(res.result_json, dict):
            current_score = res.result_json.get('passed_tasks', 0)
            max_score = res.result_json.get('total_tasks', 0)
        elif res.score and '/' in str(res.score):
            try:
                parts = res.score.split('/')
                current_score = int(parts[0])
                if len(parts) > 1:
                    max_score = int(parts[1])
            except:
                pass

        is_passed = (res.status == "passed")

        response_data.append(TestResultAdminResponse(
            id=res.id,
            test_id=res.test_id,
            user_id=res.user_id,
            username=res.user.username if res.user else "Deleted User",
            email=res.user.email if res.user else "N/A",
            score=current_score,
            max_score=max_score,
            status=res.status or "unknown",
            passed=is_passed,
            completed_at=res.completed_at
        ))
        
    return response_data