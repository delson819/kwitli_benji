import re
import asyncio
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from backend.app.database import get_session_factory
from backend.app.kyb.policies import get_policy
from backend.app.kyb.security import decrypt_document
from backend.app.rate_limit import InMemoryRateLimiter, UploadSecurityMiddleware
from backend.app.persistence.models import (
    CookProfile, MerchantVerificationCase, MerchantVerificationDocument,
    MerchantVerificationEvent, User,
)


PASSWORD = "KybTestPassword123!"
TEST_KEY = "12" * 32


def _register(client, email):
    response = client.post("/api/v1/auth/register", json={
        "email": email, "password": PASSWORD, "first_name": "Test",
    })
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _enable_kyb(monkeypatch, tmp_path):
    from backend.app.api.routes import kyb as kyb_routes
    from backend.app.core.config import get_settings
    monkeypatch.setenv("KYB_ENABLED", "true")
    monkeypatch.setenv("KYB_ENCRYPTION_KEY", TEST_KEY)
    monkeypatch.setenv("KYB_PRIVATE_STORAGE_DIR", str(tmp_path / "private"))
    monkeypatch.setattr(kyb_routes, "collection_ready", lambda: True)
    get_settings.cache_clear()


def _make_cook(client, headers, email):
    cook_response = client.post("/api/v1/cooks", headers=headers, json={
        "display_name": "Kyb Restaurant", "latitude": 14.7, "longitude": -17.4,
    })
    assert cook_response.status_code == 201
    return cook_response.json()["id"]


def test_senegal_policy_is_pending_legal_review_and_not_active():
    policy = get_policy("SN", "SN", "local_business", "food_service")
    assert policy["active"] is False
    assert policy["legal_review"] == "pending_legal_review"
    assert {item["code"] for item in policy["requirements"]} == {
        "business_identifier", "commercial_registration", "responsible_identity",
        "operating_permit", "sanitary_proof",
    }
    assert all(item["status"] == "pending_legal_review" and item["required"] is None
               for item in policy["requirements"])


def test_kyb_collection_is_disabled_by_default(client):
    response = client.post("/api/v1/kyb/cases", json={
        "country_code": "SN", "jurisdiction_code": "SN",
        "legal_entity_type": "local_business", "business_activity": "food_service",
    }, headers=_register(client, "kyb-disabled@example.com"))
    assert response.status_code == 503


def test_owner_case_is_encrypted_and_other_owner_cannot_upload(client, monkeypatch, tmp_path):
    from backend.app.api.routes import kyb as kyb_routes
    from backend.app.kyb.security import encrypt_document

    _enable_kyb(monkeypatch, tmp_path)
    owner_headers = _register(client, "kyb-owner@example.com")
    cook_id = _make_cook(client, owner_headers, "kyb-owner@example.com")
    other_headers = _register(client, "kyb-other@example.com")
    _make_cook(client, other_headers, "kyb-other@example.com")
    case_response = client.post("/api/v1/kyb/cases", headers=owner_headers, json={
        "country_code": "SN", "jurisdiction_code": "SN",
        "legal_entity_type": "local_business", "business_activity": "food_service",
        "legal_data": {"business_reference": "SYNTHETIC-PRIVATE-73"},
    })
    assert case_response.status_code == 201
    case_id = case_response.json()["id"]
    assert case_response.json()["legal_review"] == "pending_legal_review"

    with get_session_factory()() as session:
        case = session.get(MerchantVerificationCase, case_id)
        assert case.cook_profile_id == cook_id
        assert b"SYNTHETIC-PRIVATE-73" not in case.legal_data_ciphertext
        assert b"SYNTHETIC-PRIVATE-73" in decrypt_document(case.legal_data_ciphertext)
        assert all(item["status"] == "pending_legal_review" for item in case.policy_snapshot["requirements"])

    blocked = client.post(
        f"/api/v1/kyb/cases/{case_id}/documents?requirement_code=business_identifier",
        headers=other_headers, files={"document": ("private.pdf", b"%PDF-1.7 synthetic", "application/pdf")},
    )
    assert blocked.status_code == 404

    monkeypatch.setattr(kyb_routes, "scan_and_encrypt", lambda data: (
        "12345678-1234-1234-1234-123456789abc", encrypt_document(data), __import__("hashlib").sha256(data).hexdigest()
    ))
    uploaded = client.post(
        f"/api/v1/kyb/cases/{case_id}/documents?requirement_code=business_identifier",
        headers=owner_headers, files={"document": ("ignored-name.pdf", b"%PDF-1.7 synthetic", "application/pdf")},
    )
    assert uploaded.status_code == 201
    stored_path = tmp_path / "private" / "12345678-1234-1234-1234-123456789abc.kyb"
    assert stored_path.exists()
    assert b"synthetic" not in stored_path.read_bytes()
    assert stored_path.stat().st_mode & 0o777 == 0o600
    with get_session_factory()() as session:
        document = session.get(MerchantVerificationDocument, uploaded.json()["id"])
        assert document.scan_status == "clean"
        assert document.status == "technically_valid"

    _register(client, "kyb-doc-admin@example.com")
    with get_session_factory()() as session:
        admin_user = session.scalar(select(User).where(User.email == "kyb-doc-admin@example.com"))
        admin_user.is_admin = True
        session.commit()
    admin_view = client.get(f"/admin/kyb/documents/{uploaded.json()['id']}",
                            auth=("kyb-doc-admin@example.com", PASSWORD))
    assert admin_view.status_code == 200
    assert admin_view.content == b"%PDF-1.7 synthetic"
    assert admin_view.headers["cache-control"] == "no-store, private"
    assert admin_view.headers["content-disposition"] == "attachment"
    owner_view = client.get(f"/admin/kyb/documents/{uploaded.json()['id']}",
                            headers=owner_headers)
    assert owner_view.status_code == 401
    assert client.get(f"/uploads/{uploaded.json()['id']}.kyb").status_code == 404
    dashboard = client.get("/admin", auth=("kyb-doc-admin@example.com", PASSWORD))
    review_form = re.search(
        rf'<form method="post" action="/admin/kyb/documents/{uploaded.json()["id"]}/verification">'
        rf'<input type="hidden" name="csrf_token" value="([^"]+)">', dashboard.text,
    )
    assert review_form
    fake_auth = client.post(
        f"/admin/kyb/documents/{uploaded.json()['id']}/verification",
        auth=("kyb-doc-admin@example.com", PASSWORD),
        data={"csrf_token": review_form.group(1), "method": "visual_review", "result": "confirmed"},
    )
    assert fake_auth.status_code == 422
    visual_review = client.post(
        f"/admin/kyb/documents/{uploaded.json()['id']}/verification",
        auth=("kyb-doc-admin@example.com", PASSWORD),
        data={"csrf_token": review_form.group(1), "method": "visual_review", "result": "consistent"},
    )
    assert visual_review.status_code in {200, 303}
    with get_session_factory()() as session:
        document = session.get(MerchantVerificationDocument, uploaded.json()["id"])
        assert document.status == "visually_reviewed"


def test_collection_fails_closed_without_antivirus(monkeypatch, tmp_path):
    from backend.app.core.config import get_settings
    from backend.app.kyb.security import collection_ready

    monkeypatch.setenv("KYB_ENABLED", "true")
    monkeypatch.setenv("KYB_ENCRYPTION_KEY", TEST_KEY)
    monkeypatch.setenv("KYB_PRIVATE_STORAGE_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("KYB_CLAMDSCAN_PATH", "missing-clamdscan-for-test")
    get_settings.cache_clear()
    assert collection_ready() is False


def test_kyb_upload_body_is_bounded_before_multipart_parsing():
    async def run():
        downstream_called = False
        sent = []

        async def downstream(_scope, _receive, _send):
            nonlocal downstream_called
            downstream_called = True

        middleware = UploadSecurityMiddleware(
            downstream,
            limiter=InMemoryRateLimiter(max_buckets=10),
            settings=SimpleNamespace(
                upload_max_bytes=1024, kyb_max_document_bytes=1024,
                api_v1_prefix="/api/v1", rate_limit_upload_requests=10,
                rate_limit_window_seconds=60, trusted_proxy_ips="127.0.0.1",
            ),
        )

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        body_size = 1024 + 64 * 1024 + 1
        await middleware({
            "type": "http", "method": "POST", "path": "/api/v1/kyb/cases/x/documents",
            "headers": [(b"content-length", str(body_size).encode())],
            "client": ("127.0.0.1", 1234),
        }, receive, send)
        assert not downstream_called
        assert next(message["status"] for message in sent if message["type"] == "http.response.start") == 413

    asyncio.run(run())


def test_admin_cannot_approve_before_legal_policy_is_confirmed(client, monkeypatch, tmp_path):
    _enable_kyb(monkeypatch, tmp_path)
    owner_headers = _register(client, "kyb-admin@example.com")
    _make_cook(client, owner_headers, "kyb-admin@example.com")
    response = client.post("/api/v1/kyb/cases", headers=owner_headers, json={
        "country_code": "SN", "jurisdiction_code": "SN",
        "legal_entity_type": "local_business", "business_activity": "food_service",
    })
    case_id = response.json()["id"]
    with get_session_factory()() as session:
        user = session.scalar(select(User).where(User.email == "kyb-admin@example.com"))
        user.is_admin = True
        session.commit()
    submitted = client.post(f"/api/v1/kyb/cases/{case_id}/submit", headers=owner_headers)
    assert submitted.status_code == 200
    admin = client.get("/admin", auth=("kyb-admin@example.com", PASSWORD))
    assert admin.status_code == 200
    assert "Dossiers KYB" in admin.text
    match = re.search(
        rf'<form method="post" action="/admin/kyb/{case_id}/decision">'
        rf'<input type="hidden" name="csrf_token" value="([^"]+)".*?'
        rf'<input type="hidden" name="action" value="approve">', admin.text, re.S,
    )
    assert match
    approved = client.post(f"/admin/kyb/{case_id}/decision", auth=("kyb-admin@example.com", PASSWORD), data={
        "csrf_token": match.group(1), "action": "approve",
    })
    assert approved.status_code == 409
    correction_form = re.search(
        rf'<form method="post" action="/admin/kyb/{case_id}/decision"><input type="hidden" name="csrf_token" value="([^"]+)'
        rf'"><input type="hidden" name="action" value="request_correction">', admin.text,
    )
    assert correction_form
    correction = client.post(f"/admin/kyb/{case_id}/decision", auth=("kyb-admin@example.com", PASSWORD), data={
        "csrf_token": correction_form.group(1), "action": "request_correction",
        "reason_code": "missing_information", "additional_code": "business_license_copy",
        "additional_label": "Copie de document additionnelle",
    })
    assert correction.status_code in {200, 303}
    with get_session_factory()() as session:
        case = session.get(MerchantVerificationCase, case_id)
        cook = session.get(CookProfile, case.cook_profile_id)
        assert case.status == "correction_required"
        assert case.additional_requirements == [{
            "code": "business_license_copy", "label": "Copie de document additionnelle",
            "status": "admin_requested", "required": True,
        }]
        assert cook.approval_status == "pending_review"
        event_id = session.scalar(select(MerchantVerificationEvent.id).where(
            MerchantVerificationEvent.case_id == case_id,
            MerchantVerificationEvent.action == "request_correction",
        ))
        assert event_id is not None
        with pytest.raises(DBAPIError):
            session.execute(__import__("sqlalchemy").update(MerchantVerificationEvent)
                            .where(MerchantVerificationEvent.id == event_id).values(action="tampered"))
        session.rollback()


def test_policy_lookup_does_not_call_pending_rules_legal_requirements(client):
    response = client.get("/api/v1/kyb/policies")
    assert response.status_code == 200
    assert response.json()["legal_review"] == "pending_legal_review"
    assert response.json()["active"] is False
