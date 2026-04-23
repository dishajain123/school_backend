ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"
RESET_TOKEN_TYPE = "password_reset"

OTP_LENGTH = 6
OTP_EXPIRE_MINUTES = 10
RESET_TOKEN_EXPIRE_MINUTES = 5

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

ALLOWED_IMAGE_TYPES = [
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/heic",
    "image/heif",
]
ALLOWED_DOCUMENT_TYPES = ["application/pdf", "application/msword",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
ALLOWED_FILE_TYPES = ALLOWED_IMAGE_TYPES + ALLOWED_DOCUMENT_TYPES

PRESIGNED_URL_EXPIRY = 3600

MIN_ATTENDANCE_PERCENTAGE = 75.0

BCRYPT_ROUNDS = 12

MINIO_BUCKETS = [
    "assignments",
    "submissions",
    "homework",
    "homework-submissions",
    "timetables",
    "documents",
    "profiles",
    "receipts",
    "gallery",
    "chat-files",
]
