from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from shared.config import settings
from shared.models import Base  # noqa: F401 — registers metadata

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # All service entrypoints run `alembic upgrade head` concurrently on
        # `compose up`; serialize them so DDL (e.g. CREATE TABLE) doesn't
        # race. Session-level lock — released when this connection closes;
        # losers block, then re-read alembic_version and no-op.
        connection.exec_driver_sql("SELECT pg_advisory_lock(919117)")
        # exec_driver_sql opened an implicit transaction; commit it so
        # alembic's begin_transaction() OWNS the migration transaction —
        # otherwise the DDL and version bump silently ROLL BACK when the
        # connection closes. (pg_advisory_lock is session-scoped: it
        # survives this commit and releases when the connection closes.)
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
