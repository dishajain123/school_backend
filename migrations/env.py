import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.engine.url import make_url

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.base import Base
from app.core.config import settings
from app.models import academic_year  # noqa: F401
from app.models import academic_structure_copy  # noqa: F401
from app.models import announcement  # noqa: F401
from app.models import assignment  # noqa: F401
from app.models import attendance  # noqa: F401
from app.models import complaint  # noqa: F401
from app.models import conversation  # noqa: F401
from app.models import document  # noqa: F401
from app.models import exam  # noqa: F401
from app.models import exam_schedule  # noqa: F401
from app.models import fee  # noqa: F401
from app.models import feedback  # noqa: F401
from app.models import gallery  # noqa: F401
from app.models import homework  # noqa: F401
from app.models import jti_blocklist  # noqa: F401
from app.models import leave_balance  # noqa: F401
from app.models import masters  # noqa: F401
from app.models import message  # noqa: F401
from app.models import notification  # noqa: F401
from app.models import otp_store  # noqa: F401
from app.models import parent  # noqa: F401
from app.models import payment  # noqa: F401
from app.models import permission  # noqa: F401
from app.models import result  # noqa: F401
from app.models import role  # noqa: F401
from app.models import role_permission  # noqa: F401
from app.models import school  # noqa: F401
from app.models import school_settings  # noqa: F401
from app.models import section  # noqa: F401
from app.models import student  # noqa: F401
from app.models import student_academic_history  # noqa: F401
from app.models import student_behaviour_log  # noqa: F401
from app.models import student_diary  # noqa: F401
from app.models import submission  # noqa: F401
from app.models import teacher  # noqa: F401
from app.models import teacher_class_subject  # noqa: F401
from app.models import teacher_leave  # noqa: F401
from app.models import timetable  # noqa: F401
from app.models import user  # noqa: F401

config = context.config

ASYNC_DATABASE_URL = settings.DATABASE_URL
url = make_url(ASYNC_DATABASE_URL)
if url.drivername.endswith("+asyncpg"):
    url = url.set(drivername="postgresql+psycopg2")
SYNC_DATABASE_URL = str(url)

config.set_main_option("sqlalchemy.url", ASYNC_DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=SYNC_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
