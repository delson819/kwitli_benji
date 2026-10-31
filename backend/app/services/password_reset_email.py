import json
import logging
import socket
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from backend.app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_SAFE_RESEND_ERROR_CODES = {
    "domain_not_verified",
    "from_domain_not_verified",
    "internal_server_error",
    "invalid_api_key",
    "missing_api_key",
    "not_found",
    "rate_limit_exceeded",
    "restricted_api_key",
    "validation_error",
}


def _safe_http_error_code(error: HTTPError) -> str:
    """Return only a recognized machine code; never expose provider text."""
    try:
        payload = json.loads(error.read(16_384))
    except Exception:
        return "unavailable"

    if not isinstance(payload, dict):
        return "unavailable"
    error_data = payload.get("error", payload)
    if not isinstance(error_data, dict):
        return "unavailable"

    # Resend error responses commonly expose a machine-readable `name`; some
    # intermediaries use `code`. Only log known values, never arbitrary text.
    candidate = error_data.get("name", error_data.get("code"))
    if isinstance(candidate, str) and candidate in _SAFE_RESEND_ERROR_CODES:
        return candidate
    return "unrecognized"


class PasswordResetEmailSender(Protocol):
    @property
    def is_configured(self) -> bool: ...

    def send_password_reset(self, email: str, token: str) -> None: ...


class UnconfiguredPasswordResetEmailSender:
    """Aucun fournisseur n'est actif tant qu'un choix explicite n'a pas ete fait."""

    is_configured = False

    def send_password_reset(self, email: str, token: str) -> None:
        raise RuntimeError("Aucun service d'envoi de courriel n'est configure.")


class PasswordResetEmailDeliveryError(RuntimeError):
    """Échec d'envoi sans inclure de secret ou de contenu fournisseur."""


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        original = urlsplit(request.full_url)
        redirected = urlsplit(new_url)
        original_scheme = original.scheme.lower()
        redirected_scheme = redirected.scheme.lower()
        original_origin = (
            original_scheme,
            (original.hostname or "").lower(),
            original.port or (443 if original_scheme == "https" else 80),
        )
        redirected_origin = (
            redirected_scheme,
            (redirected.hostname or "").lower(),
            redirected.port or (443 if redirected_scheme == "https" else 80),
        )
        if original_origin != redirected_origin:
            raise HTTPError(request.full_url, code, "Cross-origin redirect refused", headers, fp)
        return super().redirect_request(request, fp, code, message, headers, new_url)


class ResendPasswordResetEmailSender:
    endpoint = "https://api.resend.com/emails"
    default_sender = "Kwitli <noreply@mail.kwitli.app>"

    def __init__(
        self,
        settings: Settings,
        opener: Callable[..., object] | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self._settings = settings
        self._opener = opener or build_opener(_SameOriginRedirectHandler()).open
        self._timeout_seconds = timeout_seconds

    @property
    def sender(self) -> str:
        return self._settings.resend_from_email.strip() or self.default_sender

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.resend_api_key.get_secret_value().strip())

    def send_password_reset(self, email: str, token: str) -> None:
        api_key = self._settings.resend_api_key.get_secret_value().strip()
        if not api_key:
            raise PasswordResetEmailDeliveryError("Envoi de courriel non configure.")

        base_url = self._settings.password_reset_app_url.strip()
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"kwitli", "https"} or not parsed.netloc or parsed.fragment:
            raise PasswordResetEmailDeliveryError("Lien de récupération mal configuré.")

        reset_url = f"{base_url}{'&' if parsed.query else '?'}{urlencode({'token': token})}"
        safe_url = reset_url.replace("&", "&amp;").replace('"', "&quot;")
        expiry = self._settings.password_reset_token_expire_minutes
        text_body = (
            "Vous avez demandé à réinitialiser le mot de passe de votre compte Kwitli.\n\n"
            f"Ouvrez ce lien pour choisir un nouveau mot de passe : {reset_url}\n\n"
            "Ouvrez ce courriel sur un iPhone ou un appareil Android où Kwitli est installé. "
            "Le lien ne s'ouvre pas dans Safari sur ordinateur.\n\n"
            f"Ce lien est valide pendant {expiry} minutes et ne peut être utilisé qu'une fois.\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message."
        )
        html_body = (
            "<div style=\"font-family:Arial,sans-serif;color:#173b35;max-width:560px;margin:auto\">"
            "<h1>Kwitli</h1><p>Vous avez demandé à réinitialiser le mot de passe de votre compte.</p>"
            f"<p><a href=\"{safe_url}\" style=\"display:inline-block;padding:12px 20px;"
            "background:#004c40;color:white;text-decoration:none;border-radius:8px\">"
            "Choisir un nouveau mot de passe</a></p>"
            "<p>Ouvrez ce courriel sur un iPhone ou un appareil Android où Kwitli est installé. "
            "Le lien ne s'ouvre pas dans Safari sur ordinateur.</p>"
            f"<p>Ce lien est valide pendant {expiry} minutes et ne peut être utilisé qu'une seule fois.</p>"
            "<p>Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.</p></div>"
        )
        payload = json.dumps({
            "from": self.sender,
            "to": [email],
            "subject": "Réinitialiser votre mot de passe Kwitli",
            "text": text_body,
            "html": html_body,
        }).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "kwitli/1.0",
            },
            method="POST",
        )

        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                if response.status != 200:
                    logger.warning(
                        "Password reset email delivery failed category=provider_http status_code=%s",
                        int(response.status),
                    )
                    raise PasswordResetEmailDeliveryError("Échec de l'envoi du courriel de récupération.")
                result = json.loads(response.read())
            if not isinstance(result, dict) or not isinstance(result.get("id"), str) or not result["id"]:
                logger.warning("Password reset email delivery failed category=invalid_response")
                raise PasswordResetEmailDeliveryError("Réponse Resend invalide.")
        except HTTPError as exc:
            safe_code = _safe_http_error_code(exc)
            logger.warning(
                "Password reset email delivery failed category=provider_http "
                "response_origin=unverified status_code=%s provider_error_code=%s",
                int(exc.code),
                safe_code,
            )
            raise PasswordResetEmailDeliveryError("Échec de l'envoi du courriel de récupération.") from None
        except (TimeoutError, socket.timeout):
            logger.warning("Password reset email delivery failed category=timeout")
            raise PasswordResetEmailDeliveryError("Échec de l'envoi du courriel de récupération.") from None
        except URLError as exc:
            category = "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "network_error"
            logger.warning("Password reset email delivery failed category=%s", category)
            raise PasswordResetEmailDeliveryError("Échec de l'envoi du courriel de récupération.") from None
        except PasswordResetEmailDeliveryError:
            raise
        except (OSError,):
            logger.warning("Password reset email delivery failed category=network_error")
            raise PasswordResetEmailDeliveryError("Échec de l'envoi du courriel de récupération.") from None
        except (ValueError, TypeError, UnicodeError):
            logger.warning("Password reset email delivery failed category=invalid_response")
            raise PasswordResetEmailDeliveryError("Échec de l'envoi du courriel de récupération.") from None
        except Exception:
            logger.warning("Password reset email delivery failed category=unexpected_error")
            raise PasswordResetEmailDeliveryError("Échec de l'envoi du courriel de récupération.") from None


def get_password_reset_email_sender() -> PasswordResetEmailSender:
    sender = ResendPasswordResetEmailSender(get_settings())
    return sender if sender.is_configured else UnconfiguredPasswordResetEmailSender()
