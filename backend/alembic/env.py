"""Alembic migration environment for the ICB Platform (PostgreSQL only).

The connection URL and the target metadata both come from the application
itself, so migrations always track the running app:

  * URL      -> app.config.settings.DATABASE_URL   (never hard-coded here)
  * metadata -> app.database.Base.metadata         (importing app.database
                                                     registers every model)

All costing tables and Alembic's own version table live in the `icb_costings`
schema (the icb_app role's default search_path), so we pin version_table_schema.
"""
from logging.config import fileConfig
from pathlib import Path
import sys

from sqlalchemy import engine_from_config, pool

from alembic import context

# env.py lives at backend/alembic/env.py — put backend/ on sys.path so `app` imports.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings          # noqa: E402
import app.database                       # noqa: E402,F401  (registers all models on Base)
import app.models.mes                     # noqa: E402,F401  (registers icb_mes models on Base)
from app.database import Base             # noqa: E402

config = context.config

# Inject the real DB URL from settings (keeps secrets out of alembic.ini).
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Note: alembic_version lives in the connection's default schema, which the
# icb_app role's search_path resolves to icb_costings. We deliberately do NOT
# set version_table_schema — pinning it confuses autogenerate's self-exclusion
# (it would otherwise flag alembic_version for removal on every `alembic check`).

# Multi-schema autogenerate (WO v4.13): reflect only the relevant schemas, and
# exclude cross-schema FKs (icb_mes -> icb_costings) which are created in
# migrations rather than declared on the schema-less costing models.
_RELEVANT_SCHEMAS = {None, "icb_costings", "icb_mes"}


def _include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in _RELEVANT_SCHEMAS
    return True


def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "foreign_key_constraint":
        try:
            if obj.table.schema != obj.referred_table.schema:
                return False
        except Exception:
            pass
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_schemas=True,
        include_name=_include_name,
        include_object=_include_object,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_schemas=True,
            include_name=_include_name,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
