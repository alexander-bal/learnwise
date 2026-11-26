from alembic import context
from sqlalchemy import Connection

from app.core.config import get_settings
from app.db.engine import create_sync_engine
from app.models import Base

config = context.config


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,
    )
    # Inside migrate() the caller's BEGIN IMMEDIATE transaction is reused.
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    # Alembic CLI use (e.g. autogenerate) outside the app.
    engine = create_sync_engine(get_settings().sync_database_url)
    with engine.connect() as conn:
        _run(conn)
    engine.dispose()
