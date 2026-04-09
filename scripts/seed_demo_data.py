"""
Seed a realistic demo school dataset for local development.

Usage:
    python -m scripts.seed_demo_data

This script is designed to be idempotent enough for local use:
- it reuses the existing RBAC seed
- it creates a single demo school and academic year if missing
- it creates demo users and related records with fixed identifiers
- it inserts representative operational data for the main modules
"""
import asyncio
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.academic_year import AcademicYear
from app.models.announcement import Announcement
from app.models.assignment import Assignment
from app.models.attendance import Attendance
from app.models.complaint import Complaint
from app.models.conversation import Conversation, ConversationParticipant
from app.models.document import Document
from app.models.exam import Exam
from app.models.exam_schedule import ExamSeries, ExamScheduleEntry
from app.models.fee import FeeLedger, FeeStructure
from app.models.gallery import GalleryAlbum, GalleryPhoto
from app.models.homework import Homework
from app.models.leave_balance import LeaveBalance
from app.models.masters import GradeMaster, Standard, Subject
from app.models.message import Message, MessageRead
from app.models.notification import Notification
from app.models.parent import Parent
from app.models.payment import Payment
from app.models.result import Result
from app.models.school import School
from app.models.school_settings import SchoolSetting
from app.models.student import Student
from app.models.student_behaviour_log import StudentBehaviourLog
from app.models.student_diary import StudentDiary
from app.models.submission import Submission
from app.models.teacher import Teacher
from app.models.teacher_class_subject import TeacherClassSubject
from app.models.teacher_leave import TeacherLeave
from app.models.timetable import Timetable
from app.models.user import User
from app.utils.enums import (
    AnnouncementType,
    AttendanceStatus,
    ComplaintCategory,
    ComplaintStatus,
    ConversationType,
    DocumentStatus,
    DocumentType,
    ExamType,
    FeeCategory,
    FeeStatus,
    IncidentSeverity,
    IncidentType,
    LeaveStatus,
    LeaveType,
    MessageType,
    NotificationPriority,
    NotificationType,
    PaymentMode,
    RelationType,
    RoleEnum,
    SubscriptionPlan,
)
from scripts.seed_masters import seed as seed_masters
from scripts.seed_roles_permissions import seed as seed_roles_permissions


DEMO_PASSWORD = "Demo@123"


async def first_or_none(db: AsyncSession, stmt):
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_school(db: AsyncSession) -> School:
    school = await first_or_none(
        db,
        select(School).where(School.contact_email == "admin@greenfieldacademy.edu"),
    )
    if school:
        return school

    school = School(
        name="Greenfield Academy",
        address="42 Cedar Avenue, Bengaluru",
        contact_email="admin@greenfieldacademy.edu",
        contact_phone="+91-80-5555-0100",
        subscription_plan=SubscriptionPlan.PREMIUM,
        is_active=True,
    )
    db.add(school)
    await db.flush()
    return school


async def get_or_create_academic_year(db: AsyncSession, school_id) -> AcademicYear:
    year = await first_or_none(
        db,
        select(AcademicYear).where(
            AcademicYear.school_id == school_id,
            AcademicYear.name == "2025-2026",
        ),
    )
    if year:
        if not year.is_active:
            year.is_active = True
            await db.flush()
        return year

    await db.execute(
        select(AcademicYear).where(
            AcademicYear.school_id == school_id,
            AcademicYear.is_active.is_(True),
        )
    )
    year = AcademicYear(
        name="2025-2026",
        start_date=date(2025, 6, 1),
        end_date=date(2026, 3, 31),
        is_active=True,
        school_id=school_id,
    )
    db.add(year)
    await db.flush()
    return year


async def get_or_create_user(
    db: AsyncSession,
    *,
    email: str,
    phone: str,
    role: RoleEnum,
    school_id,
    password: str = DEMO_PASSWORD,
) -> User:
    user = await first_or_none(db, select(User).where(User.email == email))
    if user:
        changed = False
        if user.school_id != school_id:
            user.school_id = school_id
            changed = True
        if user.phone != phone:
            user.phone = phone
            changed = True
        if user.role != role:
            user.role = role
            changed = True
        if not user.hashed_password:
            user.hashed_password = hash_password(password)
            changed = True
        if changed:
            await db.flush()
        return user

    user = User(
        email=email,
        phone=phone,
        hashed_password=hash_password(password),
        role=role,
        school_id=school_id,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def get_or_create_parent(db: AsyncSession, *, user_id, school_id, occupation: str, relation: RelationType) -> Parent:
    parent = await first_or_none(db, select(Parent).where(Parent.user_id == user_id))
    if parent:
        return parent
    parent = Parent(
        user_id=user_id,
        school_id=school_id,
        occupation=occupation,
        relation=relation,
    )
    db.add(parent)
    await db.flush()
    return parent


async def get_or_create_teacher(
    db: AsyncSession,
    *,
    user_id,
    school_id,
    academic_year_id,
    employee_code: str,
    specialization: str,
    join_date_value: date,
) -> Teacher:
    teacher = await first_or_none(db, select(Teacher).where(Teacher.user_id == user_id))
    if teacher:
        return teacher
    teacher = Teacher(
        user_id=user_id,
        school_id=school_id,
        academic_year_id=academic_year_id,
        employee_code=employee_code,
        specialization=specialization,
        join_date=join_date_value,
    )
    db.add(teacher)
    await db.flush()
    return teacher


async def get_or_create_student(
    db: AsyncSession,
    *,
    user_id,
    school_id,
    parent_id,
    standard_id,
    academic_year_id,
    section: str,
    roll_number: str,
    admission_number: str,
    date_of_birth_value: date,
    admission_date_value: date,
) -> Student:
    student = await first_or_none(
        db,
        select(Student).where(
            Student.school_id == school_id,
            Student.admission_number == admission_number,
        ),
    )
    if student:
        return student
    student = Student(
        user_id=user_id,
        school_id=school_id,
        parent_id=parent_id,
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        section=section,
        roll_number=roll_number,
        admission_number=admission_number,
        date_of_birth=date_of_birth_value,
        admission_date=admission_date_value,
        is_promoted=False,
    )
    db.add(student)
    await db.flush()
    return student


async def get_standard_by_level(db: AsyncSession, school_id, academic_year_id, level: int) -> Standard:
    standard = await first_or_none(
        db,
        select(Standard).where(
            Standard.school_id == school_id,
            Standard.academic_year_id == academic_year_id,
            Standard.level == level,
        ),
    )
    if not standard:
        raise ValueError(f"Missing standard for level {level}")
    return standard


async def get_subject_by_code(db: AsyncSession, school_id, code: str) -> Subject:
    subject = await first_or_none(
        db,
        select(Subject).where(Subject.school_id == school_id, Subject.code == code),
    )
    if not subject:
        raise ValueError(f"Missing subject {code}")
    return subject


async def get_grade_for_percent(db: AsyncSession, school_id, percent: Decimal) -> GradeMaster:
    grade = await first_or_none(
        db,
        select(GradeMaster).where(
            GradeMaster.school_id == school_id,
            GradeMaster.min_percent <= percent,
            GradeMaster.max_percent >= percent,
        ),
    )
    if not grade:
        raise ValueError(f"No grade configured for percent {percent}")
    return grade


async def ensure_school_settings(
    db: AsyncSession,
    school_id,
    updated_by,
    *,
    class8_id,
    class10_id,
    academic_year_id,
) -> None:
    sections_registry = {
        "standards": {
            str(class8_id): {str(academic_year_id): ["A", "B"]},
            str(class10_id): {str(academic_year_id): ["A", "B"]},
        }
    }
    settings_payload = {
        "attendance_grace_minutes": "10",
        "school_day_start": "08:15",
        "school_day_end": "15:30",
        "fee_due_day": "10",
        "result_publish_mode": "principal_approval",
        "class_sections_registry": json.dumps(sections_registry, separators=(",", ":")),
    }
    for key, value in settings_payload.items():
        existing = await first_or_none(
            db,
            select(SchoolSetting).where(
                SchoolSetting.school_id == school_id,
                SchoolSetting.setting_key == key,
            ),
        )
        if existing:
            existing.setting_value = value
            existing.updated_by = updated_by
        else:
            db.add(
                SchoolSetting(
                    school_id=school_id,
                    setting_key=key,
                    setting_value=value,
                    updated_by=updated_by,
                )
            )
    await db.flush()


async def seed_demo(db: AsyncSession) -> dict[str, str]:
    await seed_roles_permissions(db)

    school = await get_or_create_school(db)
    year = await get_or_create_academic_year(db, school.id)
    await db.commit()

    await seed_masters(school.id, year.id)

    principal_user = await get_or_create_user(
        db,
        email="principal@greenfieldacademy.edu",
        phone="+919900000101",
        role=RoleEnum.PRINCIPAL,
        school_id=school.id,
    )
    trustee_user = await get_or_create_user(
        db,
        email="trustee@greenfieldacademy.edu",
        phone="+919900000102",
        role=RoleEnum.TRUSTEE,
        school_id=school.id,
    )
    teacher_math_user = await get_or_create_user(
        db,
        email="ananya.sharma@greenfieldacademy.edu",
        phone="+919900000201",
        role=RoleEnum.TEACHER,
        school_id=school.id,
    )
    teacher_science_user = await get_or_create_user(
        db,
        email="rohit.verma@greenfieldacademy.edu",
        phone="+919900000202",
        role=RoleEnum.TEACHER,
        school_id=school.id,
    )
    teacher_english_user = await get_or_create_user(
        db,
        email="neha.dsouza@greenfieldacademy.edu",
        phone="+919900000203",
        role=RoleEnum.TEACHER,
        school_id=school.id,
    )

    parent_rao_user = await get_or_create_user(
        db,
        email="meera.rao.parent@greenfieldacademy.edu",
        phone="+919900000301",
        role=RoleEnum.PARENT,
        school_id=school.id,
    )
    parent_khan_user = await get_or_create_user(
        db,
        email="imran.khan.parent@greenfieldacademy.edu",
        phone="+919900000302",
        role=RoleEnum.PARENT,
        school_id=school.id,
    )
    parent_iyer_user = await get_or_create_user(
        db,
        email="lakshmi.iyer.parent@greenfieldacademy.edu",
        phone="+919900000303",
        role=RoleEnum.PARENT,
        school_id=school.id,
    )

    student_users = [
        await get_or_create_user(
            db,
            email="aarav.rao@greenfieldacademy.edu",
            phone="+919900000401",
            role=RoleEnum.STUDENT,
            school_id=school.id,
        ),
        await get_or_create_user(
            db,
            email="isha.rao@greenfieldacademy.edu",
            phone="+919900000402",
            role=RoleEnum.STUDENT,
            school_id=school.id,
        ),
        await get_or_create_user(
            db,
            email="zara.khan@greenfieldacademy.edu",
            phone="+919900000403",
            role=RoleEnum.STUDENT,
            school_id=school.id,
        ),
        await get_or_create_user(
            db,
            email="reyaan.khan@greenfieldacademy.edu",
            phone="+919900000404",
            role=RoleEnum.STUDENT,
            school_id=school.id,
        ),
        await get_or_create_user(
            db,
            email="diya.iyer@greenfieldacademy.edu",
            phone="+919900000405",
            role=RoleEnum.STUDENT,
            school_id=school.id,
        ),
        await get_or_create_user(
            db,
            email="vivaan.iyer@greenfieldacademy.edu",
            phone="+919900000406",
            role=RoleEnum.STUDENT,
            school_id=school.id,
        ),
    ]

    parent_rao = await get_or_create_parent(
        db, user_id=parent_rao_user.id, school_id=school.id, occupation="Product Manager", relation=RelationType.MOTHER
    )
    parent_khan = await get_or_create_parent(
        db, user_id=parent_khan_user.id, school_id=school.id, occupation="Architect", relation=RelationType.FATHER
    )
    parent_iyer = await get_or_create_parent(
        db, user_id=parent_iyer_user.id, school_id=school.id, occupation="Doctor", relation=RelationType.GUARDIAN
    )

    teacher_math = await get_or_create_teacher(
        db,
        user_id=teacher_math_user.id,
        school_id=school.id,
        academic_year_id=year.id,
        employee_code="TCH-1001",
        specialization="Mathematics",
        join_date_value=date(2021, 6, 1),
    )
    teacher_science = await get_or_create_teacher(
        db,
        user_id=teacher_science_user.id,
        school_id=school.id,
        academic_year_id=year.id,
        employee_code="TCH-1002",
        specialization="Science",
        join_date_value=date(2020, 6, 1),
    )
    teacher_english = await get_or_create_teacher(
        db,
        user_id=teacher_english_user.id,
        school_id=school.id,
        academic_year_id=year.id,
        employee_code="TCH-1003",
        specialization="English",
        join_date_value=date(2022, 6, 1),
    )

    class8 = await get_standard_by_level(db, school.id, year.id, 8)
    class10 = await get_standard_by_level(db, school.id, year.id, 10)

    eng08 = await get_subject_by_code(db, school.id, "ENG08")
    math08 = await get_subject_by_code(db, school.id, "MATH08")
    sci08 = await get_subject_by_code(db, school.id, "SCI08")
    eng10 = await get_subject_by_code(db, school.id, "ENG10")
    math10 = await get_subject_by_code(db, school.id, "MATH10")
    sci10 = await get_subject_by_code(db, school.id, "SCI10")

    student_specs = [
        (student_users[0], parent_rao, class8, "A", "08A-01", "ADM-2025-0801", date(2012, 5, 14)),
        (student_users[1], parent_rao, class8, "B", "08B-01", "ADM-2025-0802", date(2012, 9, 21)),
        (student_users[2], parent_khan, class8, "A", "08A-02", "ADM-2025-0803", date(2012, 11, 2)),
        (student_users[3], parent_khan, class10, "A", "10A-01", "ADM-2025-1001", date(2010, 3, 18)),
        (student_users[4], parent_iyer, class10, "B", "10B-01", "ADM-2025-1002", date(2010, 7, 5)),
        (student_users[5], parent_iyer, class10, "B", "10B-02", "ADM-2025-1003", date(2010, 12, 9)),
    ]

    students: list[Student] = []
    for user, parent, standard, section, roll, admission, dob in student_specs:
        students.append(
            await get_or_create_student(
                db,
                user_id=user.id,
                school_id=school.id,
                parent_id=parent.id,
                standard_id=standard.id,
                academic_year_id=year.id,
                section=section,
                roll_number=roll,
                admission_number=admission,
                date_of_birth_value=dob,
                admission_date_value=date(2025, 6, 10),
            )
        )

    await ensure_school_settings(
        db,
        school.id,
        principal_user.id,
        class8_id=class8.id,
        class10_id=class10.id,
        academic_year_id=year.id,
    )

    assignment_specs = [
        (teacher_math.id, class8.id, "A", math08.id),
        (teacher_science.id, class8.id, "A", sci08.id),
        (teacher_english.id, class8.id, "A", eng08.id),
        (teacher_math.id, class8.id, "B", math08.id),
        (teacher_science.id, class8.id, "B", sci08.id),
        (teacher_english.id, class8.id, "B", eng08.id),
        (teacher_math.id, class10.id, "A", math10.id),
        (teacher_science.id, class10.id, "A", sci10.id),
        (teacher_english.id, class10.id, "A", eng10.id),
        (teacher_math.id, class10.id, "B", math10.id),
        (teacher_science.id, class10.id, "B", sci10.id),
        (teacher_english.id, class10.id, "B", eng10.id),
    ]
    for teacher_id, standard_id, section, subject_id in assignment_specs:
        existing = await first_or_none(
            db,
            select(TeacherClassSubject).where(
                TeacherClassSubject.teacher_id == teacher_id,
                TeacherClassSubject.standard_id == standard_id,
                TeacherClassSubject.section == section,
                TeacherClassSubject.subject_id == subject_id,
                TeacherClassSubject.academic_year_id == year.id,
            ),
        )
        if not existing:
            db.add(
                TeacherClassSubject(
                    teacher_id=teacher_id,
                    standard_id=standard_id,
                    section=section,
                    subject_id=subject_id,
                    academic_year_id=year.id,
                )
            )

    await db.flush()

    today = date.today()
    attendance_rows = []
    class_subject_map = {
        class8.id: (teacher_math, class8, math08),
        class10.id: (teacher_science, class10, sci10),
    }
    for day_offset in range(0, 14):
        attendance_date = today - timedelta(days=day_offset)
        if attendance_date.weekday() >= 5:
            continue
        for idx, student in enumerate(students):
            class_tuple = class_subject_map.get(student.standard_id)
            if not class_tuple:
                continue
            teacher_ref, standard_ref, subject_ref = class_tuple
            if day_offset % 9 == (idx % 3):
                status = AttendanceStatus.ABSENT
            elif day_offset % 4 == (idx % 2):
                status = AttendanceStatus.LATE
            else:
                status = AttendanceStatus.PRESENT
            attendance_rows.append(
                (student, teacher_ref, standard_ref, subject_ref, attendance_date, status)
            )

    for student, teacher, standard, subject, attendance_date, status in attendance_rows:
        exists = await first_or_none(
            db,
            select(Attendance).where(
                Attendance.student_id == student.id,
                Attendance.subject_id == subject.id,
                Attendance.date == attendance_date,
            ),
        )
        if not exists:
            db.add(
                Attendance(
                    student_id=student.id,
                    teacher_id=teacher.id,
                    standard_id=standard.id,
                    section=(student.section or "").strip(),
                    subject_id=subject.id,
                    academic_year_id=year.id,
                    date=attendance_date,
                    status=status,
                )
            )

    content_dates = {
        "class8": today - timedelta(days=1),
        "class10": today - timedelta(days=2),
    }

    timetable_rows = [
        (class8.id, "A", "demo/timetables/class8a_2025_26.pdf"),
        (class8.id, "B", "demo/timetables/class8b_2025_26.pdf"),
        (class10.id, "A", "demo/timetables/class10a_2025_26.pdf"),
        (class10.id, "B", "demo/timetables/class10b_2025_26.pdf"),
    ]
    for standard_id, section_value, file_key in timetable_rows:
        existing = await first_or_none(
            db,
            select(Timetable).where(
                Timetable.school_id == school.id,
                Timetable.standard_id == standard_id,
                Timetable.section == section_value,
                Timetable.academic_year_id == year.id,
            ),
        )
        if not existing:
            db.add(
                Timetable(
                    standard_id=standard_id,
                    section=section_value,
                    academic_year_id=year.id,
                    file_key=file_key,
                    effective_from=year.start_date,
                    effective_to=year.end_date,
                    uploaded_by=principal_user.id,
                    school_id=school.id,
                )
            )

    homework_rows = [
        (
            "class8-math",
            Homework,
            dict(
                description="Solve linear equations from exercise 4A and write two real-world word problems.",
                date=content_dates["class8"],
                teacher_id=teacher_math.id,
                standard_id=class8.id,
                subject_id=math08.id,
                academic_year_id=year.id,
                school_id=school.id,
            ),
        ),
        (
            "class10-science",
            Homework,
            dict(
                description="Prepare a short note on metals vs non-metals and complete lab observation sheet 3.",
                date=content_dates["class10"],
                teacher_id=teacher_science.id,
                standard_id=class10.id,
                subject_id=sci10.id,
                academic_year_id=year.id,
                school_id=school.id,
            ),
        ),
        (
            "class8-english",
            Homework,
            dict(
                description="Read chapter 7 and write a 250-word character sketch of the protagonist.",
                date=today - timedelta(days=3),
                teacher_id=teacher_english.id,
                standard_id=class8.id,
                subject_id=eng08.id,
                academic_year_id=year.id,
                school_id=school.id,
            ),
        ),
        (
            "class10-math",
            Homework,
            dict(
                description="Solve trigonometry worksheet set C before the weekend revision class.",
                date=today - timedelta(days=4),
                teacher_id=teacher_math.id,
                standard_id=class10.id,
                subject_id=math10.id,
                academic_year_id=year.id,
                school_id=school.id,
            ),
        ),
    ]
    for _, model_cls, payload in homework_rows:
        exists = await first_or_none(
            db,
            select(model_cls).where(
                model_cls.school_id == payload["school_id"],
                model_cls.standard_id == payload["standard_id"],
                model_cls.subject_id == payload["subject_id"],
                model_cls.date == payload["date"],
                model_cls.academic_year_id == payload["academic_year_id"],
            ),
        )
        if not exists:
            db.add(model_cls(**payload))

    diary_rows = [
        dict(
            topic_covered="Introduction to linear equations in one variable",
            homework_note="Revise solved examples 1 to 5 before tomorrow's class quiz.",
            date=content_dates["class8"],
            teacher_id=teacher_math.id,
            standard_id=class8.id,
            subject_id=math08.id,
            academic_year_id=year.id,
            school_id=school.id,
        ),
        dict(
            topic_covered="Chemical reactions and balancing equations",
            homework_note="Bring notebook and lab coat for the practical session on Friday.",
            date=content_dates["class10"],
            teacher_id=teacher_science.id,
            standard_id=class10.id,
            subject_id=sci10.id,
            academic_year_id=year.id,
            school_id=school.id,
        ),
    ]
    for payload in diary_rows:
        exists = await first_or_none(
            db,
            select(StudentDiary).where(
                StudentDiary.school_id == payload["school_id"],
                StudentDiary.standard_id == payload["standard_id"],
                StudentDiary.subject_id == payload["subject_id"],
                StudentDiary.date == payload["date"],
                StudentDiary.academic_year_id == payload["academic_year_id"],
            ),
        )
        if not exists:
            db.add(StudentDiary(**payload))

    assignment_specs = [
        dict(
            title="Linear Equations Worksheet",
            description="Complete the worksheet and upload scanned solutions by Friday evening.",
            teacher_id=teacher_math.id,
            standard_id=class8.id,
            subject_id=math08.id,
            due_date=today + timedelta(days=2),
            file_key="demo/assignments/linear_equations_worksheet.pdf",
        ),
        dict(
            title="Acids, Bases and Salts Revision",
            description="Submit concise revision notes and 15 objective questions.",
            teacher_id=teacher_science.id,
            standard_id=class10.id,
            subject_id=sci10.id,
            due_date=today + timedelta(days=1),
            file_key="demo/assignments/acids_bases_revision.pdf",
        ),
    ]
    assignments_by_title: dict[str, Assignment] = {}
    for spec in assignment_specs:
        assignment = await first_or_none(
            db,
            select(Assignment).where(
                Assignment.school_id == school.id,
                Assignment.title == spec["title"],
            ),
        )
        if not assignment:
            assignment = Assignment(
                title=spec["title"],
                description=spec["description"],
                teacher_id=spec["teacher_id"],
                standard_id=spec["standard_id"],
                subject_id=spec["subject_id"],
                due_date=spec["due_date"],
                file_key=spec["file_key"],
                is_active=True,
                academic_year_id=year.id,
                school_id=school.id,
            )
            db.add(assignment)
            await db.flush()
        assignments_by_title[spec["title"]] = assignment

    submission_specs = [
        (
            "Linear Equations Worksheet",
            students[0],
            "Completed all 10 problems and attached rough work.",
            "A",
            "Good structure and neat working.",
            True,
            False,
        ),
        (
            "Linear Equations Worksheet",
            students[1],
            "Attached worksheet with one incomplete answer.",
            "B+",
            "Recheck question 7.",
            True,
            False,
        ),
        (
            "Acids, Bases and Salts Revision",
            students[3],
            "Shared revision notes with all objective answers.",
            "A-",
            "Good understanding. Add more balanced equations.",
            True,
            False,
        ),
        (
            "Acids, Bases and Salts Revision",
            students[5],
            "Submitted after deadline due to internet issue.",
            None,
            None,
            False,
            True,
        ),
    ]
    for (
        assignment_title,
        student,
        text_response,
        grade,
        feedback,
        is_graded,
        is_late,
    ) in submission_specs:
        assignment = assignments_by_title[assignment_title]
        existing = await first_or_none(
            db,
            select(Submission).where(
                Submission.assignment_id == assignment.id,
                Submission.student_id == student.id,
            ),
        )
        if not existing:
            db.add(
                Submission(
                    assignment_id=assignment.id,
                    student_id=student.id,
                    performed_by=student.user_id,
                    file_key=f"demo/submissions/{student.admission_number.lower()}_{assignment.id}.pdf",
                    text_response=text_response,
                    grade=grade,
                    feedback=feedback,
                    is_graded=is_graded,
                    is_late=is_late,
                    school_id=school.id,
                )
            )

    announcements = [
        (
            "Annual Day Rehearsal Schedule",
            "Classes 8 to 10 will report to the auditorium at 1:30 PM from Monday to Wednesday for rehearsals.",
            AnnouncementType.EVENT,
            None,
            None,
        ),
        (
            "Midterm Exams Begin Next Week",
            "Please review the published timetable. Students should carry ID cards and transparent stationery pouches.",
            AnnouncementType.EXAM,
            RoleEnum.STUDENT,
            class10.id,
        ),
        (
            "Fee Counter Extended Hours",
            "School fee office will remain open till 5:30 PM on Friday for quarter-end settlements.",
            AnnouncementType.GENERAL,
            RoleEnum.PARENT,
            None,
        ),
        (
            "Holiday Notice - School Foundation Day",
            "School will remain closed on Monday for Foundation Day celebrations and staff development activities.",
            AnnouncementType.HOLIDAY,
            None,
            None,
        ),
    ]
    for title, body, ann_type, target_role, target_standard_id in announcements:
        existing = await first_or_none(
            db,
            select(Announcement).where(
                Announcement.school_id == school.id,
                Announcement.title == title,
            ),
        )
        if not existing:
            db.add(
                Announcement(
                    title=title,
                    body=body,
                    type=ann_type,
                    created_by=principal_user.id,
                    target_role=target_role,
                    target_standard_id=target_standard_id,
                    attachment_key=None,
                    school_id=school.id,
                )
            )

    fee_structure_specs = [
        (class8.id, FeeCategory.TUITION, Decimal("45000.00"), date(2025, 7, 10), "Annual tuition for Class 8"),
        (class8.id, FeeCategory.TRANSPORT, Decimal("12000.00"), date(2025, 7, 10), "Bus transport fee for Class 8"),
        (class8.id, FeeCategory.LIBRARY, Decimal("3500.00"), date(2025, 8, 5), "Annual library and digital resource fee"),
        (class10.id, FeeCategory.TUITION, Decimal("52000.00"), date(2025, 7, 10), "Annual tuition for Class 10"),
        (class10.id, FeeCategory.LABORATORY, Decimal("6000.00"), date(2025, 8, 20), "Laboratory maintenance and consumables"),
        (class10.id, FeeCategory.EXAMINATION, Decimal("8500.00"), date(2025, 11, 15), "Board preparation and exam fee"),
    ]
    fee_structures: list[FeeStructure] = []
    for standard_id, category, amount, due_date_value, description in fee_structure_specs:
        fee_structure = await first_or_none(
            db,
            select(FeeStructure).where(
                FeeStructure.school_id == school.id,
                FeeStructure.standard_id == standard_id,
                FeeStructure.academic_year_id == year.id,
                FeeStructure.fee_category == category,
            ),
        )
        if not fee_structure:
            fee_structure = FeeStructure(
                standard_id=standard_id,
                academic_year_id=year.id,
                fee_category=category,
                amount=amount,
                due_date=due_date_value,
                description=description,
                school_id=school.id,
            )
            db.add(fee_structure)
            await db.flush()
        fee_structures.append(fee_structure)

    student_by_standard = {class8.id: students[:3], class10.id: students[3:]}
    fee_ledger_by_student: dict[tuple, FeeLedger] = {}
    for structure in fee_structures:
        for student in student_by_standard[structure.standard_id]:
            ledger = await first_or_none(
                db,
                select(FeeLedger).where(
                    FeeLedger.student_id == student.id,
                    FeeLedger.fee_structure_id == structure.id,
                ),
            )
            paid_amount = Decimal("0.00")
            status = FeeStatus.PENDING
            if structure.fee_category == FeeCategory.TUITION and student in {students[0], students[3], students[4]}:
                paid_amount = structure.amount if student in {students[0], students[4]} else Decimal("25000.00")
                status = FeeStatus.PAID if paid_amount == structure.amount else FeeStatus.PARTIAL
            if structure.fee_category == FeeCategory.TRANSPORT and student == students[1]:
                paid_amount = Decimal("5000.00")
                status = FeeStatus.PARTIAL
            if structure.fee_category == FeeCategory.LIBRARY and student == students[0]:
                paid_amount = structure.amount
                status = FeeStatus.PAID
            if structure.fee_category == FeeCategory.LABORATORY and student == students[4]:
                paid_amount = structure.amount
                status = FeeStatus.PAID
            if structure.fee_category == FeeCategory.EXAMINATION and student == students[3]:
                paid_amount = Decimal("4000.00")
                status = FeeStatus.PARTIAL

            if not ledger:
                ledger = FeeLedger(
                    student_id=student.id,
                    fee_structure_id=structure.id,
                    total_amount=structure.amount,
                    paid_amount=paid_amount,
                    status=status,
                    school_id=school.id,
                )
                db.add(ledger)
                await db.flush()
            else:
                ledger.total_amount = structure.amount
                ledger.paid_amount = paid_amount
                ledger.status = status
            fee_ledger_by_student[(student.id, structure.id)] = ledger

    for structure in fee_structures:
        for student in student_by_standard[structure.standard_id]:
            ledger = fee_ledger_by_student[(student.id, structure.id)]
            total_paid = Decimal(str(ledger.paid_amount))
            if total_paid <= Decimal("0.00"):
                continue

            payment_splits = [total_paid]
            payment_modes = [PaymentMode.UPI]
            if structure.fee_category == FeeCategory.TUITION and student == students[3]:
                payment_splits = [Decimal("15000.00"), Decimal("10000.00")]
                payment_modes = [PaymentMode.BANK_TRANSFER, PaymentMode.UPI]
            elif structure.fee_category == FeeCategory.TUITION and student == students[4]:
                payment_modes = [PaymentMode.ONLINE]
            elif structure.fee_category == FeeCategory.LIBRARY:
                payment_modes = [PaymentMode.CASH]
            elif structure.fee_category == FeeCategory.LABORATORY:
                payment_modes = [PaymentMode.BANK_TRANSFER]
            elif structure.fee_category == FeeCategory.TRANSPORT:
                payment_modes = [PaymentMode.CHEQUE]
            elif structure.fee_category == FeeCategory.EXAMINATION:
                payment_modes = [PaymentMode.UPI]

            for idx, split_amount in enumerate(payment_splits):
                ref = (
                    f"{payment_modes[min(idx, len(payment_modes)-1)].value}-"
                    f"{student.roll_number}-{structure.fee_category.value}-{idx+1}"
                )
                existing = await first_or_none(
                    db,
                    select(Payment).where(
                        Payment.fee_ledger_id == ledger.id,
                        Payment.reference_number == ref,
                    ),
                )
                if not existing:
                    db.add(
                        Payment(
                            student_id=student.id,
                            fee_ledger_id=ledger.id,
                            amount=split_amount,
                            payment_date=max(
                                structure.due_date - timedelta(days=2 - idx),
                                year.start_date,
                            ),
                            payment_mode=payment_modes[min(idx, len(payment_modes)-1)],
                            reference_number=ref,
                            receipt_key=(
                                f"demo/receipts/"
                                f"{student.admission_number.lower()}_{structure.fee_category.value.lower()}_{idx+1}.pdf"
                            ),
                            recorded_by=principal_user.id,
                            late_fee_applied=(structure.due_date < today and idx == 0),
                            original_due_date=structure.due_date,
                            school_id=school.id,
                        )
                    )

    exam_definitions = [
        (
            "Midterm Examination",
            class10,
            ExamType.MIDTERM,
            date(2025, 9, 16),
            date(2025, 9, 24),
            "Class 10 Midterm Series",
            [
                (math10.id, date(2025, 9, 16), time(9, 0), 120, "Hall A"),
                (sci10.id, date(2025, 9, 18), time(9, 0), 120, "Science Lab Block"),
                (eng10.id, date(2025, 9, 22), time(9, 0), 90, "Hall A"),
            ],
        ),
        (
            "Unit Test - Cycle 2",
            class8,
            ExamType.UNIT,
            date(2025, 8, 20),
            date(2025, 8, 26),
            "Class 8 Unit Test Series",
            [
                (math08.id, date(2025, 8, 20), time(9, 30), 60, "Class 8A"),
                (sci08.id, date(2025, 8, 22), time(9, 30), 60, "Science Lab 1"),
                (eng08.id, date(2025, 8, 25), time(9, 30), 60, "Class 8A"),
            ],
        ),
    ]
    exam_by_name: dict[str, Exam] = {}
    for (
        exam_name,
        standard,
        exam_type,
        start_date_value,
        end_date_value,
        series_name,
        series_entries,
    ) in exam_definitions:
        exam = await first_or_none(
            db,
            select(Exam).where(
                Exam.school_id == school.id,
                Exam.standard_id == standard.id,
                Exam.academic_year_id == year.id,
                Exam.name == exam_name,
            ),
        )
        if not exam:
            exam = Exam(
                name=exam_name,
                exam_type=exam_type,
                standard_id=standard.id,
                academic_year_id=year.id,
                start_date=start_date_value,
                end_date=end_date_value,
                created_by=principal_user.id,
                school_id=school.id,
            )
            db.add(exam)
            await db.flush()
        exam_by_name[exam_name] = exam

        exam_series = await first_or_none(
            db,
            select(ExamSeries).where(
                ExamSeries.school_id == school.id,
                ExamSeries.standard_id == standard.id,
                ExamSeries.academic_year_id == year.id,
                ExamSeries.name == series_name,
            ),
        )
        if not exam_series:
            exam_series = ExamSeries(
                name=series_name,
                standard_id=standard.id,
                academic_year_id=year.id,
                is_published=True,
                created_by=principal_user.id,
                school_id=school.id,
            )
            db.add(exam_series)
            await db.flush()

        for subject_id, exam_date_value, start_time_value, duration, venue in series_entries:
            existing = await first_or_none(
                db,
                select(ExamScheduleEntry).where(
                    ExamScheduleEntry.series_id == exam_series.id,
                    ExamScheduleEntry.subject_id == subject_id,
                ),
            )
            if not existing:
                db.add(
                    ExamScheduleEntry(
                        series_id=exam_series.id,
                        subject_id=subject_id,
                        exam_date=exam_date_value,
                        start_time=start_time_value,
                        duration_minutes=duration,
                        venue=venue,
                        is_cancelled=False,
                    )
                )

    result_specs = [
        ("Midterm Examination", students[3], math10, Decimal("86.00"), teacher_math_user.id),
        ("Midterm Examination", students[3], sci10, Decimal("78.00"), teacher_science_user.id),
        ("Midterm Examination", students[3], eng10, Decimal("88.00"), teacher_english_user.id),
        ("Midterm Examination", students[4], math10, Decimal("92.00"), teacher_math_user.id),
        ("Midterm Examination", students[4], sci10, Decimal("81.00"), teacher_science_user.id),
        ("Midterm Examination", students[4], eng10, Decimal("84.00"), teacher_english_user.id),
        ("Midterm Examination", students[5], math10, Decimal("67.00"), teacher_math_user.id),
        ("Midterm Examination", students[5], sci10, Decimal("73.00"), teacher_science_user.id),
        ("Midterm Examination", students[5], eng10, Decimal("70.00"), teacher_english_user.id),
        ("Unit Test - Cycle 2", students[0], math08, Decimal("79.00"), teacher_math_user.id),
        ("Unit Test - Cycle 2", students[0], sci08, Decimal("83.00"), teacher_science_user.id),
        ("Unit Test - Cycle 2", students[0], eng08, Decimal("88.00"), teacher_english_user.id),
        ("Unit Test - Cycle 2", students[1], math08, Decimal("72.00"), teacher_math_user.id),
        ("Unit Test - Cycle 2", students[1], sci08, Decimal("69.00"), teacher_science_user.id),
        ("Unit Test - Cycle 2", students[1], eng08, Decimal("81.00"), teacher_english_user.id),
        ("Unit Test - Cycle 2", students[2], math08, Decimal("65.00"), teacher_math_user.id),
        ("Unit Test - Cycle 2", students[2], sci08, Decimal("74.00"), teacher_science_user.id),
        ("Unit Test - Cycle 2", students[2], eng08, Decimal("71.00"), teacher_english_user.id),
    ]
    for exam_name, student, subject, marks, entered_by in result_specs:
        exam = exam_by_name[exam_name]
        existing = await first_or_none(
            db,
            select(Result).where(
                Result.exam_id == exam.id,
                Result.student_id == student.id,
                Result.subject_id == subject.id,
            ),
        )
        if existing:
            continue
        grade = await get_grade_for_percent(db, school.id, marks)
        db.add(
            Result(
                exam_id=exam.id,
                student_id=student.id,
                subject_id=subject.id,
                marks_obtained=marks,
                max_marks=Decimal("100.00"),
                percentage=marks,
                grade_id=grade.id,
                is_published=True,
                entered_by=entered_by,
                school_id=school.id,
            )
        )

    complaint_rows = [
        (
            parent_rao_user.id,
            ComplaintCategory.ACADEMIC,
            "Class 8 mathematics assignment deadlines are too close together during exam prep week.",
            ComplaintStatus.IN_PROGRESS,
            principal_user.id,
            "Reviewed with the mathematics department. Future deadlines will be staggered.",
            False,
        ),
        (
            student_users[5].id,
            ComplaintCategory.INFRASTRUCTURE,
            "Projector in Class 10B occasionally flickers during science presentations.",
            ComplaintStatus.RESOLVED,
            principal_user.id,
            "AV vendor replaced the HDMI adapter and checked the projector lamp.",
            False,
        ),
        (
            parent_khan_user.id,
            ComplaintCategory.STAFF,
            "Need more frequent PTM slots for working parents in the evening.",
            ComplaintStatus.OPEN,
            None,
            None,
            False,
        ),
    ]
    for submitted_by, category, description, status, resolved_by, resolution_note, is_anonymous in complaint_rows:
        existing = await first_or_none(
            db,
            select(Complaint).where(
                Complaint.school_id == school.id,
                Complaint.description == description,
            ),
        )
        if not existing:
            db.add(
                Complaint(
                    school_id=school.id,
                    submitted_by=submitted_by,
                    category=category,
                    description=description,
                    status=status,
                    resolved_by=resolved_by,
                    resolution_note=resolution_note,
                    is_anonymous=is_anonymous,
                )
            )

    behaviour_rows = [
        (
            students[0].id,
            teacher_math.id,
            IncidentType.POSITIVE,
            "Helped a peer understand equation balancing during group work.",
            IncidentSeverity.LOW,
            today - timedelta(days=7),
        ),
        (
            students[5].id,
            teacher_science.id,
            IncidentType.NEGATIVE,
            "Missed lab safety gloves during practical and needed a reminder before continuing.",
            IncidentSeverity.MEDIUM,
            today - timedelta(days=5),
        ),
        (
            students[2].id,
            teacher_english.id,
            IncidentType.NEUTRAL,
            "Requested additional support material for grammar practice after class.",
            IncidentSeverity.LOW,
            today - timedelta(days=4),
        ),
    ]
    for student_id, teacher_id, incident_type, description, severity, incident_date in behaviour_rows:
        existing = await first_or_none(
            db,
            select(StudentBehaviourLog).where(
                StudentBehaviourLog.student_id == student_id,
                StudentBehaviourLog.incident_date == incident_date,
                StudentBehaviourLog.description == description,
            ),
        )
        if not existing:
            db.add(
                StudentBehaviourLog(
                    student_id=student_id,
                    teacher_id=teacher_id,
                    incident_type=incident_type,
                    description=description,
                    severity=severity,
                    incident_date=incident_date,
                    academic_year_id=year.id,
                    school_id=school.id,
                )
            )

    for teacher in [teacher_math, teacher_science, teacher_english]:
        for leave_type, total, used in [
            (LeaveType.CASUAL, Decimal("12.00"), Decimal("2.00")),
            (LeaveType.SICK, Decimal("8.00"), Decimal("1.00")),
        ]:
            existing = await first_or_none(
                db,
                select(LeaveBalance).where(
                    LeaveBalance.teacher_id == teacher.id,
                    LeaveBalance.academic_year_id == year.id,
                    LeaveBalance.leave_type == leave_type,
                ),
            )
            if not existing:
                db.add(
                    LeaveBalance(
                        teacher_id=teacher.id,
                        academic_year_id=year.id,
                        leave_type=leave_type,
                        total_days=total,
                        used_days=used,
                        school_id=school.id,
                    )
                )

    teacher_leave_rows = [
        (
            teacher_english.id,
            LeaveType.CASUAL,
            today,
            today + timedelta(days=1),
            "Family function out of town",
            LeaveStatus.APPROVED,
            principal_user.id,
            "Approved with class coverage adjustment.",
        ),
        (
            teacher_math.id,
            LeaveType.SICK,
            today + timedelta(days=5),
            today + timedelta(days=5),
            "Mild viral fever",
            LeaveStatus.PENDING,
            None,
            None,
        ),
        (
            teacher_science.id,
            LeaveType.CASUAL,
            today - timedelta(days=10),
            today - timedelta(days=9),
            "Personal travel",
            LeaveStatus.REJECTED,
            principal_user.id,
            "Exam schedule preparation week.",
        ),
    ]
    for (
        teacher_id,
        leave_type,
        from_date_value,
        to_date_value,
        reason,
        leave_status,
        approved_by,
        remarks,
    ) in teacher_leave_rows:
        leave = await first_or_none(
            db,
            select(TeacherLeave).where(
                TeacherLeave.teacher_id == teacher_id,
                TeacherLeave.from_date == from_date_value,
                TeacherLeave.to_date == to_date_value,
                TeacherLeave.reason == reason,
            ),
        )
        if not leave:
            db.add(
                TeacherLeave(
                    teacher_id=teacher_id,
                    leave_type=leave_type,
                    from_date=from_date_value,
                    to_date=to_date_value,
                    reason=reason,
                    status=leave_status,
                    approved_by=approved_by,
                    remarks=remarks,
                    academic_year_id=year.id,
                    school_id=school.id,
                )
            )

    album = await first_or_none(
        db,
        select(GalleryAlbum).where(
            GalleryAlbum.school_id == school.id,
            GalleryAlbum.event_name == "Annual Science Exhibition 2025",
        ),
    )
    if not album:
        album = GalleryAlbum(
            event_name="Annual Science Exhibition 2025",
            event_date=date(2025, 12, 12),
            description="Student-led exhibition with renewable energy and robotics models.",
            cover_photo_key="demo/gallery/science-exhibition-cover.jpg",
            created_by=teacher_science_user.id,
            school_id=school.id,
            academic_year_id=year.id,
        )
        db.add(album)
        await db.flush()

    for idx, caption in enumerate(
        [
            "Class 10 students presenting the solar irrigation prototype.",
            "Robotics team explaining obstacle detection.",
        ],
        start=1,
    ):
        existing = await first_or_none(
            db,
            select(GalleryPhoto).where(
                GalleryPhoto.album_id == album.id,
                GalleryPhoto.caption == caption,
            ),
        )
        if not existing:
            db.add(
                GalleryPhoto(
                    album_id=album.id,
                    photo_key=f"demo/gallery/science-exhibition-{idx}.jpg",
                    caption=caption,
                    uploaded_by=teacher_science_user.id,
                    is_featured=(idx == 1),
                    school_id=school.id,
                )
            )

    document_rows = [
        (
            students[3],
            DocumentType.REPORT_CARD,
            f"demo/documents/{students[3].admission_number.lower()}-report-card.pdf",
            DocumentStatus.READY,
            datetime.now(timezone.utc) - timedelta(days=3),
        ),
        (
            students[4],
            DocumentType.REPORT_CARD,
            f"demo/documents/{students[4].admission_number.lower()}-report-card.pdf",
            DocumentStatus.READY,
            datetime.now(timezone.utc) - timedelta(days=4),
        ),
        (
            students[1],
            DocumentType.BONAFIDE,
            None,
            DocumentStatus.PROCESSING,
            None,
        ),
        (
            students[2],
            DocumentType.ID_CARD,
            None,
            DocumentStatus.PENDING,
            None,
        ),
    ]
    for student, doc_type, file_key, status, generated_at in document_rows:
        existing = await first_or_none(
            db,
            select(Document).where(
                Document.student_id == student.id,
                Document.document_type == doc_type,
                Document.academic_year_id == year.id,
            ),
        )
        if not existing:
            db.add(
                Document(
                    student_id=student.id,
                    document_type=doc_type,
                    file_key=file_key,
                    status=status,
                    generated_at=generated_at,
                    academic_year_id=year.id,
                    school_id=school.id,
                )
            )

    conversation = await first_or_none(
        db,
        select(Conversation).where(
            Conversation.school_id == school.id,
            Conversation.name == "Class 10B Science Group",
        ),
    )
    if not conversation:
        conversation = Conversation(
            type=ConversationType.GROUP,
            name="Class 10B Science Group",
            standard_id=class10.id,
            created_by=teacher_science_user.id,
            academic_year_id=year.id,
            school_id=school.id,
        )
        db.add(conversation)
        await db.flush()

    participant_ids = [teacher_science_user.id, student_users[3].id, student_users[4].id, student_users[5].id]
    for user_id in participant_ids:
        existing = await first_or_none(
            db,
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation.id,
                ConversationParticipant.user_id == user_id,
            ),
        )
        if not existing:
            db.add(
                ConversationParticipant(
                    conversation_id=conversation.id,
                    user_id=user_id,
                    is_admin=(user_id == teacher_science_user.id),
                )
            )

    message_payloads = [
        (teacher_science_user.id, "Please submit your science exhibition model abstract by 4 PM today."),
        (student_users[4].id, "Ma'am, we have uploaded the final version to the drive."),
        (teacher_science_user.id, "Received. I will review and share feedback before assembly."),
    ]
    created_messages: list[Message] = []
    for sender_id, content in message_payloads:
        existing = await first_or_none(
            db,
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.sender_id == sender_id,
                Message.content == content,
            ),
        )
        if existing:
            created_messages.append(existing)
            continue
        msg = Message(
            conversation_id=conversation.id,
            sender_id=sender_id,
            content=content,
            message_type=MessageType.TEXT,
            school_id=school.id,
        )
        db.add(msg)
        await db.flush()
        created_messages.append(msg)

    if created_messages:
        last_message = created_messages[-1]
        for user_id in [teacher_science_user.id, student_users[4].id]:
            existing = await first_or_none(
                db,
                select(MessageRead).where(
                    MessageRead.message_id == last_message.id,
                    MessageRead.user_id == user_id,
                ),
            )
            if not existing:
                db.add(MessageRead(message_id=last_message.id, user_id=user_id))

    parent_teacher_conversation = await first_or_none(
        db,
        select(Conversation).where(
            Conversation.school_id == school.id,
            Conversation.type == ConversationType.ONE_TO_ONE,
            Conversation.name == "Parent-Teacher: Meera Rao & Ananya Sharma",
        ),
    )
    if not parent_teacher_conversation:
        parent_teacher_conversation = Conversation(
            type=ConversationType.ONE_TO_ONE,
            name="Parent-Teacher: Meera Rao & Ananya Sharma",
            standard_id=class8.id,
            created_by=teacher_math_user.id,
            academic_year_id=year.id,
            school_id=school.id,
        )
        db.add(parent_teacher_conversation)
        await db.flush()

    for user_id in [teacher_math_user.id, parent_rao_user.id]:
        participant = await first_or_none(
            db,
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == parent_teacher_conversation.id,
                ConversationParticipant.user_id == user_id,
            ),
        )
        if not participant:
            db.add(
                ConversationParticipant(
                    conversation_id=parent_teacher_conversation.id,
                    user_id=user_id,
                    is_admin=(user_id == teacher_math_user.id),
                )
            )

    direct_messages = [
        (
            teacher_math_user.id,
            "Aarav is improving well in algebra. Please encourage daily revision for 20 minutes.",
        ),
        (
            parent_rao_user.id,
            "Thank you ma'am, we have started a daily practice schedule at home.",
        ),
    ]
    for sender_id, content in direct_messages:
        existing = await first_or_none(
            db,
            select(Message).where(
                Message.conversation_id == parent_teacher_conversation.id,
                Message.sender_id == sender_id,
                Message.content == content,
            ),
        )
        if not existing:
            db.add(
                Message(
                    conversation_id=parent_teacher_conversation.id,
                    sender_id=sender_id,
                    content=content,
                    message_type=MessageType.TEXT,
                    school_id=school.id,
                )
            )

    notifications = [
        (student_users[0].id, "Assignment posted", "Your mathematics worksheet is due in 2 days.", NotificationType.ASSIGNMENT, NotificationPriority.HIGH),
        (student_users[3].id, "Midterm result published", "Your Midterm Examination result is available now.", NotificationType.RESULT, NotificationPriority.HIGH),
        (parent_rao_user.id, "Attendance update", "Aarav marked present in mathematics today.", NotificationType.ATTENDANCE, NotificationPriority.MEDIUM),
        (parent_khan_user.id, "Fee reminder", "One fee component is pending for this quarter.", NotificationType.FEE, NotificationPriority.MEDIUM),
        (teacher_science_user.id, "Complaint resolved", "Projector issue in Class 10B has been resolved.", NotificationType.SYSTEM, NotificationPriority.LOW),
        (principal_user.id, "Teacher leave request", "A pending sick leave request needs your action.", NotificationType.LEAVE, NotificationPriority.MEDIUM),
    ]
    for user_id, title, body, notif_type, priority in notifications:
        existing = await first_or_none(
            db,
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.title == title,
                Notification.body == body,
            ),
        )
        if not existing:
            db.add(
                Notification(
                    user_id=user_id,
                    title=title,
                    body=body,
                    type=notif_type,
                    priority=priority,
                    is_read=False,
                )
            )

    await db.commit()

    return {
        "school_name": school.name,
        "school_id": str(school.id),
        "academic_year_id": str(year.id),
        "principal_email": principal_user.email or "",
        "principal_password": DEMO_PASSWORD,
        "teacher_email": teacher_science_user.email or "",
        "parent_email": parent_rao_user.email or "",
        "student_email": student_users[0].email or "",
    }


async def main() -> None:
    print("SMS Backend — Seeding Demo Data\n")
    async with AsyncSessionLocal() as db:
        summary = await seed_demo(db)

    print("✅ Demo dataset ready\n")
    print(f"School: {summary['school_name']}")
    print(f"School ID: {summary['school_id']}")
    print(f"Academic Year ID: {summary['academic_year_id']}")
    print(f"Principal login: {summary['principal_email']} / {summary['principal_password']}")
    print(f"Teacher login: {summary['teacher_email']} / {summary['principal_password']}")
    print(f"Parent login: {summary['parent_email']} / {summary['principal_password']}")
    print(f"Student login: {summary['student_email']} / {summary['principal_password']}")


if __name__ == "__main__":
    asyncio.run(main())
