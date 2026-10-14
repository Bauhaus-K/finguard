from decimal import Decimal

from app.calc.common import FigureUnit
from app.gateway.checks import CheckContext
from app.gateway.types import GatewayInput, source

K, P, M, DY = FigureUnit.KRW, FigureUnit.PERCENT, FigureUnit.MONTHS, FigureUnit.DAYS


def inp(answer: str, **kw) -> GatewayInput:
    return GatewayInput(answer=answer, **kw)


def src(value, unit=K) -> object:
    return source("s", Decimal(str(value)), unit)


CTX = CheckContext()
