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


class ComplaintCategory(str, Enum):
    ACADEMIC = "ACADEMIC"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    STAFF = "STAFF"
    OTHER = "OTHER"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class IncidentType(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MessageType(str, Enum):
    TEXT = "TEXT"
    FILE = "FILE"
    IMAGE = "IMAGE"


class NotificationType(str, Enum):
    ATTENDANCE = "ATTENDANCE"
    ASSIGNMENT = "ASSIGNMENT"
    SUBMISSION = "SUBMISSION"
    HOMEWORK = "HOMEWORK"
    DIARY = "DIARY"
    EXAM = "EXAM"
    FEE = "FEE"
    RESULT = "RESULT"
    ANNOUNCEMENT = "ANNOUNCEMENT"
    LEAVE = "LEAVE"
    COMPLAINT = "COMPLAINT"
    BEHAVIOUR = "BEHAVIOUR"
    CHAT = "CHAT"
    SYSTEM = "SYSTEM"


class NotificationPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SubscriptionPlan(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class RelationType(str, Enum):
    MOTHER = "MOTHER"
    FATHER = "FATHER"
    GUARDIAN = "GUARDIAN"


class AnnouncementType(str, Enum):
    EXAM = "EXAM"
    EVENT = "EVENT"
    HOLIDAY = "HOLIDAY"
    GENERAL = "GENERAL"


class FeedbackType(str, Enum):
    GENERAL = "GENERAL"
    ACADEMIC = "ACADEMIC"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    STAFF = "STAFF"


class ConversationType(str, Enum):
    ONE_TO_ONE = "ONE_TO_ONE"
    GROUP = "GROUP"