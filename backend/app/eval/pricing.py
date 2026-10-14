"""요청당 비용 추정용 단가 (USD / 100만 토큰). 2026-10 기준 공개 단가이며 변경될 수 있다."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float
    cache_write: float  # 5분 TTL 캐시 쓰기


PRICES: dict[str, Price] = {
    "claude-sonnet-5-5": Price(2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": Price(4.00, 20.00, 0.20, 5.00),
    "claude-haiku-5-5": Price(0.10, 0.50, 0.01, 0.125),
}


def cost_usd(model: str, usage: dict[str, int]) -> float | None:
    p = PRICES.get(model)
    if p is None:
        return None
    return (
        usage.get("input_tokens", 0) * p.input
        + usage.get("output_tokens", 0) * p.output
        + usage.get("cache_read_input_tokens", 0) * p.cache_read
        + usage.get("cache_creation_input_tokens", 0) * p.cache_write
    ) / 1_000_000
