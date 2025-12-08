"""
Test execution service with Ansible integration
"""

import logging
import json
import subprocess
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.test import Test, TestResult, TestStatus
from app.models.vm import VM
from app.config import settings

logger = logging.getLogger(__name__)

class TestService:
    
    async def get_all_tests(self, db: AsyncSession) -> list[Test]:
        """Get all available tests"""
        result = await db.execute(select(Test))
        return result.scalars().all()
    
    async def get_test_by_id(self, db: AsyncSession, test_id: int) -> Test:
        """Get specific test"""
        result = await db.execute(select(Test).where(Test.id == test_id))
        return result.scalar_one_or_none()
    
    async def run_test_validation(self, db: AsyncSession, user_id: int, test_id: int) -> TestResult:
        """Run Ansible test validation"""
        try:
            # Get user's VM
            vm_result = await db.execute(
                select(VM).where(VM.user_id == user_id)
            )
            vm = vm_result.scalar_one_or_none()
            if not vm:
                logger.error(f"No VM found for user {user_id}")
                return None
            
            # Get test
            test = await self.get_test_by_id(db, test_id)
            if not test:
                return None
            
            # Run Ansible playbook
            playbook_path = f"{settings.ANSIBLE_PLAYBOOKS_PATH}/verify_test_{test_id}.yml"
            
            cmd = [
                "ansible-playbook",
                playbook_path,
                "-i", f"{vm.vm_id},",  # Note: comma for single host inventory
                "-v" if settings.ANSIBLE_VERBOSITY > 0 else "",
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=settings.ANSIBLE_EXECUTION_TIMEOUT_SECONDS
            )
            
            # Parse Ansible output
            test_result_data = json.loads(result.stdout)
            
            # Create test result
            test_result = TestResult(
                user_id=user_id,
                test_id=test_id,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                result_json=test_result_data,
                score=f"{test_result_data.get('passed_tasks')}/{test_result_data.get('total_tasks')}",
                status=TestStatus.PASSED if test_result_data.get('passed_tasks') == test_result_data.get('total_tasks') else TestStatus.PARTIAL,
            )
            
            db.add(test_result)
            await db.commit()
            await db.refresh(test_result)
            
            logger.info(f"Test {test_id} executed for user {user_id}")
            return test_result
            
        except Exception as e:
            logger.error(f"Error running test validation: {e}")
            return None
    
    async def get_test_result(self, db: AsyncSession, user_id: int, test_id: int) -> TestResult:
        """Get latest test result for user"""
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
