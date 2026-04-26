"""
Compatibility module for enrollment schemas.

Phase 4 canonical schemas live in student_year_mapping.py.
"""

from app.schemas.student_year_mapping import (  # noqa: F401
    ClassRosterResponse,
    ParentStudentLinkCreate,
    ParentStudentLinkResponse,
    RollNumberAssignRequest,
    StudentExitRequest,
    StudentYearMappingCreate,
    StudentYearMappingResponse,
    StudentYearMappingUpdate,
)
