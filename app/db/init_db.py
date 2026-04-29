from app.db.session import engine
from app.db.base import Base
from app.core.logging import get_logger
from sqlalchemy import text

logger = get_logger(__name__)


async def init_db() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

            # ── Attendance: section + lecture_number columns ───────────────────
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

            # ── Attendance: performance indexes ───────────────────────────────
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_attendance_student_date ON attendance (student_id, date);")
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_attendance_standard_section_date ON attendance (standard_id, section, date);")
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_attendance_teacher_subject ON attendance (teacher_id, subject_id);")
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_attendance_year_standard ON attendance (academic_year_id, standard_id);")
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_attendance_date ON attendance (date);")
            )

            # ── Submission review workflow ─────────────────────────────────────
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

            # ── Homework attachments ───────────────────────────────────────────
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

            # ── Fee structures: custom_fee_head + upgraded uniqueness ──────────
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

            # ── Fee structures: installment_plan JSONB column ─────────────────
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS fee_structures
                    ADD COLUMN IF NOT EXISTS installment_plan JSONB NULL
                    """
                )
            )

            # ── FeeStatus enum: add OVERDUE value ─────────────────────────────
            await conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_enum
                            WHERE enumlabel = 'OVERDUE'
                              AND enumtypid = (
                                SELECT oid FROM pg_type WHERE typname = 'fee_status_enum'
                              )
                        ) THEN
                            ALTER TYPE fee_status_enum ADD VALUE 'OVERDUE';
                        END IF;
                    END $$;
                    """
                )
            )

            # ── PaymentMode enum: add CARD value ──────────────────────────────
            await conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_enum
                            WHERE enumlabel = 'CARD'
                              AND enumtypid = (
                                SELECT oid FROM pg_type WHERE typname = 'payment_mode_enum'
                              )
                        ) THEN
                            ALTER TYPE payment_mode_enum ADD VALUE 'CARD';
                        END IF;
                    END $$;
                    """
                )
            )

            # ── FeeLedger: new columns for installment tracking ───────────────
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS fee_ledger
                    ADD COLUMN IF NOT EXISTS installment_name VARCHAR(120) NOT NULL DEFAULT ''
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS fee_ledger
                    ADD COLUMN IF NOT EXISTS due_date DATE NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS fee_ledger
                    ADD COLUMN IF NOT EXISTS last_payment_date DATE NULL
                    """
                )
            )

            # Backfill due_date from joined fee_structure for existing rows
            await conn.execute(
                text(
                    """
                    UPDATE fee_ledger fl
                    SET due_date = fs.due_date
                    FROM fee_structures fs
                    WHERE fl.fee_structure_id = fs.id
                      AND fl.due_date IS NULL
                    """
                )
            )

            # ── FeeLedger: migrate unique constraint ──────────────────────────
            # Old constraint: (student_id, fee_structure_id)
            # New constraint: (student_id, fee_structure_id, installment_name)
            await conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'uq_fee_ledger_student_structure'
                        ) THEN
                            ALTER TABLE fee_ledger
                            DROP CONSTRAINT uq_fee_ledger_student_structure;
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
                            WHERE conname = 'uq_fee_ledger_student_structure_installment'
                        ) THEN
                            ALTER TABLE fee_ledger
                            ADD CONSTRAINT uq_fee_ledger_student_structure_installment
                            UNIQUE (student_id, fee_structure_id, installment_name);
                        END IF;
                    END $$;
                    """
                )
            )

            # ── FeeLedger: performance indexes ────────────────────────────────
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_fee_ledger_student_id ON fee_ledger (student_id);"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_fee_ledger_status ON fee_ledger (status);"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_fee_ledger_due_date ON fee_ledger (due_date);"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_fee_ledger_school_status ON fee_ledger (school_id, status);"
                )
            )

            # ── Payment: transaction_ref column ───────────────────────────────
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS payments
                    ADD COLUMN IF NOT EXISTS transaction_ref VARCHAR(255) NULL
                    """
                )
            )

            # ── Payment: performance indexes ──────────────────────────────────
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_payments_payment_date ON payments (payment_date);"
                )
            )

            # ── Phase 1 Identity/Approval: user status + registration payload ─
            await conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_type WHERE typname = 'userstatus'
                        ) THEN
                            CREATE TYPE userstatus AS ENUM (
                                'PENDING_APPROVAL',
                                'ACTIVE',
                                'REJECTED',
                                'INACTIVE',
                                'ON_HOLD',
                                'HOLD',
                                'DISABLED'
                            );
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
                            SELECT 1 FROM pg_type WHERE typname = 'registrationsource'
                        ) THEN
                            CREATE TYPE registrationsource AS ENUM (
                                'SELF_REGISTERED',
                                'ADMIN_CREATED'
                            );
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
                            FROM pg_enum
                            WHERE enumlabel = 'ON_HOLD'
                              AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'userstatus')
                        ) THEN
                            ALTER TYPE userstatus ADD VALUE 'ON_HOLD';
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
                            FROM pg_enum
                            WHERE enumlabel = 'HOLD'
                              AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'userstatus')
                        ) THEN
                            ALTER TYPE userstatus ADD VALUE 'HOLD';
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
                            FROM pg_enum
                            WHERE enumlabel = 'DISABLED'
                              AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'userstatus')
                        ) THEN
                            ALTER TYPE userstatus ADD VALUE 'DISABLED';
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
                            FROM pg_enum
                            WHERE enumlabel = 'SELF_REGISTERED'
                              AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'registrationsource')
                        ) THEN
                            ALTER TYPE registrationsource ADD VALUE 'SELF_REGISTERED';
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
                            FROM pg_enum
                            WHERE enumlabel = 'ADMIN_CREATED'
                              AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'registrationsource')
                        ) THEN
                            ALTER TYPE registrationsource ADD VALUE 'ADMIN_CREATED';
                        END IF;
                    END $$;
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS users
                    ADD COLUMN IF NOT EXISTS status userstatus NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS users
                    ADD COLUMN IF NOT EXISTS registration_source registrationsource NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS users
                    ADD COLUMN IF NOT EXISTS rejection_reason VARCHAR(500) NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS users
                    ADD COLUMN IF NOT EXISTS hold_reason VARCHAR(500) NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS users
                    ADD COLUMN IF NOT EXISTS submitted_data JSONB NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS users
                    ADD COLUMN IF NOT EXISTS approved_by_id UUID NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS users
                    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ NULL
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
                            FROM pg_enum
                            WHERE enumlabel = 'INACTIVE'
                              AND enumtypid = (
                                SELECT oid FROM pg_type WHERE typname = 'userstatus'
                              )
                        ) THEN
                            ALTER TYPE userstatus ADD VALUE 'INACTIVE';
                        END IF;
                    END $$;
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    UPDATE users
                    SET status = CASE
                        WHEN is_active IS TRUE THEN 'ACTIVE'::userstatus
                        ELSE 'INACTIVE'::userstatus
                    END
                    WHERE status IS NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    UPDATE users
                    SET registration_source = 'SELF_REGISTERED'::registrationsource
                    WHERE registration_source IS NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS users
                    ALTER COLUMN status SET DEFAULT 'PENDING_APPROVAL'::userstatus
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS users
                    ALTER COLUMN registration_source SET DEFAULT 'SELF_REGISTERED'::registrationsource
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS users
                    ALTER COLUMN status SET NOT NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS users
                    ALTER COLUMN registration_source SET NOT NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_users_status
                    ON users (status)
                    """
                )
            )

            # ── Parent identifier uniqueness within school when present ───────
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS parents
                    ADD COLUMN IF NOT EXISTS parent_code VARCHAR(50) NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_parent_code_school
                    ON parents (school_id, parent_code)
                    WHERE parent_code IS NOT NULL
                    """
                )
            )

            # ── Approval audit log indexes ────────────────────────────────────
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_user_approval_audits_user_acted_at ON user_approval_audits (user_id, acted_at DESC);"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_user_approval_audits_actor_acted_at ON user_approval_audits (acted_by_id, acted_at DESC);"
                )
            )

            # ── Phase 3 Academic Structure hardening ────────────────────────
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS subjects
                    ALTER COLUMN standard_id DROP NOT NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_academic_year_one_active_per_school
                    ON academic_years (school_id)
                    WHERE is_active IS TRUE
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_section_school_std_year_name_idx
                    ON sections (school_id, standard_id, academic_year_id, name)
                    """
                )
            )

            # ── Enrollment mapping compatibility (admission_type) ───────────
            await conn.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS student_year_mappings
                    ADD COLUMN IF NOT EXISTS admission_type VARCHAR(30) NULL
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    UPDATE student_year_mappings
                    SET admission_type = 'NEW_ADMISSION'
                    WHERE admission_type IS NULL
                    """
                )
            )

            # ── AnnouncementType enum sync ──────────────────────────────────
            await conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_type WHERE typname = 'announcement_type_enum'
                        ) THEN
                            CREATE TYPE announcement_type_enum AS ENUM (
                                'GENERAL',
                                'URGENT',
                                'FEE',
                                'EXAM',
                                'EVENT',
                                'HOLIDAY'
                            );
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
                            SELECT 1 FROM pg_enum
                            WHERE enumlabel = 'GENERAL'
                              AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'announcement_type_enum')
                        ) THEN
                            ALTER TYPE announcement_type_enum ADD VALUE 'GENERAL';
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
                            SELECT 1 FROM pg_enum
                            WHERE enumlabel = 'URGENT'
                              AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'announcement_type_enum')
                        ) THEN
                            ALTER TYPE announcement_type_enum ADD VALUE 'URGENT';
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
                            SELECT 1 FROM pg_enum
                            WHERE enumlabel = 'FEE'
                              AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'announcement_type_enum')
                        ) THEN
                            ALTER TYPE announcement_type_enum ADD VALUE 'FEE';
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
                            SELECT 1 FROM pg_enum
                            WHERE enumlabel = 'EXAM'
                              AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'announcement_type_enum')
                        ) THEN
                            ALTER TYPE announcement_type_enum ADD VALUE 'EXAM';
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
                            SELECT 1 FROM pg_enum
                            WHERE enumlabel = 'EVENT'
                              AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'announcement_type_enum')
                        ) THEN
                            ALTER TYPE announcement_type_enum ADD VALUE 'EVENT';
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
                            SELECT 1 FROM pg_enum
                            WHERE enumlabel = 'HOLIDAY'
                              AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'announcement_type_enum')
                        ) THEN
                            ALTER TYPE announcement_type_enum ADD VALUE 'HOLIDAY';
                        END IF;
                    END $$;
                    """
                )
            )

        logger.info("Database tables created/verified successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
