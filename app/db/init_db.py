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
            # Runtime-safe patch for customizable fee heads and upgraded uniqueness.
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS fee_structures
                    ADD COLUMN IF NOT EXISTS custom_fee_head VARCHAR(120)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    UPDATE fee_structures
                    SET custom_fee_head = ''
                    WHERE custom_fee_head IS NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS fee_structures
                    ALTER COLUMN custom_fee_head SET DEFAULT ''
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS fee_structures
                    ALTER COLUMN custom_fee_head SET NOT NULL
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
                            WHERE conname = 'uq_fee_structure_category_standard_year_school'
                        ) THEN
                            ALTER TABLE fee_structures
                            DROP CONSTRAINT uq_fee_structure_category_standard_year_school;
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
                            WHERE conname = 'uq_fee_structure_category_standard_year_school'
                        ) THEN
                            ALTER TABLE fee_structures
                            ADD CONSTRAINT uq_fee_structure_category_standard_year_school
                            UNIQUE (school_id, standard_id, academic_year_id, fee_category, custom_fee_head);
                        END IF;
                    END $$;
                    """
                )
            )
        logger.info("Database tables created/verified successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
