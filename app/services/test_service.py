"""
Test execution service with Ansible integration - REFACTORED VERSION
Serwis do uruchamiania testów z integracją Ansible

GŁÓWNE ZMIANY:
1. Naprawiona metoda run_test_validation - teraz używa ansible_service
2. Dodana metoda run_verification_on_vm - uruchamia verify playbook na konkretnej VM
3. Właściwe parsowanie JSON z Ansible playbook'u
4. Zapisanie wyników do bazy (result_json, score, status)
"""

import logging
import json
import subprocess
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.future import select as sql_select

from app.models.test import Test, TestResult, TestStatus
from app.models.vm import VM
from app.config import settings
from sqlalchemy.orm import joinedload

logger = logging.getLogger(__name__)


class TestService:
    """
    Service obsługujący uruchamianie testów i weryfikację poprzez Ansible.
    """
    
    def __init__(self, ansible_service=None):
        """
        Initialize test service with optional ansible service dependency.
        
        Args:
            ansible_service: AnsibleService instance for playbook execution
        """
        self.ansible_service = ansible_service
    
    # ========================================================================
    # TEST RETRIEVAL
    # ========================================================================
    
    async def get_all_tests(self, db: AsyncSession) -> list[Test]:
        """Get all available tests"""
        result = await db.execute(select(Test))
        return result.scalars().all()
    
    async def get_test_by_id(self, db: AsyncSession, test_id: int) -> Optional[Test]:
        """Get specific test by ID"""
        result = await db.execute(select(Test).where(Test.id == test_id))
        return result.scalar_one_or_none()
    
    async def get_all_results_for_admin(self, db: AsyncSession):
        """
        Fetches all test results for all users from the database.
        Ordered by completion date (newest first).
        """
        # We join TestResult with User to access username/email in the response
        query = (
            select(TestResult)
            .options(joinedload(TestResult.user))  # Eager load user data
            .order_by(desc(TestResult.completed_at))
        )
        
        result = await db.execute(query)
        return result.scalars().all()
        
    # ========================================================================
    # TEST EXECUTION - REFACTORED
    # ========================================================================
    
    async def run_test_validation(
        self,
        db: AsyncSession,
        user_id: int,
        test_id: int,
        ansible_service=None
    ) -> Optional[TestResult]:
        """
        Run complete test validation pipeline.
        
        Pipeline:
        1. Get user's active VM (RUNNING status)
        2. Retrieve test details
        3. Execute Ansible verify-test-{id}.yml playbook on VM
        4. Parse JSON output
        5. Save results to test_results table
        
        Args:
            db: Database session
            user_id: User ID requesting test execution
            test_id: Test ID to execute
            ansible_service: Optional AnsibleService (injected for testing)
        
        Returns:
            TestResult object with execution results or None on failure
        """
        try:
            # 1. GET USER'S ACTIVE VM
            vm_result = await db.execute(
                select(VM)
                .where(
                    (VM.user_id == user_id) &
                    (VM.vm_status == "RUNNING")
                )
                .order_by(VM.created_at.desc())
                .limit(1)
            )
            user_vm = vm_result.scalar_one_or_none()
            
            if not user_vm:
                logger.error(
                    f"[TEST_RUN] No RUNNING VM found for user {user_id}. "
                    f"Test {test_id} execution aborted."
                )
                return None
            
            # 2. GET TEST DETAILS
            test = await self.get_test_by_id(db, test_id)
            if not test:
                logger.error(f"[TEST_RUN] Test {test_id} not found")
                return None
            
            logger.info(
                f"[TEST_RUN] Starting test {test_id} for user {user_id} "
                f"on VM {user_vm.proxmox_vm_id} ({user_vm.ip_address})"
            )
            
            # 3. EXECUTE ANSIBLE VERIFICATION
            verify_result = await self.run_verification_on_vm(
                test_id=test_id,
                vm=user_vm,
                ansible_service=ansible_service or self.ansible_service
            )
            
            if verify_result is None:
                logger.error(
                    f"[TEST_RUN] Ansible verification failed for test {test_id}"
                )
                return None
            
            # 4. PARSE RESULTS & CALCULATE SCORE
            passed_count = verify_result.get('passed_tasks', 0)
            total_count = verify_result.get('total_tasks', 1)
            success_rate = (passed_count / total_count * 100) if total_count > 0 else 0
            
            # Determine status based on pass rate
            if passed_count == total_count:
                status = TestStatus.PASSED
            elif passed_count == 0:
                status = TestStatus.FAILED
            else:
                status = TestStatus.PARTIAL
            
            # 5. CREATE & SAVE TEST RESULT
            test_result = TestResult(
                user_id=user_id,
                test_id=test_id,
                started_at=datetime.now(),
                completed_at=datetime.now(),
                result_json=verify_result,
                score=f"{passed_count}/{total_count}",
                status=status.value if hasattr(status, 'value') else str(status)
            )
            
            db.add(test_result)
            await db.commit()
            await db.refresh(test_result)
            
            logger.info(
                f"[TEST_RUN] ✅ Test {test_id} completed for user {user_id} "
                f"| Status: {status} | Score: {passed_count}/{total_count} ({success_rate:.1f}%)"
            )
            
            return test_result
            
        except Exception as e:
            logger.error(
                f"[TEST_RUN] ❌ Error during test validation: {str(e)}",
                exc_info=True
            )
            await db.rollback()
            return None
    
    async def run_verification_on_vm(
        self,
        test_id: int,
        vm: VM,
        ansible_service=None
    ) -> Optional[Dict]:
        """
        Execute verify-test-{id}.yml playbook on specific VM and parse results.
        
        Playbook should output JSON in format:
        {
            "passed_tasks": 5,
            "total_tasks": 7,
            "failed_tasks": 2,
            "details": {
                "task_name": {"status": "passed/failed", "message": "..."},
                ...
            }
        }
        
        Args:
            test_id: Test ID to verify
            vm: UserVM object with VM details
            ansible_service: AnsibleService instance
        
        Returns:
            Parsed JSON dict from playbook stdout or None on failure
        """
        if not ansible_service:
            logger.error("[VERIFY] No AnsibleService provided")
            return None
        
        if not vm.ip_address:
            logger.error(f"[VERIFY] VM {vm.proxmox_vm_id} has no IP address")
            return None
        
        try:
            logger.info(
                f"[VERIFY] Running verify-test-{test_id} on {vm.ip_address} "
                f"(VM {vm.proxmox_vm_id})"
            )
            
            # Use AnsibleService method
            result = await ansible_service.run_verify_test(
                test_id=test_id,
                ip_address=str(vm.ip_address)
            )
            
            if result is None:
                logger.error(
                    f"[VERIFY] ❌ Playbook execution returned None for test {test_id}"
                )
                return None
            
            # Validate result structure
            if not isinstance(result, dict):
                logger.error(
                    f"[VERIFY] ❌ Invalid result format (expected dict, got {type(result).__name__})"
                )
                return None
            
            # Ensure required fields
            if 'passed_tasks' not in result or 'total_tasks' not in result:
                logger.warning(
                    f"[VERIFY] ⚠️ Result missing required fields. "
                    f"Adding defaults: {result.keys()}"
                )
                result.setdefault('passed_tasks', 0)
                result.setdefault('total_tasks', 0)
                result.setdefault('failed_tasks', 0)
                result.setdefault('details', {})
            
            logger.info(
                f"[VERIFY] ✅ Verification complete: "
                f"{result['passed_tasks']}/{result['total_tasks']} passed"
            )
            
            return result
            
        except Exception as e:
            logger.error(
                f"[VERIFY] ❌ Error running verification: {str(e)}",
                exc_info=True
            )
            return None
    
    # ========================================================================
    # TEST RESULTS RETRIEVAL
    # ========================================================================
    
    async def get_test_result(
        self,
        db: AsyncSession,
        user_id: int,
        test_id: int
    ) -> Optional[TestResult]:
        """
        Get latest test result for specific user and test.
        
        Args:
            db: Database session
            user_id: User ID
            test_id: Test ID
        
        Returns:
            Latest TestResult or None if not found
        """
        result = await db.execute(
            select(TestResult)
            .where(
                (TestResult.user_id == user_id) &
                (TestResult.test_id == test_id)
            )
            .order_by(TestResult.completed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def get_user_test_results(
        self,
        db: AsyncSession,
        user_id: int,
        test_id: Optional[int] = None
    ) -> list[TestResult]:
        """
        Get all test results for user, optionally filtered by test_id.
        
        Args:
            db: Database session
            user_id: User ID
            test_id: Optional test ID filter
        
        Returns:
            List of TestResult objects
        """
        query = select(TestResult).where(TestResult.user_id == user_id)
        
        if test_id:
            query = query.where(TestResult.test_id == test_id)
        
        query = query.order_by(TestResult.completed_at.desc())
        
        result = await db.execute(query)
        return result.scalars().all()
    
    async def get_test_result_by_id(
        self,
        db: AsyncSession,
        result_id: int,
        user_id: int
    ) -> Optional[TestResult]:
        """
        Get specific test result by ID (with user ownership check).
        
        Args:
            db: Database session
            result_id: TestResult ID
            user_id: User ID (for ownership verification)
        
        Returns:
            TestResult or None
        """
        result = await db.execute(
            select(TestResult)
            .where(
                (TestResult.id == result_id) &
                (TestResult.user_id == user_id)
            )
        )
        return result.scalar_one_or_none()
    
    async def get_user_test_stats(
        self,
        db: AsyncSession,
        user_id: int
    ) -> Dict:
        """
        Get test execution statistics for user.
        
        Returns:
            {
                "total_tests_run": int,
                "passed": int,
                "partial": int,
                "failed": int,
                "in_progress": int,
                "average_score": float
            }
        """
        try:
            results = await self.get_user_test_results(db, user_id)
            
            stats = {
                "total_tests_run": len(results),
                "passed": sum(1 for r in results if r.status == TestStatus.PASSED.value),
                "partial": sum(1 for r in results if r.status == TestStatus.PARTIAL.value),
                "failed": sum(1 for r in results if r.status == TestStatus.FAILED.value),
                "in_progress": sum(1 for r in results if r.status == TestStatus.IN_PROGRESS.value),
                "average_score": 0.0
            }
            
            # Calculate average score
            total_passed = 0
            total_tasks = 0
            for r in results:
                if r.result_json and isinstance(r.result_json, dict):
                    total_passed += r.result_json.get('passed_tasks', 0)
                    total_tasks += r.result_json.get('total_tasks', 0)
            
            if total_tasks > 0:
                stats["average_score"] = (total_passed / total_tasks * 100)
            
            return stats
            
        except Exception as e:
            logger.error(f"[STATS] Error calculating test stats: {str(e)}")
            return {
                "total_tests_run": 0,
                "passed": 0,
                "partial": 0,
                "failed": 0,
                "in_progress": 0,
                "average_score": 0.0
            }