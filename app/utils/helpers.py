import uuid
import random
import string
from datetime import date, timedelta
from typing import Optional, TypeVar, Any

T = TypeVar("T")


def generate_otp(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))


def generate_uuid() -> uuid.UUID:
    return uuid.uuid4()


def generate_unique_code(prefix: str = "", length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    code = ''.join(random.choices(chars, k=length))
    return f"{prefix}{code}" if prefix else code


def calculate_date_range(from_date: date, to_date: date) -> int:
    return (to_date - from_date).days + 1


def get_current_month_date_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def paginate(query_result: list[T], page: int, page_size: int) -> dict[str, Any]:
    total = len(query_result)
    start = (page - 1) * page_size
    end = start + page_size
    items = query_result[start:end]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0:
        return default
    return numerator / denominator


def format_academic_year(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def mask_email(email: str) -> str:
    parts = email.split('@')
    if len(parts) != 2:
        return email
    local = parts[0]
    domain = parts[1]
    if len(local) <= 2:
        masked = local[0] + '*' * (len(local) - 1)
    else:
        masked = local[0] + '*' * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


def mask_phone(phone: str) -> str:
    if len(phone) < 4:
        return phone
    return '*' * (len(phone) - 4) + phone[-4:]