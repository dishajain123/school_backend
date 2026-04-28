# app/api/v1/router.py
from fastapi import APIRouter

from app.api.v1.endpoints.academic_years import router as academic_years_router
from app.api.v1.endpoints.approvals import router as approvals_router
from app.api.v1.endpoints.audit_logs import router as audit_logs_router
from app.api.v1.endpoints.assignments import router as assignments_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.behaviour import router as behaviour_router
from app.api.v1.endpoints.chat import router as chat_router
from app.api.v1.endpoints.complaints import router as complaints_router
from app.api.v1.endpoints.diary import router as diary_router
from app.api.v1.endpoints.documents import router as documents_router
from app.api.v1.endpoints.enrollments import router as enrollments_router   # Phase 6/7
from app.api.v1.endpoints.exam_schedule import router as exam_schedule_router
from app.api.v1.endpoints.fees import router as fees_router
from app.api.v1.endpoints.files import router as files_router
from app.api.v1.endpoints.gallery import router as gallery_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.homework import router as homework_router
from app.api.v1.endpoints.leave import router as leave_router
from app.api.v1.endpoints.masters import router as masters_router
from app.api.v1.endpoints.notifications import router as notifications_router
from app.api.v1.endpoints.parents import router as parents_router
from app.api.v1.endpoints.principal_reports import router as principal_reports_router
from app.api.v1.endpoints.promotions import router as promotions_router     # Phase 7
from app.api.v1.endpoints.registrations import router as registrations_router
from app.api.v1.endpoints.results import router as results_router
from app.api.v1.endpoints.role_profiles import router as role_profiles_router
from app.api.v1.endpoints.schools import router as schools_router
from app.api.v1.endpoints.settings import router as settings_router
from app.api.v1.endpoints.students import router as students_router
from app.api.v1.endpoints.submissions import router as submissions_router
from app.api.v1.endpoints.teacher_assignments import router as teacher_assignments_router
from app.api.v1.endpoints.teacher_class_subjects import router as teacher_class_subjects_router
from app.api.v1.endpoints.teachers import router as teachers_router
from app.api.v1.endpoints.timetable import router as timetable_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(approvals_router)
api_router.include_router(audit_logs_router)
api_router.include_router(assignments_router)
api_router.include_router(behaviour_router)
api_router.include_router(chat_router)
api_router.include_router(complaints_router)
api_router.include_router(diary_router)
api_router.include_router(documents_router)
api_router.include_router(enrollments_router)        # Phase 6/7
api_router.include_router(exam_schedule_router)
api_router.include_router(fees_router)
api_router.include_router(files_router)
api_router.include_router(gallery_router)
api_router.include_router(health_router)
api_router.include_router(homework_router)
api_router.include_router(leave_router)
api_router.include_router(masters_router)
api_router.include_router(notifications_router)
api_router.include_router(parents_router)
api_router.include_router(principal_reports_router)
api_router.include_router(promotions_router)         # Phase 7
api_router.include_router(results_router)
api_router.include_router(registrations_router)
api_router.include_router(role_profiles_router)
api_router.include_router(schools_router)
api_router.include_router(settings_router)
api_router.include_router(submissions_router)
api_router.include_router(students_router)
api_router.include_router(timetable_router)
api_router.include_router(teacher_assignments_router)
api_router.include_router(teacher_class_subjects_router)
api_router.include_router(teachers_router)
api_router.include_router(academic_years_router)
