# app/utils/enums.py
from enum import Enum


class RoleEnum(str, Enum):
    SUPERADMIN = "SUPERADMIN"
    TRUSTEE = "TRUSTEE"
    PRINCIPAL = "PRINCIPAL"
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"
    PARENT = "PARENT"


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"


class LeaveType(str, Enum):
    CASUAL = "CASUAL"
    SICK = "SICK"
    EARNED = "EARNED"


class LeaveStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FeeCategory(str, Enum):
    TUITION = "TUITION"
    TRANSPORT = "TRANSPORT"
    LIBRARY = "LIBRARY"
    LABORATORY = "LABORATORY"
    SPORTS = "SPORTS"
    EXAMINATION = "EXAMINATION"
    MISCELLANEOUS = "MISCELLANEOUS"


class FeeStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    OVERDUE = "OVERDUE"


class PaymentMode(str, Enum):
    CASH = "CASH"
    CHEQUE = "CHEQUE"
    ONLINE = "ONLINE"
    UPI = "UPI"
    BANK_TRANSFER = "BANK_TRANSFER"
    CARD = "CARD"


class ExamType(str, Enum):
    UNIT = "UNIT"
    MIDTERM = "MIDTERM"
    FINAL = "FINAL"
    QUARTERLY = "QUARTERLY"
    HALF_YEARLY = "HALF_YEARLY"
    ANNUAL = "ANNUAL"


class PromotionStatus(str, Enum):
    PROMOTED = "PROMOTED"
    HELD_BACK = "HELD_BACK"


# Phase 7: decision made during the promotion workflow
class PromotionDecision(str, Enum):
    PROMOTE = "PROMOTE"       # advance to next class in new year
    REPEAT = "REPEAT"         # repeat same class in new year
    GRADUATE = "GRADUATE"     # completed final class — no further mapping
    SKIP = "SKIP"             # exclude from this promotion run (handle manually)


class DocumentType(str, Enum):
    ID_CARD = "ID_CARD"
    BONAFIDE = "BONAFIDE"
    LEAVING_CERT = "LEAVING_CERT"
    REPORT_CARD = "REPORT_CARD"


class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


# ── Phase 6: Admission Type ───────────────────────────────────────────────────
class AdmissionType(str, Enum):
    NEW_ADMISSION = "NEW_ADMISSION"   # standard start-of-year admission
    MID_YEAR = "MID_YEAR"             # joining after year has started
    TRANSFER_IN = "TRANSFER_IN"       # transferred from another school
    READMISSION = "READMISSION"       # previously LEFT/TRANSFERRED, re-joining


# ── Phase 6 & 7: Enrollment (StudentYearMapping) lifecycle ───────────────────
class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"           # currently enrolled in this year
    HOLD = "HOLD"               # temporarily on hold
    COMPLETED = "COMPLETED"     # year finished, promotion decision pending
    LEFT = "LEFT"               # left school mid-year
    TRANSFERRED = "TRANSFERRED" # transferred to another school mid-year
    # Phase 7 terminal states — set when new year mapping is created
    PROMOTED = "PROMOTED"       # promoted to next class (old-year mapping closed)
    REPEATED = "REPEATED"       # repeating same class (old-year mapping closed)


class ConversationType(str, Enum):
    ONE_TO_ONE = "ONE_TO_ONE"
    GROUP = "GROUP"


class UserStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    INACTIVE = "INACTIVE"
    ON_HOLD = "ON_HOLD"
    # Backward-compat aliases used in older code paths
    HOLD = "HOLD"
    DISABLED = "DISABLED"


class RegistrationSource(str, Enum):
    SELF_REGISTERED = "SELF_REGISTERED"
    ADMIN_CREATED = "ADMIN_CREATED"


class ApprovalAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    HOLD = "HOLD"


class ApprovalDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ON_HOLD = "ON_HOLD"


class AuditAction(str, Enum):
    USER_REGISTERED = "USER_REGISTERED"
    USER_APPROVED = "USER_APPROVED"
    USER_REJECTED = "USER_REJECTED"
    USER_HELD = "USER_HELD"
    USER_ACTIVATED = "USER_ACTIVATED"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    ADMIN_LOGIN = "ADMIN_LOGIN"
    ADMIN_CREATED_USER = "ADMIN_CREATED_USER"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"
    STUDENT_ENROLLED = "STUDENT_ENROLLED"
    STUDENT_EXITED = "STUDENT_EXITED"
    STUDENT_PROMOTED = "STUDENT_PROMOTED"
    STUDENT_REPEATED = "STUDENT_REPEATED"
    STUDENT_GRADUATED = "STUDENT_GRADUATED"
    STUDENT_REENROLLED = "STUDENT_REENROLLED"
    TEACHER_ASSIGNMENT_COPIED = "TEACHER_ASSIGNMENT_COPIED"


class IdentifierType(str, Enum):
    ADMISSION_NUMBER = "ADMISSION_NUMBER"
    EMPLOYEE_ID = "EMPLOYEE_ID"
    PARENT_CODE = "PARENT_CODE"


class RelationType(str, Enum):
    FATHER = "FATHER"
    MOTHER = "MOTHER"
    GUARDIAN = "GUARDIAN"
    SIBLING = "SIBLING"
    OTHER = "OTHER"