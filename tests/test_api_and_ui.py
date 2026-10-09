"""API contract tests and a Streamlit smoke test."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import config, pipeline


@pytest.fixture
def client():
    import api
    return TestClient(api.app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_review_and_audit_flow(client, samples):
    p = samples["invoice_missing"]
    r = client.post("/documents", files={"file": (p.name, p.read_bytes(), "application/pdf")})
    assert r.status_code == 200 and r.json()["status"] == "pending_review"
    doc_id = r.json()["doc_id"]

    # reject without reason -> 409 with a useful message
    bad = client.post(f"/documents/{doc_id}/review", json={"decision": "reject", "reviewer": "ali"})
    assert bad.status_code == 409 and "reason" in bad.json()["detail"]

    ok = client.post(f"/documents/{doc_id}/review", json={"decision": "approve", "reviewer": "ali"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"

    # approved -> approve again is an invalid transition
    again = client.post(f"/documents/{doc_id}/review", json={"decision": "approve", "reviewer": "ali"})
    assert again.status_code == 409

    events = client.get(f"/documents/{doc_id}/audit").json()
    assert any(e["to_status"] == "approved" and e["actor"] == "ali" for e in events)


def test_api_error_codes(client, samples):
    p = samples["unsupported"]
    assert client.post("/documents", files={"file": (p.name, p.read_bytes())}).status_code == 415
    assert client.get("/documents/9999").status_code == 404
    assert client.post("/documents/1/review", json={"decision": "maybe", "reviewer": "x"}).status_code == 422
    assert client.post("/ask", json={"question": "hi"}).status_code == 422


def test_api_key_enforced(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "secret")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"X-API-Key": "secret"}).status_code == 200


def test_ask_endpoint(client, samples):
    p = samples["invoice"]
    client.post("/documents", files={"file": (p.name, p.read_bytes())})
    body = client.post("/ask", json={"question": "What is the invoice number?"}).json()
    assert body["answered"] and body["sources"]


def test_streamlit_pages_render_without_errors(samples):
    from streamlit.testing.v1 import AppTest

    for k in ("invoice", "invoice_missing", "corrupted"):
        pipeline.process_upload(samples[k].name, samples[k].read_bytes())
    at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=60).run()
    assert not at.exception
    for page in ["⬆️ Upload", "🗂️ Documents", "🧑‍⚖️ Review Queue", "💬 Assistant", "🕒 Audit Trail", "📊 Dashboard"]:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, f"{page}: {at.exception}"
