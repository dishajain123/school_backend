import re
from typing import Optional
from fastapi import HTTPException


def validate_email(email: str) -> str:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        raise HTTPException(status_code=422, detail=f"Invalid email format: {email}")
    return email.lower().strip()


def validate_phone(phone: str) -> str:
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    if not re.match(r'^\+?[0-9]{10,15}$', cleaned):
        raise HTTPException(status_code=422, detail=f"Invalid phone number format: {phone}")
    return cleaned


def validate_password_strength(password: str) -> str:
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters long")
    if not re.search(r'[A-Z]', password):
        raise HTTPException(status_code=422, detail="Password must contain at least one uppercase letter")
    if not re.search(r'[a-z]', password):
        raise HTTPException(status_code=422, detail="Password must contain at least one lowercase letter")
    if not re.search(r'\d', password):
        raise HTTPException(status_code=422, detail="Password must contain at least one digit")
    return password


def validate_file_size(file_size: int, max_size_bytes: int) -> None:
    if file_size > max_size_bytes:
        max_mb = max_size_bytes / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"File size exceeds maximum allowed size of {max_mb:.0f}MB"
        )


def validate_mime_type(content_type: str, allowed_types: list[str]) -> None:
    if content_type not in allowed_types:
        raise HTTPException(
            status_code=415,
            detail=f"File type '{content_type}' is not allowed. Allowed types: {', '.join(allowed_types)}"
        )


def validate_otp_format(otp: str) -> str:
    if not re.match(r'^\d{6}$', otp):
        raise HTTPException(status_code=422, detail="OTP must be exactly 6 digits")
    return otp