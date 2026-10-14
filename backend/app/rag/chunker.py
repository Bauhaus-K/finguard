"""약관 markdown 을 조항(## 제N조) / FAQ(### Q) 단위로 자른다."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)
_SECTION = re.compile(r"^(##|###) (.+)$", re.M)


@dataclass(frozen=True)
class TermsChunk:
    chunk_id: str  # 예: HB-DEP-001#제6조
    product_code: str
    section: str  # 예: "제6조 (중도해지)" 또는 "Q1. ..."
    text: str


def chunk_terms_document(markdown: str) -> list[TermsChunk]:
    m = _FRONT_MATTER.match(markdown)
    if not m:
        raise ValueError("약관 문서에 front matter(product_code)가 없습니다")
    meta = yaml.safe_load(m.group(1))
    code = meta["product_code"]
    title = meta.get("title", code)
    body = markdown[m.end() :]

    headers = list(_SECTION.finditer(body))
    chunks: list[TermsChunk] = []
    for i, h in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        section = h.group(2).strip()
        content = body[h.end() : end].strip().rstrip("-").strip()
        if not content:
            continue
        key = section.split(" ")[0].rstrip(".")  # "제6조" / "Q1"
        chunks.append(
            TermsChunk(
                chunk_id=f"{code}#{key}",
                product_code=code,
                section=section,
                text=f"[{title}] {section}\n{content}",
            )
        )
    return chunks


def load_terms_chunks(terms_dir: Path) -> list[TermsChunk]:
    chunks: list[TermsChunk] = []
    for path in sorted(terms_dir.glob("*.md")):
        chunks.extend(chunk_terms_document(path.read_text(encoding="utf-8")))
    return chunks
