import json
import re
from html import unescape
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest
from pydantic import SecretStr

from backend.app.core.config import Settings
from backend.app.services.password_reset_email import (
    PasswordResetEmailDeliveryError,
    ResendPasswordResetEmailSender,
    _SameOriginRedirectHandler,
)


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self._body


def _settings() -> Settings:
    return Settings(
        app_env="test",
        secret_key="test-only-secret",
        resend_api_key=SecretStr("fake-resend-key"),
        resend_from_email="Kwitli <noreply@mail.kwitli.app>",
        password_reset_app_url="kwitli://reset-password",
        password_reset_token_expire_minutes=30,
    )


def test_password_reset_url_defaults_to_the_native_app_scheme():
    settings = Settings(_env_file=None, app_env="test", secret_key="test-only-secret")

    assert settings.password_reset_app_url == "kwitli://reset-password"


def test_resend_sends_french_reset_email_without_password_or_logging_token():
    captured = {}

    def fake_opener(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(b'{"id":"fake-message-id"}')

    sender = ResendPasswordResetEmailSender(_settings(), opener=fake_opener)
    sender.send_password_reset("owner@example.invalid", "opaque-reset-token-value")

    request = captured["request"]
    body = json.loads(request.data)
    assert request.full_url == "https://api.resend.com/emails"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer fake-resend-key"
    assert request.get_header("User-agent") == "kwitli/1.0"
    assert captured["timeout"] == 10
    assert body["from"] == "Kwitli <noreply@mail.kwitli.app>"
    assert body["to"] == ["owner@example.invalid"]
    assert set(body) == {"from", "to", "subject", "text", "html"}
    button_match = re.search(r'<a href="([^"]+)"', body["html"])
    assert button_match is not None
    button_url = urlsplit(unescape(button_match.group(1)))
    assert button_url.scheme == "kwitli"
    assert button_url.netloc == "reset-password"
    assert parse_qs(button_url.query) == {"token": ["opaque-reset-token-value"]}
    assert "kwitli://reset-password?token=opaque-reset-token-value" in body["text"]
    assert "iPhone" in body["text"] and "Android" in body["html"]
    assert "Safari sur ordinateur" in body["text"]
    assert "30 minutes" in body["text"]
    assert "ignorez" in body["text"]
    assert "opaque-reset-token-value" in body["text"]
    assert "mot de passe" in body["text"].lower()


def test_cross_origin_redirect_is_rejected_before_authorization_can_be_forwarded():
    request = Request(
        "https://api.resend.com/emails",
        data=b"{}",
        headers={"Authorization": "Bearer fake-resend-key"},
        method="POST",
    )
    handler = _SameOriginRedirectHandler()

    with pytest.raises(HTTPError) as exc_info:
        handler.redirect_request(
            request,
            BytesIO(b"redirect response"),
            302,
            "Found",
            {},
            "https://attacker.invalid/collect",
        )

    assert "Cross-origin redirect refused" in str(exc_info.value.reason)
    assert "fake-resend-key" not in str(exc_info.value)


@pytest.mark.parametrize(
    "status_code", [401, 403, 422, 429, 500],
)
def test_resend_logs_provider_http_status_without_response_body(status_code, caplog):
    sensitive = "private-email@example.com reset-token-value fake-api-key response-secret"

    def fake_opener(_request, *, timeout):
        raise HTTPError(
            "https://api.resend.com/emails", status_code, sensitive, None, BytesIO(sensitive.encode())
        )

    sender = ResendPasswordResetEmailSender(_settings(), opener=fake_opener)
    with pytest.raises(PasswordResetEmailDeliveryError) as exc_info:
        sender.send_password_reset("private-email@example.com", "reset-token-value")

    assert str(exc_info.value) == "Échec de l'envoi du courriel de récupération."
    assert f"category=provider_http response_origin=unverified status_code={status_code}" in caplog.text
    assert "provider_error_code=unavailable" in caplog.text
    assert sensitive not in caplog.text
    assert "private-email@example.com" not in caplog.text
    assert "reset-token-value" not in caplog.text
    assert "fake-api-key" not in caplog.text
    assert "response-secret" not in caplog.text


@pytest.mark.parametrize("status_code", [401, 403, 422, 429, 500])
def test_resend_logs_non_success_response_status(status_code, caplog):
    sender = ResendPasswordResetEmailSender(
        _settings(), opener=lambda _request, **_kwargs: FakeResponse(b'{"message":"private"}', status_code)
    )

    with pytest.raises(PasswordResetEmailDeliveryError):
        sender.send_password_reset("owner@example.invalid", "opaque-reset-token-value")

    assert f"category=provider_http status_code={status_code}" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        (b'{"name":"restricted_api_key","message":"private account detail"}', "restricted_api_key"),
        (b'{"error":{"code":"domain_not_verified","message":"private detail"}}', "domain_not_verified"),
        (b'{"name":"private-email@example.com","message":"reset-token-value"}', "unrecognized"),
        (b'{"code":"fake-api-key-value-that-must-not-be-logged"}', "unrecognized"),
        (b"not-json private-provider-body", "unavailable"),
    ],
    ids=["known-name", "known-nested-code", "email-rejected", "secret-rejected", "invalid-json"],
)
def test_resend_http_error_logs_only_allowlisted_structured_code(body, expected_code, caplog):
    sensitive_values = [
        "private-email@example.com",
        "reset-token-value",
        "fake-api-key-value-that-must-not-be-logged",
        "private account detail",
        "private detail",
        "private-provider-body",
    ]

    def fake_opener(_request, *, timeout):
        raise HTTPError(
            "https://api.resend.com/emails", 403, "forbidden", None, BytesIO(body)
        )

    sender = ResendPasswordResetEmailSender(_settings(), opener=fake_opener)
    with pytest.raises(PasswordResetEmailDeliveryError):
        sender.send_password_reset("private-email@example.com", "reset-token-value")

    assert "response_origin=unverified status_code=403" in caplog.text
    assert f"provider_error_code={expected_code}" in caplog.text
    for sensitive in sensitive_values:
        assert sensitive not in caplog.text


@pytest.mark.parametrize(
    ("failure", "expected_category"),
    [
        (TimeoutError("private timeout data"), "timeout"),
        (URLError("private network data"), "network_error"),
        (OSError("private socket data"), "network_error"),
    ],
    ids=["timeout", "url-error", "socket-error"],
)
def test_resend_transport_failures_are_categorized_without_sensitive_details(
    failure, expected_category, caplog
):
    sender = ResendPasswordResetEmailSender(
        _settings(), opener=lambda _request, **_kwargs: (_ for _ in ()).throw(failure)
    )
    with pytest.raises(PasswordResetEmailDeliveryError) as exc_info:
        sender.send_password_reset("private-email@example.com", "reset-token-value")

    assert f"category={expected_category}" in caplog.text
    assert "private" not in caplog.text
    assert "reset-token-value" not in caplog.text
    assert "fake-resend-key" not in caplog.text
    assert "private" not in str(exc_info.value)


def test_resend_sender_uses_configured_from_email_and_default_when_blank():
    configured = _settings()
    configured.resend_from_email = "Kwitli Ops <support@mail.kwitli.app>"
    sender = ResendPasswordResetEmailSender(configured, opener=lambda *_args, **_kwargs: None)
    assert sender.sender == "Kwitli Ops <support@mail.kwitli.app>"

    blank = _settings()
    blank.resend_from_email = " "
    assert ResendPasswordResetEmailSender(blank).sender == "Kwitli <noreply@mail.kwitli.app>"


@pytest.mark.parametrize(
    "body",
    [b"not-json", b'{"message":"accepted without message id"}', b'{"id":7}'],
    ids=["invalid-json", "missing-id", "invalid-id"],
)
def test_resend_rejects_invalid_provider_response(body):
    sender = ResendPasswordResetEmailSender(
        _settings(), opener=lambda _request, **_kwargs: FakeResponse(body)
    )

    with pytest.raises(PasswordResetEmailDeliveryError):
        sender.send_password_reset("owner@example.invalid", "opaque-reset-token-value")


def test_resend_invalid_response_logs_only_category(caplog):
    sender = ResendPasswordResetEmailSender(
        _settings(), opener=lambda _request, **_kwargs: FakeResponse(b'{"detail":"private-provider-data"}')
    )

    with pytest.raises(PasswordResetEmailDeliveryError):
        sender.send_password_reset("private-email@example.com", "reset-token-value")

    assert "category=invalid_response" in caplog.text
    assert "private-provider-data" not in caplog.text
    assert "private-email@example.com" not in caplog.text
    assert "reset-token-value" not in caplog.text
