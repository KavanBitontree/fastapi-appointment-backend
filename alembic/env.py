from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool

from core.config import settings
from core.database import Base
from alembic import context
from models.user import User
from models.doctor import Doctor
from models.patient import Patient
from models.device import Device
from models.refresh_token import RefreshToken



config = context.config
config.set_main_option("sqlalchemy.url", settings.NEON_DB_URL)

fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(
        url=settings.NEON_DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"sslmode": "require"},
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
