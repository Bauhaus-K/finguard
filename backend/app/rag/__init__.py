"""약관 검색(RAG).

Retriever 프로토콜 뒤에 구현을 둔다. 개발 기본값은 외부 의존이 없는 BM25.
pgvector 임베딩 검색은 같은 프로토콜로 추가한다(임베딩 모델 선택은 미정).
"""

from app.rag.chunker import TermsChunk, chunk_terms_document, load_terms_chunks
from app.rag.retriever import BM25Retriever, Retriever, SearchHit

__all__ = [
    "BM25Retriever",
    "Retriever",
    "SearchHit",
    "TermsChunk",
    "chunk_terms_document",
    "load_terms_chunks",
]
