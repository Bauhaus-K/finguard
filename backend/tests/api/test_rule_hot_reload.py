"""데모 시나리오 6: 규칙 YAML 에 금지 표현을 추가하면 코드 수정·재시작 없이 다음 요청부터 반영된다."""

import os
import shutil

from app.llm.fake import say

from .conftest import AH, H

ANSWER = "이 예금은 고객님께 최고의 선택입니다."
NEW_TERM = """\
forbidden_expressions:
  terms:
    - id: best_choice
      label: 최선 단정
      pattern: '최고의\\s*선택'
      action: block
"""


def test_added_forbidden_term_applies_without_restart(make_client, settings, tmp_path):
    rules_dir = tmp_path / "rules"
    shutil.copytree(settings.rules_dir, rules_dir)
    client, _ = make_client([say(ANSWER), say(ANSWER)], rules_dir=rules_dir)

    before = client.post("/v1/gateway/check", json={"answer": ANSWER}, headers=H).json()
    assert before["status"] in ("PASS", "AUTO_FIXED")

    tenant_file = rules_dir / "tenants" / "demo.yaml"
    tenant_file.write_text(NEW_TERM, encoding="utf-8")
    st = tenant_file.stat()
    os.utime(tenant_file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    after = client.post("/v1/gateway/check", json={"answer": ANSWER}, headers=H).json()
    assert after["status"] == "BLOCKED"
    assert after["rules_digest"] != before["rules_digest"]
    forbidden = next(c for c in after["checks"] if c["check"] == "forbidden_expressions")
    assert forbidden["findings"][-1]["code"] == "best_choice"

    chat = client.post("/v1/chat", json={"message": "예금 어때요?"}, headers=H).json()
    assert chat["status"] == "BLOCKED"
    assert client.get("/v1/rules", headers=AH).json()["digest"] == after["rules_digest"]
