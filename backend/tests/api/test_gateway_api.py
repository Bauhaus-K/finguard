from .conftest import H


def check(client, **body):
    return client.post("/v1/gateway/check", json=body, headers=H)


def test_gateway_check_pass_and_fixed(make_client):
    client, _ = make_client()
    r = check(
        client,
        answer="한빛 정기예금(가상) 기준 세후 이자는 279,180원입니다.",
        sources=[{"name": "after_tax_interest", "value": "279180", "unit": "KRW"}],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "AUTO_FIXED"
    assert "예금자보호법" in body["final_answer"]
    assert body["rules_version"] and body["rules_digest"]
    assert all("text_after" not in c for c in body["checks"])


def test_gateway_check_wrong_number_blocked(make_client):
    client, _ = make_client()
    body = check(
        client,
        answer="세후 이자는 297,180원입니다.",
        sources=[{"value": 279180, "unit": "KRW"}],
    ).json()
    assert body["status"] == "BLOCKED" and body["retryable"] is True


def test_gateway_check_context_texts(make_client):
    client, _ = make_client()
    body = check(
        client, answer="예금자보호 한도는 1억원입니다.", context_texts=["1인당 최고 1억원까지 보호"]
    ).json()
    numeric = next(c for c in body["checks"] if c["check"] == "numeric")
    assert numeric["outcome"] == "PASS"


def test_gateway_check_audited_and_masked(make_client):
    client, _ = make_client()
    body = check(client, answer="번호 010-1234-5678 확인", user_message="900101-1234567").json()
    assert body["status"] == "AUTO_FIXED"
    rec = client.get(f"/v1/audit/records/{body['request_id']}", headers=H).json()
    assert rec["mode"] == "gateway_only"
    dumped = str(rec)
    assert "010-1234-5678" not in dumped and "900101-1234567" not in dumped


def test_gateway_check_validation(make_client):
    client, _ = make_client()
    assert check(client, answer="").status_code == 422
    assert check(client, answer="x", sources=[{"value": 1, "unit": "EUR"}]).status_code == 422
