"""Compatibility service for Phase 7 promotion workflow endpoints.

This module keeps imports stable for `app.api.v1.endpoints.promotions`.
If full workflow logic is moved/renamed, API startup should still succeed
and return a controlled API error instead of crashing at import time.
"""

from __future__ import annotations

import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import GoneException


class PromotionWorkflowService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def preview_promotion(
        self,
        source_year_id: uuid.UUID,
        target_year_id: uuid.UUID,
        school_id: uuid.UUID,
        standard_id: uuid.UUID | None = None,
    ):
        raise GoneException(
            "Promotion workflow service is temporarily unavailable. "
            "Please contact backend team to re-enable Phase 7 workflow."
        )

    async def execute_promotion(self, data, current_user: CurrentUser):
        raise GoneException(
            "Promotion execution service is temporarily unavailable. "
            "Please contact backend team to re-enable Phase 7 workflow."
        )

    async def reenroll_student(self, student_id: uuid.UUID, data, current_user: CurrentUser):
        raise GoneException(
            "Student re-enrollment service is temporarily unavailable. "
            "Please contact backend team to re-enable Phase 7 workflow."
        )

    async def copy_teacher_assignments(self, data, current_user: CurrentUser):
        raise GoneException(
            "Teacher assignment copy service is temporarily unavailable. "
            "Please contact backend team to re-enable Phase 7 workflow."
        )

