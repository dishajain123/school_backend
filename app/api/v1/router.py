from fastapi import APIRouter
from app.api.v1.endpoints.schools import router as schools_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.academic_years import router as academic_years_router
from app.api.v1.endpoints.users import router as users_router
from app.api.v1.endpoints.students import router as students_router

api_router = APIRouter()
api_router.include_router(schools_router)
api_router.include_router(auth_router)
api_router.include_router(academic_years_router)
api_router.include_router(users_router)
api_router.include_router(students_router)