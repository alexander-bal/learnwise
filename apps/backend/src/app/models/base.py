from typing import Any

from sqlalchemy import JSON, CheckConstraint, MetaData, String, text
from sqlalchemy.orm import DeclarativeBase, mapped_column

# ISO 8601 UTC with milliseconds, e.g. 2026-11-25T10:00:00.000Z (Processing Appendix: Schema).
NOW_ISO = text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: JSON, Any: JSON}


def timestamp(*, required: bool = True, default_now: bool = False) -> Any:
    return mapped_column(
        String,
        nullable=not required,
        server_default=NOW_ISO if default_now else None,
    )


def json_valid(column: str, *, nullable: bool = False) -> CheckConstraint:
    condition = f"json_valid({column})"
    if nullable:
        condition = f"{column} IS NULL OR {condition}"
    return CheckConstraint(condition, name=f"{column}_json")


def one_of(column: str, values: tuple[str, ...], *, nullable: bool = False) -> CheckConstraint:
    listed = ", ".join(f"'{v}'" for v in values)
    condition = f"{column} IN ({listed})"
    if nullable:
        condition = f"{column} IS NULL OR {condition}"
    return CheckConstraint(condition, name=f"{column}_values")
