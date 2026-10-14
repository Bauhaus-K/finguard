import pytest

from app.rag import BM25Retriever, chunk_terms_document, load_terms_chunks
from app.rag.retriever import tokenize


def test_chunks_cover_all_products(settings, catalog):
    chunks = load_terms_chunks(settings.data_dir / "terms")
    assert {c.product_code for c in chunks} == {p.code for p in catalog.products}
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(c.text.startswith("[") for c in chunks)


def test_chunk_ids_and_sections():
    md = "---\nproduct_code: X-1\ntitle: 테스트\n---\n# 제목\n## 제1조 (목적)\n내용 A\n## 제2조 (빈)\n\n### Q1. 질문?\n답변\n"
    chunks = chunk_terms_document(md)
    assert [c.chunk_id for c in chunks] == ["X-1#제1조", "X-1#Q1"]
    assert chunks[0].section == "제1조 (목적)"
    assert "내용 A" in chunks[0].text


def test_missing_front_matter():
    with pytest.raises(ValueError):
        chunk_terms_document("## 제1조\n내용")


def test_tokenize_korean_bigrams():
    tokens = tokenize("중도해지는")
    assert "중도해지는" in tokens and "중도" in tokens and "해지" in tokens


@pytest.mark.parametrize(
    ("query", "product_code", "expected"),
    [
        ("예금자보호 한도", "HB-DEP-001", "HB-DEP-001#제9조"),
        ("중도상환수수료", "HB-LOAN-001", "HB-LOAN-001#제7조"),
        ("중도해지이율", "HB-DEP-002", "HB-DEP-002#제6조"),
        (
            "적금 이자가 총 납입액 곱하기 금리보다 적은 이유",
            "HB-SAV-001",
            "HB-SAV-001#Q1",
        ),  # 제5조도 정답
        ("보증료", "HB-POL-001", None),
    ],
)
def test_search_top_hit(retriever, query, product_code, expected):
    hits = retriever.search(query, k=3, product_code=product_code)
    assert hits
    assert all(h.chunk.product_code == product_code for h in hits)
    if expected:
        assert expected in [h.chunk.chunk_id for h in hits[:2]]
    assert hits == sorted(hits, key=lambda h: -h.score)


def test_search_no_hits(retriever):
    assert retriever.search("zzzz qqqq") == []


def test_empty_retriever():
    assert BM25Retriever([]).search("무엇이든") == []
