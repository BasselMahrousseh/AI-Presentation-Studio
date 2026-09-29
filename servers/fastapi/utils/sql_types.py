"""Portable ORM types; Oracle storage is explicit rather than dialect fallback.

Existing SQLite/PostgreSQL/MySQL storage representations stay unchanged. Oracle
uses RAW UUIDs, JSON-validated CLOBs (constraints in the frozen baseline), and
timezone-preserving timestamps. Required long text supports empty strings too.
"""

import json
import uuid
from datetime import timezone

from sqlalchemy import JSON, DateTime, String, Text, Uuid
from sqlalchemy.dialects import mysql, oracle
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import TypeDecorator
from sqlmodel.sql.sqltypes import AutoString


class PortableUUID(TypeDecorator):
    impl = Uuid
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(oracle.RAW(16) if dialect.name == "oracle" else Uuid())

    def process_bind_param(self, value, dialect):
        if value is not None and dialect.name == "oracle":
            return (value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))).bytes
        return value

    def process_result_value(self, value, dialect):
        if value is not None and dialect.name == "oracle":
            return uuid.UUID(bytes=bytes(value))
        return value


class PortableJSON(TypeDecorator):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(oracle.CLOB() if dialect.name == "oracle" else JSON())

    def process_bind_param(self, value, dialect):
        if dialect.name == "oracle":
            return json.dumps(None if value is JSON.NULL else value, ensure_ascii=False, allow_nan=False)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and dialect.name == "oracle":
            return json.loads(value.read() if hasattr(value, "read") else value)
        return value


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(
            oracle.TIMESTAMP(timezone=True) if dialect.name == "oracle" else DateTime(timezone=True)
        )

    def process_bind_param(self, value, dialect):
        if value is not None and dialect.name == "oracle":
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and dialect.name == "oracle":
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value

    def column_expression(self, column):
        return _UTCColumn(column, type_=self)

    def bind_expression(self, bindvalue):
        return _UTCBind(bindvalue, type_=self)


class _RequiredText(FunctionElement):
    inherit_cache = True

    def __init__(self, value, *, type_):
        super().__init__(value)
        self.type = type_


class _UTCColumn(_RequiredText):
    inherit_cache = True


class _UTCBind(_RequiredText):
    inherit_cache = True


@compiles(_UTCBind)
def _utc_bind_default(element, compiler, **kwargs):
    return compiler.process(list(element.clauses)[0], **kwargs)


@compiles(_UTCBind, "oracle")
def _utc_bind_oracle(element, compiler, **kwargs):
    # The driver may bind datetime as TIMESTAMP without its Python tzinfo.
    # Our bind processor has normalized the wall time to UTC; make that zone
    # explicit instead of relying on the Oracle session's TIME_ZONE setting.
    return "FROM_TZ(CAST(" + compiler.process(list(element.clauses)[0], **kwargs) + " AS TIMESTAMP), '+00:00')"


@compiles(_UTCColumn)
def _utc_column_default(element, compiler, **kwargs):
    return compiler.process(list(element.clauses)[0], **kwargs)


@compiles(_UTCColumn, "oracle")
def _utc_column_oracle(element, compiler, **kwargs):
    # python-oracledb's datetime conversion need not retain a timezone object.
    # Extract UTC in SQL before conversion so the instant survives any session
    # timezone or values written with a different original offset.
    return "SYS_EXTRACT_UTC(" + compiler.process(list(element.clauses)[0], **kwargs) + ")"


@compiles(_RequiredText)
def _required_text_default(element, compiler, **kwargs):
    return compiler.process(list(element.clauses)[0], **kwargs)


@compiles(_RequiredText, "oracle")
def _required_text_oracle(element, compiler, **kwargs):
    # Oracle folds the empty string to NULL; required prompt/chat text may be
    # empty while a deck is being drafted. Persist an empty LOB in that case.
    return "COALESCE(" + compiler.process(list(element.clauses)[0], **kwargs) + ", EMPTY_CLOB())"


class RequiredText(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, original=None):
        self.original = original if original is not None else Text()
        super().__init__()

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(oracle.CLOB() if dialect.name == "oracle" else self.original)

    def bind_expression(self, bindvalue):
        return _RequiredText(bindvalue, type_=self)

    def process_result_value(self, value, dialect):
        if dialect.name == "oracle":
            return value.read() if hasattr(value, "read") else (value or "")
        return value


def auto_text():
    return AutoString().with_variant(oracle.CLOB(), "oracle")


def string_text():
    return String().with_variant(oracle.CLOB(), "oracle").with_variant(mysql.TEXT(), "mysql")


def label(length=255, *, auto=False):
    return ((AutoString() if auto else String()).with_variant(oracle.VARCHAR2(length), "oracle")
            .with_variant(mysql.VARCHAR(length), "mysql"))
