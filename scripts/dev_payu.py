#!/usr/bin/env python3
"""Workflow local non sensible pour PayU Sandbox et le tunnel Cloudflare nomme."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_ENV = ROOT_DIR / "backend" / ".env"
MOBILE_ENV = ROOT_DIR / "mobile" / ".env"
LOCAL_HEALTH_URL = "http://127.0.0.1:8000/api/v1/health"
FIXED_PUBLIC_API_URL = "https://api-dev.kwitli.app"
FIXED_PUBLIC_HEALTH_URL = f"{FIXED_PUBLIC_API_URL}/api/v1/health"
REQUIRED_PAYU_KEYS = (
    "PAYU_ENV",
    "PAYU_API_LOGIN",
    "PAYU_API_KEY",
    "PAYU_MERCHANT_ID",
    "PAYU_ACCOUNT_ID",
    "PAYU_PUBLIC_KEY",
    "PAYU_CHECKOUT_URL",
)


class DevPayUError(RuntimeError):
    """Erreur affichable sans inclure la configuration locale."""


@dataclass(frozen=True)
class HealthcheckResult:
    ok: bool
    reason: str


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def validate_payu_environment(backend_env: Path = BACKEND_ENV) -> None:
    if not backend_env.exists():
        raise DevPayUError("backend/.env est introuvable. Copiez backend/.env.example puis renseignez PayU Sandbox.")
    values = read_env(backend_env)
    missing = [key for key in REQUIRED_PAYU_KEYS if not values.get(key)]
    if missing:
        raise DevPayUError("La configuration PayU Sandbox est incomplete. Verifiez backend/.env sans afficher ses valeurs.")
    if values.get("PAYU_ENV") != "sandbox":
        raise DevPayUError("PAYU_ENV doit etre defini a sandbox pour ce workflow.")


def normalize_url(value: str | None) -> str:
    return (value or "").strip().rstrip("/")


def validate_fixed_public_urls(
    backend_env: Path = BACKEND_ENV,
    mobile_env: Path = MOBILE_ENV,
) -> None:
    """Verifie le domaine fixe sans modifier les fichiers .env locaux."""
    if not mobile_env.exists():
        raise DevPayUError("mobile/.env est introuvable. Copiez mobile/.env.example puis renseignez l'API publique.")

    backend_url = normalize_url(read_env(backend_env).get("PUBLIC_API_URL"))
    mobile_url = normalize_url(read_env(mobile_env).get("EXPO_PUBLIC_API_URL"))
    if backend_url != FIXED_PUBLIC_API_URL:
        raise DevPayUError("PUBLIC_API_URL doit utiliser https://api-dev.kwitli.app.")
    if mobile_url != FIXED_PUBLIC_API_URL:
        raise DevPayUError("EXPO_PUBLIC_API_URL doit utiliser https://api-dev.kwitli.app.")


def parse_health_payload(raw_payload: str) -> HealthcheckResult:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return HealthcheckResult(False, "reponse HTTP 200 non JSON")
    if isinstance(payload, dict) and payload.get("status") == "ok" and payload.get("app") == "Kwitli":
        return HealthcheckResult(True, "Kwitli OK")
    return HealthcheckResult(False, "reponse HTTP 200 non reconnue comme Kwitli")


def healthcheck_result(url: str, timeout: float = 2.0) -> HealthcheckResult:
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310 - URL controlee par le workflow.
            if response.status != 200:
                return HealthcheckResult(False, f"HTTP {response.status}")
            try:
                payload = response.read().decode("utf-8")
            except UnicodeDecodeError:
                return HealthcheckResult(False, "reponse HTTP 200 non JSON")
            return parse_health_payload(payload)
    except HTTPError as error:
        return HealthcheckResult(False, f"HTTP {error.code}")
    except URLError as error:
        return HealthcheckResult(False, f"erreur de connexion: {error.reason}")
    except OSError as error:
        return HealthcheckResult(False, f"erreur reseau: {error}")


def curl_healthcheck_result(
    url: str,
    *,
    timeout: int = 5,
    curl_path: str | None = None,
    runner=subprocess.run,
) -> HealthcheckResult:
    curl = curl_path or shutil.which("curl")
    if curl is None:
        return HealthcheckResult(False, "curl indisponible")
    try:
        result = runner(
            [curl, "-fsS", "--max-time", str(timeout), url],
            capture_output=True,
            text=True,
            timeout=timeout + 1,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return HealthcheckResult(False, f"erreur curl: {error}")
    if result.returncode != 0:
        return HealthcheckResult(False, f"curl exited (code {result.returncode})")
    return parse_health_payload(result.stdout)


def healthcheck_with_fallback(
    url: str,
    *,
    python_check=healthcheck_result,
    curl_check=curl_healthcheck_result,
) -> HealthcheckResult:
    result = python_check(url)
    if result.ok:
        return result
    # Cloudflare peut refuser l'agent par defaut de urllib tout en servant curl.
    return curl_check(url)


def healthcheck(url: str, timeout: float = 2.0) -> bool:
    return healthcheck_result(url, timeout).ok


def wait_for_health(url: str, timeout: float, process: subprocess.Popen[str] | None = None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return False
        if healthcheck(url):
            return True
        time.sleep(0.5)
    return False


def wait_for_public_health(
    url: str = FIXED_PUBLIC_HEALTH_URL,
    *,
    attempts: int = 30,
    delay: float = 2.0,
    check=healthcheck_with_fallback,
    sleep=time.sleep,
    output=print,
) -> None:
    """Attend le routage du tunnel nomme sans bloquer sur le DNS de Python seul."""
    last_reason = "aucune tentative effectuee"
    output("Waiting for public tunnel...")
    for attempt in range(1, attempts + 1):
        output(f"Public healthcheck attempt {attempt}/{attempts}")
        result = check(url)
        if result.ok:
            output("Public healthcheck OK")
            return
        last_reason = result.reason
        if attempt < attempts:
            sleep(delay)
    raise DevPayUError(
        "Le tunnel fixe kwitli-dev n'est pas connecte ou ne repond pas au healthcheck public "
        f"apres {attempts} tentatives: {last_reason}."
    )


def port_is_open(host: str = "127.0.0.1", port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.5)
        return connection.connect_ex((host, port)) == 0


def stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3.0)


def start_backend() -> subprocess.Popen[str] | None:
    if port_is_open():
        if healthcheck(LOCAL_HEALTH_URL):
            return None
        raise DevPayUError("Le port 8000 est occupe par un service qui ne repond pas au healthcheck Kwitli.")
    python_path = ROOT_DIR / ".venv" / "bin" / "python"
    if not python_path.exists():
        raise DevPayUError("Le Python .venv/bin/python est introuvable.")
    process = subprocess.Popen(
        [
            str(python_path), "-m", "uvicorn", "backend.main:app",
            "--host", "0.0.0.0", "--port", "8000", "--no-access-log",
        ],
        cwd=ROOT_DIR,
        text=True,
    )
    if not wait_for_health(LOCAL_HEALTH_URL, timeout=20.0, process=process):
        stop_process(process)
        raise DevPayUError("FastAPI n'a pas repondu au healthcheck local.")
    return process


def start_expo() -> subprocess.Popen[str] | None:
    npx = shutil.which("npx")
    if npx is None:
        print("Expo non lance: installez Node.js puis executez npx expo start dans mobile/.")
        return None
    return subprocess.Popen([npx, "expo", "start"], cwd=ROOT_DIR / "mobile", text=True)


def display_status() -> None:
    print(f"Public API: {FIXED_PUBLIC_API_URL}")
    print(f"PayU confirmation: {FIXED_PUBLIC_API_URL}/api/v1/payments/payu/confirmation")
    print(f"PayU response: {FIXED_PUBLIC_API_URL}/api/v1/payments/payu/response")
    print("Backend: running")
    print("Tunnel kwitli-dev: connected")
    print("PayU sandbox: ready")


def run(*, expo: bool = False) -> int:
    validate_payu_environment()
    validate_fixed_public_urls()
    backend_process: subprocess.Popen[str] | None = None
    expo_process: subprocess.Popen[str] | None = None
    try:
        backend_process = start_backend()
        wait_for_public_health()
        display_status()
        if expo:
            expo_process = start_expo()
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Arret du workflow PayU local.")
        return 0
    except DevPayUError as error:
        print(f"Erreur: {error}", file=sys.stderr)
        return 1
    finally:
        stop_process(expo_process)
        stop_process(backend_process)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lance Kwitli avec le tunnel Cloudflare nomme kwitli-dev.")
    parser.add_argument("--expo", action="store_true", help="Lance aussi Expo dans mobile/.")
    return run(expo=parser.parse_args().expo)


if __name__ == "__main__":
    sys.exit(main())
