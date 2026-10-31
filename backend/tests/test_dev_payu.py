import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "dev_payu.py"
SPEC = importlib.util.spec_from_file_location("kwitli_dev_payu", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
dev_payu = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dev_payu
SPEC.loader.exec_module(dev_payu)


def write_backend_env(path: Path, public_url: str = dev_payu.FIXED_PUBLIC_API_URL) -> None:
    path.write_text(
        "\n".join((
            "PAYU_ENV=sandbox",
            "PAYU_API_LOGIN=login-secret",
            "PAYU_API_KEY=api-key-secret",
            "PAYU_MERCHANT_ID=merchant-secret",
            "PAYU_ACCOUNT_ID=account-secret",
            "PAYU_PUBLIC_KEY=public-key-secret",
            "PAYU_CHECKOUT_URL=https://sandbox.checkout.payulatam.com/ppp-web-gateway-payu/",
            f"PUBLIC_API_URL={public_url}",
            "SECRET_KEY=secret-key",
            "",
        )),
        encoding="utf-8",
    )


def test_fixed_public_urls_accept_the_named_tunnel_without_writing_files(tmp_path: Path):
    backend_env = tmp_path / "backend.env"
    mobile_env = tmp_path / "mobile.env"
    write_backend_env(backend_env)
    mobile_env.write_text(
        f"EXPO_PUBLIC_API_URL={dev_payu.FIXED_PUBLIC_API_URL}\nOTHER_SETTING=keep\n",
        encoding="utf-8",
    )
    backend_before = backend_env.read_text(encoding="utf-8")
    mobile_before = mobile_env.read_text(encoding="utf-8")

    dev_payu.validate_payu_environment(backend_env)
    dev_payu.validate_fixed_public_urls(backend_env, mobile_env)

    assert backend_env.read_text(encoding="utf-8") == backend_before
    assert mobile_env.read_text(encoding="utf-8") == mobile_before


def test_fixed_public_urls_reject_an_outdated_or_missing_configuration(tmp_path: Path):
    backend_env = tmp_path / "backend.env"
    mobile_env = tmp_path / "mobile.env"
    write_backend_env(backend_env, "https://old-tunnel.example")
    mobile_env.write_text("EXPO_PUBLIC_API_URL=https://old-tunnel.example\n", encoding="utf-8")

    with pytest.raises(dev_payu.DevPayUError, match="PUBLIC_API_URL"):
        dev_payu.validate_fixed_public_urls(backend_env, mobile_env)

    write_backend_env(backend_env)
    mobile_env.unlink()
    with pytest.raises(dev_payu.DevPayUError, match="mobile/.env"):
        dev_payu.validate_fixed_public_urls(backend_env, mobile_env)


def test_validate_payu_environment_rejects_missing_required_values(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text("PAYU_ENV=sandbox\n", encoding="utf-8")

    with pytest.raises(dev_payu.DevPayUError, match="incomplete"):
        dev_payu.validate_payu_environment(env_path)


def test_wait_for_fixed_tunnel_health_retries_before_success():
    outcomes = iter((
        dev_payu.HealthcheckResult(False, "erreur de connexion: DNS"),
        dev_payu.HealthcheckResult(False, "HTTP 502"),
        dev_payu.HealthcheckResult(True, "Kwitli OK"),
    ))
    messages: list[str] = []

    dev_payu.wait_for_public_health(
        check=lambda _url: next(outcomes),
        sleep=lambda _delay: None,
        output=messages.append,
    )

    assert "Public healthcheck attempt 3/30" in messages
    assert messages[-1] == "Public healthcheck OK"


def test_fixed_tunnel_health_timeout_has_clear_reason():
    with pytest.raises(dev_payu.DevPayUError, match="tunnel fixe kwitli-dev.*DNS"):
        dev_payu.wait_for_public_health(
            attempts=3,
            delay=0,
            check=lambda _url: dev_payu.HealthcheckResult(False, "erreur de connexion: DNS"),
            sleep=lambda _delay: None,
            output=lambda _message: None,
        )


def test_python_resolution_failure_falls_back_to_curl_successfully():
    curl_calls: list[str] = []

    result = dev_payu.healthcheck_with_fallback(
        dev_payu.FIXED_PUBLIC_HEALTH_URL,
        python_check=lambda _url: dev_payu.HealthcheckResult(False, "erreur de connexion: [Errno 8] not known"),
        curl_check=lambda url: curl_calls.append(url) or dev_payu.HealthcheckResult(True, "Kwitli OK"),
    )

    assert result.ok
    assert curl_calls == [dev_payu.FIXED_PUBLIC_HEALTH_URL]


def test_python_cloudflare_403_falls_back_to_curl_successfully():
    result = dev_payu.healthcheck_with_fallback(
        dev_payu.FIXED_PUBLIC_HEALTH_URL,
        python_check=lambda _url: dev_payu.HealthcheckResult(False, "HTTP 403"),
        curl_check=lambda _url: dev_payu.HealthcheckResult(True, "Kwitli OK"),
    )

    assert result.ok


def test_curl_healthcheck_accepts_only_kwitli_response():
    good_response = subprocess.CompletedProcess(["curl"], 0, '{"status":"ok","app":"Kwitli"}', "")
    bad_response = subprocess.CompletedProcess(["curl"], 0, '{"status":"ok","app":"Other"}', "")

    assert dev_payu.curl_healthcheck_result(
        "https://example.test", curl_path="curl", runner=lambda *_args, **_kwargs: good_response
    ).ok
    assert not dev_payu.curl_healthcheck_result(
        "https://example.test", curl_path="curl", runner=lambda *_args, **_kwargs: bad_response
    ).ok


def test_fixed_tunnel_workflow_has_no_quick_tunnel_or_env_writer():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "trycloudflare.com" not in source
    assert "tunnel --url" not in source
    assert "update_public_urls" not in source
    assert "cloudflared" not in source
