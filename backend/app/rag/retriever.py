"""검색기 인터페이스와 BM25 구현.

한국어 형태소 분석기 없이도 동작하도록 토큰을 '공백 단위 단어 + 한글 문자 bigram' 으로 만든다.
(조사가 붙은 어절 '중도해지는' 과 '중도해지' 가 bigram 수준에서 겹치도록)
"""

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from app.rag.chunker import TermsChunk

_WORD = re.compile(r"[0-9A-Za-z.]+|[가-힣]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for word in _WORD.findall(text.lower()):
        tokens.append(word)
        if "가" <= word[0] <= "힣" and len(word) > 1:
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
    return tokens


@dataclass(frozen=True)
class SearchHit:
    chunk: TermsChunk
    score: float


class Retriever(Protocol):
    def search(
        self, query: str, *, k: int = 4, product_code: str | None = None
    ) -> list[SearchHit]: ...


class BM25Retriever:
    def __init__(self, chunks: list[TermsChunk], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1, self.b = k1, b
        self._tfs = [Counter(tokenize(c.text)) for c in chunks]
        self._lens = [sum(tf.values()) for tf in self._tfs]
        self._avg_len = (sum(self._lens) / len(self._lens)) if chunks else 0.0
        df: Counter[str] = Counter()
        for tf in self._tfs:
            df.update(tf.keys())
        n = len(chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def _score(self, q_tokens: list[str], i: int) -> float:
        tf, length = self._tfs[i], self._lens[i]
        score = 0.0
        for t in q_tokens:
            f = tf.get(t)
            if not f:
                continue
            norm = (
                f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self._avg_len))
            )
            score += self._idf[t] * norm
        return score

    def search(self, query: str, *, k: int = 4, product_code: str | None = None) -> list[SearchHit]:
        q_tokens = tokenize(query)
        hits = [
            SearchHit(chunk=c, score=self._score(q_tokens, i))
            for i, c in enumerate(self.chunks)
            if product_code is None or c.product_code == product_code
        ]
        hits = [h for h in hits if h.score > 0]
        hits.sort(key=lambda h: (-h.score, h.chunk.chunk_id))
        return hits[:k]
