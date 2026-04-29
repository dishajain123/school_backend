from enum import Enum


class RoleEnum(str, Enum):
    SUPERADMIN = "SUPERADMIN"
    PRINCIPAL = "PRINCIPAL"
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"
    PARENT = "PARENT"
    TRUSTEE = "TRUSTEE"
    STAFF_ADMIN = "STAFF_ADMIN"


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
    STUDENT_SECTION_TRANSFERRED = "STUDENT_SECTION_TRANSFERRED"   # Phase 14/15: in-year transfer
    STUDENT_CLASS_TRANSFERRED = "STUDENT_CLASS_TRANSFERRED"       # Phase 14/15: in-year class change
    TEACHER_ASSIGNMENT_CREATED = "TEACHER_ASSIGNMENT_CREATED"     # Phase 14/15
    TEACHER_ASSIGNMENT_UPDATED = "TEACHER_ASSIGNMENT_UPDATED"     # Phase 14/15
    TEACHER_ASSIGNMENT_DELETED = "TEACHER_ASSIGNMENT_DELETED"     # Phase 14/15
    TEACHER_ASSIGNMENT_COPIED = "TEACHER_ASSIGNMENT_COPIED"
    DOCUMENT_APPROVED = "DOCUMENT_APPROVED"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"
    ANNOUNCEMENT_CREATED = "ANNOUNCEMENT_CREATED"
    ANNOUNCEMENT_UPDATED = "ANNOUNCEMENT_UPDATED"
    ANNOUNCEMENT_DELETED = "ANNOUNCEMENT_DELETED"


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


class PaymentMode(str, Enum):
    CASH = "CASH"
    CHEQUE = "CHEQUE"
    ONLINE = "ONLINE"
    DD = "DD"
    NEFT = "NEFT"
    RTGS = "RTGS"
    UPI = "UPI"
    OTHER = "OTHER"


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


class ExamType(str, Enum):
    UNIT_TEST = "UNIT_TEST"
    MID_TERM = "MID_TERM"
    FINAL = "FINAL"
    MOCK = "MOCK"
    QUARTERLY = "QUARTERLY"
    HALF_YEARLY = "HALF_YEARLY"
    ANNUAL = "ANNUAL"


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"
    EXCUSED = "EXCUSED"
    HALF_DAY = "HALF_DAY"


class LeaveStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class LeaveType(str, Enum):
    SICK = "SICK"
    CASUAL = "CASUAL"
    EARNED = "EARNED"
    UNPAID = "UNPAID"
    MATERNITY = "MATERNITY"
    PATERNITY = "PATERNITY"
    OTHER = "OTHER"


class DocumentType(str, Enum):
    # Newer document types used by admin/mobile flows
    ID_CARD = "ID_CARD"
    BONAFIDE = "BONAFIDE"
    LEAVING_CERT = "LEAVING_CERT"
    REPORT_CARD = "REPORT_CARD"

    # Legacy types kept for backward compatibility with older records
    ID_PROOF = "ID_PROOF"
    ADDRESS_PROOF = "ADDRESS_PROOF"
    ACADEMIC_CERTIFICATE = "ACADEMIC_CERTIFICATE"
    TRANSFER_CERTIFICATE = "TRANSFER_CERTIFICATE"
    MEDICAL = "MEDICAL"
    OTHER = "OTHER"


class DocumentStatus(str, Enum):
    # Current workflow statuses (used by services and admin UI)
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"

    # Legacy statuses kept for compatibility with historical rows
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AnnouncementType(str, Enum):
    GENERAL = "GENERAL"
    URGENT = "URGENT"
    FEE = "FEE"
    EXAM = "EXAM"
    EVENT = "EVENT"
    HOLIDAY = "HOLIDAY"


class ComplaintCategory(str, Enum):
    ACADEMIC = "ACADEMIC"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    STAFF = "STAFF"
    ADMIN = "ADMIN"
    OTHER = "OTHER"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class FeedbackType(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


class MessageType(str, Enum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    FILE = "FILE"
    SYSTEM = "SYSTEM"


class NotificationType(str, Enum):
    ASSIGNMENT = "ASSIGNMENT"
    RESULT = "RESULT"
    ATTENDANCE = "ATTENDANCE"
    FEE = "FEE"
    SYSTEM = "SYSTEM"
    LEAVE = "LEAVE"
    ANNOUNCEMENT = "ANNOUNCEMENT"


class NotificationPriority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SubscriptionPlan(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"
    ENTERPRISE = "ENTERPRISE"


class IncidentType(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ── Phase 6: Admission Type ───────────────────────────────────────────────────
class AdmissionType(str, Enum):
    NEW_ADMISSION = "NEW_ADMISSION"
    MID_YEAR = "MID_YEAR"
    TRANSFER_IN = "TRANSFER_IN"
    READMISSION = "READMISSION"


# ── Phase 6 & 7: Enrollment (StudentYearMapping) lifecycle ───────────────────
class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HOLD = "HOLD"
    COMPLETED = "COMPLETED"
    LEFT = "LEFT"
    TRANSFERRED = "TRANSFERRED"
    PROMOTED = "PROMOTED"
    REPEATED = "REPEATED"
    GRADUATED = "GRADUATED"


class PromotionDecision(str, Enum):
    PROMOTE = "PROMOTE"
    REPEAT = "REPEAT"
    GRADUATE = "GRADUATE"
    SKIP = "SKIP"


class PromotionStatus(str, Enum):
    PROMOTED = "PROMOTED"
    NOT_PROMOTED = "NOT_PROMOTED"
    PENDING = "PENDING"


class ConversationType(str, Enum):
    ONE_TO_ONE = "ONE_TO_ONE"
    GROUP = "GROUP"
