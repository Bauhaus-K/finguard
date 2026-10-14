"""DB 컬럼 타입."""

from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class ExactDecimal(TypeDecorator[Decimal]):
    """금리 등 소수값을 정확하게 저장한다.

    PostgreSQL: NUMERIC(12, 6). SQLite: 문자열(SQLite 는 Decimal 을 float 로 저장하므로).
    """

    impl = Numeric(12, 6)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(32))
        return dialect.type_descriptor(Numeric(12, 6, asdecimal=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = Decimal(value)
        return str(value) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(str(value))
