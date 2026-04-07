from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def today_in_app_timezone() -> date:
    """Return today's date in configured app timezone."""
    return datetime.now(ZoneInfo(settings.APP_TIMEZONE)).date()
