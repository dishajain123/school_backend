# 🆕 NEW FILE
# app/api/v1/endpoints/my_class.py
"""
My Class API — Phase: My Class Module

Hierarchy: Subject → Chapter → Topic → ContentItem (note/file/link/quiz)

Role-access summary:
  TEACHER    : create/update/delete chapters, topics, content, quiz, questions
               for their assigned class/section/subject/year only
  STUDENT    : read-only for their enrolled class/section/year
               attempt quizzes (current year only)
  PARENT     : same as student but scoped to child via ?child_id= (decision #4)
  PRINCIPAL / staff admin : read-only everything
  ADMIN      : read-only

All responses are auto-wrapped in the existing envelope:
  { success, data, message, error }
via ApiEnvelopeRoute (app/core/response.py).
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.db.session import get_db
from app.schemas.my_class import (
    AttemptCreate,
    AttemptListResponse,
    AttemptResultResponse,
    ChapterCreate,
    ChapterListResponse,
    ChapterResponse,
    ChapterUpdate,
    ContentItemCreate,
    ContentItemListResponse,
    ContentItemResponse,
    ContentItemUpdate,
    QuestionCreate,
    QuestionResponse,
    QuestionUpdate,
    QuizCreate,
    QuizResponse,
    QuizUpdate,
    QuizWithQuestionsResponse,
    SubjectListForClassResponse,
    TopicCreate,
    TopicListResponse,
    TopicResponse,
    TopicUpdate,
)
from app.services.my_class import MyClassService

router = APIRouter(prefix="/my-class", tags=["My Class"])


def _svc(db: AsyncSession = Depends(get_db)) -> MyClassService:
    return MyClassService(db)


# ─────────────────────────────────────────────────────────────────────────────
# Subjects (entry point — lists subjects with teacher assignments for a class)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/subjects", response_model=SubjectListForClassResponse)
async def list_subjects_for_class(
    standard_id: uuid.UUID = Query(...),
    section_id: uuid.UUID = Query(...),
    academic_year_id: uuid.UUID = Query(...),
    child_id: Optional[uuid.UUID] = Query(None, description="Parent: child student ID"),
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    Lists subjects with teacher assignments for a specific class/section/year.

    - STUDENT: validated against own enrollment
    - PARENT: child_id required; parent-child ownership validated
    - TEACHER: sees assigned subjects for that class/section/year
    - PRINCIPAL/ADMIN: unrestricted
    """
    return await service.list_subjects_for_class(
        standard_id=standard_id,
        section_id=section_id,
        academic_year_id=academic_year_id,
        current_user=current_user,
        child_id=child_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Chapters
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/chapters", response_model=ChapterResponse, status_code=201)
async def create_chapter(
    payload: ChapterCreate,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    Teacher: Create a chapter for a subject/class/section/year.
    Teacher must be assigned to that subject+class+section+year.
    Only allowed for the current academic year.
    """
    return await service.create_chapter(payload, current_user)


@router.get("/chapters", response_model=ChapterListResponse)
async def list_chapters(
    subject_id: uuid.UUID = Query(...),
    standard_id: uuid.UUID = Query(...),
    section_id: uuid.UUID = Query(...),
    academic_year_id: uuid.UUID = Query(...),
    child_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    List all chapters for a subject+class+section+year.
    STUDENT/PARENT: enrollment validated.
    TEACHER: assignment validated.
    """
    return await service.list_chapters(
        subject_id=subject_id,
        standard_id=standard_id,
        section_id=section_id,
        academic_year_id=academic_year_id,
        current_user=current_user,
        child_id=child_id,
    )


@router.patch("/chapters/{chapter_id}", response_model=ChapterResponse)
async def update_chapter(
    chapter_id: uuid.UUID,
    payload: ChapterUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """Teacher: Update chapter title, description, order, or lock state."""
    return await service.update_chapter(chapter_id, payload, current_user)


@router.delete("/chapters/{chapter_id}", status_code=204)
async def delete_chapter(
    chapter_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    Teacher: Delete a chapter and all its topics/content (cascade).
    Only allowed for current academic year.
    """
    await service.delete_chapter(chapter_id, current_user)


# ─────────────────────────────────────────────────────────────────────────────
# Topics
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/topics", response_model=TopicResponse, status_code=201)
async def create_topic(
    payload: TopicCreate,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """Teacher: Add a topic to an existing chapter."""
    return await service.create_topic(payload, current_user)


@router.get("/topics", response_model=TopicListResponse)
async def list_topics(
    chapter_id: uuid.UUID = Query(...),
    child_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """List all topics for a chapter. Access validated per role."""
    return await service.list_topics(
        chapter_id=chapter_id,
        current_user=current_user,
        child_id=child_id,
    )


@router.patch("/topics/{topic_id}", response_model=TopicResponse)
async def update_topic(
    topic_id: uuid.UUID,
    payload: TopicUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """Teacher: Update topic title, description, order, or lock state."""
    return await service.update_topic(topic_id, payload, current_user)


@router.delete("/topics/{topic_id}", status_code=204)
async def delete_topic(
    topic_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """Teacher: Delete a topic and all its content items (cascade)."""
    await service.delete_topic(topic_id, current_user)


# ─────────────────────────────────────────────────────────────────────────────
# Content Items
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/content", response_model=ContentItemResponse, status_code=201)
async def add_content(
    payload: ContentItemCreate,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    Teacher: Add a content item (note/file/link/quiz) to a topic.
    For type='file': upload to MinIO first, pass the returned file_key here.
    For type='quiz': create the quiz first, pass quiz_id here.
    """
    return await service.add_content(payload, current_user)


@router.post("/upload-file")
async def upload_my_class_file(
    standard_id: uuid.UUID = Form(...),
    section_id: uuid.UUID = Form(...),
    subject_id: uuid.UUID = Form(...),
    academic_year_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    Teacher: Upload file binary for My Class content and get file metadata for POST /my-class/content.
    """
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    return await service.upload_content_file(
        current_user=current_user,
        standard_id=standard_id,
        section_id=section_id,
        subject_id=subject_id,
        academic_year_id=academic_year_id,
        file_name=file.filename or "classroom_file",
        content_type=file.content_type or "application/octet-stream",
        file_bytes=file_bytes,
    )


@router.get("/content", response_model=ContentItemListResponse)
async def list_content(
    topic_id: uuid.UUID = Query(...),
    child_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    List all content items for a topic.
    File-type items include a presigned URL (1hr expiry) in the response.
    """
    return await service.list_content(
        topic_id=topic_id,
        current_user=current_user,
        child_id=child_id,
    )


@router.patch("/content/{item_id}", response_model=ContentItemResponse)
async def update_content(
    item_id: uuid.UUID,
    payload: ContentItemUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """Teacher: Update a content item."""
    return await service.update_content(item_id, payload, current_user)


@router.delete("/content/{item_id}", status_code=204)
async def delete_content(
    item_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """Teacher: Delete a content item."""
    await service.delete_content(item_id, current_user)


# ─────────────────────────────────────────────────────────────────────────────
# Quiz
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/quizzes", response_model=QuizWithQuestionsResponse, status_code=201)
async def create_quiz(
    payload: QuizCreate,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    Teacher: Create a quiz for a topic.
    After creation, add questions via POST /my-class/questions,
    then link to content via POST /my-class/content with type='quiz'.
    """
    return await service.create_quiz(payload, current_user)


@router.get("/quizzes/{quiz_id}", response_model=QuizResponse)
async def get_quiz(
    quiz_id: uuid.UUID,
    child_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    Get quiz details.
    TEACHER/ADMIN: full response including correct answers.
    STUDENT/PARENT: response excludes correct answers until submission.
    """
    return await service.get_quiz(quiz_id, current_user, child_id)


@router.patch("/quizzes/{quiz_id}", response_model=QuizWithQuestionsResponse)
async def update_quiz(
    quiz_id: uuid.UUID,
    payload: QuizUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """Teacher: Update quiz metadata (title, duration, lock state)."""
    return await service.update_quiz(quiz_id, payload, current_user)


# ─────────────────────────────────────────────────────────────────────────────
# Questions
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/questions", response_model=QuestionResponse, status_code=201)
async def add_question(
    payload: QuestionCreate,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    Teacher: Add a question to a quiz.
    quiz.total_marks is automatically recalculated after each question add.
    """
    return await service.add_question(payload, current_user)


@router.patch("/questions/{question_id}", response_model=QuestionResponse)
async def update_question(
    question_id: uuid.UUID,
    payload: QuestionUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """Teacher: Update a question. quiz.total_marks is recalculated."""
    return await service.update_question(question_id, payload, current_user)


@router.delete("/questions/{question_id}", status_code=204)
async def delete_question(
    question_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """Teacher: Delete a question. quiz.total_marks is recalculated."""
    await service.delete_question(question_id, current_user)


# ─────────────────────────────────────────────────────────────────────────────
# Quiz Attempts
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/quizzes/{quiz_id}/attempt", response_model=AttemptResultResponse, status_code=201)
async def attempt_quiz(
    quiz_id: uuid.UUID,
    payload: AttemptCreate,
    child_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    Student/Parent: Submit a quiz attempt.

    - Multiple attempts allowed (decision #3)
    - Only permitted for current academic year
    - Returns immediate graded result with per-question breakdown
    - Parent: child_id query param required
    """
    # Ensure quiz_id in path matches payload
    payload = AttemptCreate(quiz_id=quiz_id, answers_json=payload.answers_json)
    return await service.attempt_quiz(payload, current_user, child_id)


@router.get("/quizzes/{quiz_id}/attempts/mine", response_model=AttemptListResponse)
async def my_attempts(
    quiz_id: uuid.UUID,
    child_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    Student/Parent: List all my attempts for a quiz.
    Returns all attempts (latest first) + best_score + latest_attempt_id.
    """
    return await service.list_my_attempts(quiz_id, current_user, child_id)


@router.get("/quizzes/{quiz_id}/attempts", response_model=AttemptListResponse)
async def all_attempts(
    quiz_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: MyClassService = Depends(_svc),
):
    """
    Teacher/Admin: List all student attempts for a quiz (analytics view).
    """
    return await service.list_quiz_attempts_teacher(quiz_id, current_user)
