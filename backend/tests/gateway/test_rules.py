import os
import shutil

import pytest
from pydantic import ValidationError

from app.gateway.rules import Rules, RulesRepository, merge_rules


def test_default_rules_valid(rules):
    assert rules.order == [
        "pii",
        "scope",
        "numeric",
        "forbidden_expressions",
        "suitability",
        "disclosures",
    ]
    assert {t.id for t in rules.forbidden_expressions.terms} >= {
        "approval_guarantee",
        "guaranteed_return",
    }
    assert set(rules.disclosures.required) == {"DEPOSIT", "SAVINGS", "LOAN"}


def test_merge_by_id():
    base = {
        "terms": [{"id": "a", "x": 1}, {"id": "b", "x": 2}],
        "plain": [1, 2],
        "d": {"k": 1, "j": 2},
    }
    override = {
        "terms": [{"id": "a", "x": 9}, {"id": "c", "x": 3}, {"id": "b", "remove": True}],
        "plain": [3],
        "d": {"k": 5},
    }
    merged = merge_rules(base, override)
    assert merged["terms"] == [{"id": "a", "x": 9}, {"id": "c", "x": 3}]
    assert merged["plain"] == [3]
    assert merged["d"] == {"k": 5, "j": 2}
    assert base["terms"][0]["x"] == 1  # 원본 불변


@pytest.fixture
def rules_dir(tmp_path, settings):
    d = tmp_path / "rules"
    shutil.copytree(settings.rules_dir, d)
    return d


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    # 같은 해상도 안에서 두 번 써도 변경이 감지되도록 mtime 을 밀어 둔다
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


def test_tenant_override_and_hot_reload(rules_dir):
    repo = RulesRepository(rules_dir)
    before = repo.get("demo")
    assert before.files == ["default.yaml", "tenants/demo.yaml"]
    assert repo.get("demo") is before  # 캐시
    _write(
        rules_dir / "tenants" / "demo.yaml",
        "forbidden_expressions:\n  terms:\n    - id: best_choice\n      label: 최선 단정\n"
        "      pattern: '최고의\\s*선택'\n      action: block\n",
    )
    after = repo.get("demo")
    assert after is not before
    assert after.digest != before.digest
    ids = [t.id for t in after.rules.forbidden_expressions.terms]
    assert ids[-1] == "best_choice" and "approval_guarantee" in ids


def test_tenant_without_file(rules_dir):
    loaded = RulesRepository(rules_dir).get("other")
    assert loaded.files == ["default.yaml"] and loaded.rules is not None


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (
            "forbidden_expressions:\n  terms: [{id: x, label: x, pattern: '(', action: block}]\n",
            "정규식",
        ),
        ("order: [pii, magic]\n", "알 수 없는 검사"),
        ("order: [pii, pii]\n", "중복"),
        ("scope: [\n", "ParserError"),
        ("- just a list\n", "매핑"),
        ("numeric:\n  unknown_key: 1\n", "extra"),
    ],
)
def test_invalid_rules_report_error(rules_dir, content, error):
    _write(rules_dir / "tenants" / "demo.yaml", content)
    loaded = RulesRepository(rules_dir).get("demo")
    assert loaded.rules is None
    assert error in loaded.error


def test_missing_default(tmp_path):
    loaded = RulesRepository(tmp_path).get("demo")
    assert loaded.rules is None and "FileNotFoundError" in loaded.error


def test_rules_model_rejects_bad_action(rules):
    data = rules.model_dump()
    data["forbidden_expressions"]["terms"][0]["action"] = "explode"
    with pytest.raises(ValidationError):
        Rules.model_validate(data)


def test_check_enabled(rules):
    assert rules.check_enabled("numeric")
