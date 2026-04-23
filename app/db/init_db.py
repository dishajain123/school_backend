from app.db.session import engine
from app.db.base import Base
from app.core.logging import get_logger
from sqlalchemy import text

logger = get_logger(__name__)


async def init_db() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Runtime-safe patch for existing installations:
            # add lecture_number and new unique key for lecture-wise attendance.
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS attendance
                    ADD COLUMN IF NOT EXISTS section VARCHAR(10) NOT NULL DEFAULT ''
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS attendance
                    ADD COLUMN IF NOT EXISTS lecture_number INTEGER NOT NULL DEFAULT 1
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'uq_attendance_student_subject_date'
                        ) THEN
                            ALTER TABLE attendance
                            DROP CONSTRAINT uq_attendance_student_subject_date;
                        END IF;
                    END $$;
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'uq_attendance_student_subject_date_lecture'
                        ) THEN
                            ALTER TABLE attendance
                            ADD CONSTRAINT uq_attendance_student_subject_date_lecture
                            UNIQUE (student_id, subject_id, date, lecture_number);
                        END IF;
                    END $$;
                    """
                )
            )
            # Runtime-safe patch for submission review workflow.
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS submissions
                    ADD COLUMN IF NOT EXISTS is_approved BOOLEAN NOT NULL DEFAULT FALSE
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS submissions
                    ADD COLUMN IF NOT EXISTS approved_by UUID NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS submissions
                    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ NULL
                    """
                )
            )
            # Runtime-safe patch for homework attachments and file responses.
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS homework
                    ADD COLUMN IF NOT EXISTS file_key TEXT NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS homework_submissions
                    ADD COLUMN IF NOT EXISTS file_key TEXT NULL
                    """
                )
            )
        logger.info("Database tables created/verified successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
