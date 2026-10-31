from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
from ipaddress import ip_address
from math import ceil
from threading import RLock
import time

from fastapi import HTTPException, Request, status
from starlette.responses import JSONResponse

from backend.app.core.config import Settings, get_settings


class InMemoryRateLimiter:
    """Limiteur local borne pour le MVP mono-processus."""

    def __init__(
        self,
        *,
        max_buckets: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_buckets = max_buckets
        self._clock = clock
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = RLock()

    def consume(self, key: str, *, limit: int, window_seconds: int) -> int | None:
        """Retourne le delai de retry si le quota est depasse, sinon None."""
        now = self._clock()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self._max_buckets:
                    # Retirer d'abord les compteurs expires : un flot de nouvelles
                    # cles ne doit pas effacer un compteur encore actif.
                    expired = [name for name, values in self._buckets.items() if not values or values[-1] <= cutoff]
                    for name in expired:
                        del self._buckets[name]
                if len(self._buckets) >= self._max_buckets:
                    self._buckets.popitem(last=False)
                bucket = deque()
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return max(1, ceil(bucket[0] + window_seconds - now))
            bucket.append(now)
            return None


def client_identifier(request: Request, settings: Settings) -> str:
    direct_host = request.client.host if request.client is not None else "unknown"
    return resolved_client_identifier(
        direct_host,
        request.headers.get("CF-Connecting-IP", ""),
        settings,
    )


def resolved_client_identifier(
    direct_host: str,
    cloudflare_ip: str,
    settings: Settings,
) -> str:
    trusted_proxies = {
        value.strip() for value in settings.trusted_proxy_ips.split(",") if value.strip()
    }
    if direct_host in trusted_proxies:
        try:
            return str(ip_address(cloudflare_ip.strip()))
        except ValueError:
            pass
    return direct_host


class UploadSecurityMiddleware:
    """Borne et limite les uploads avant le parsing multipart de FastAPI."""

    def __init__(
        self,
        app,
        *,
        limiter: InMemoryRateLimiter,
        settings: Settings,
    ) -> None:
        self.app = app
        self._limiter = limiter
        self._settings = settings
        self._max_catalog_body_bytes = settings.upload_max_bytes + 64 * 1024
        self._max_kyb_body_bytes = settings.kyb_max_document_bytes + 64 * 1024

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or not self._is_upload_path(scope["path"]):
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", ())
        }
        is_kyb_upload = self._is_kyb_upload_path(scope["path"])
        max_body_bytes = self._max_kyb_body_bytes if is_kyb_upload else self._max_catalog_body_bytes
        direct_host = scope.get("client", ("unknown", 0))[0]
        identity = resolved_client_identifier(
            direct_host,
            headers.get("cf-connecting-ip", ""),
            self._settings,
        )
        retry_after = self._limiter.consume(
            f"uploads-ingress:ip:{identity}",
            limit=self._settings.rate_limit_upload_requests,
            window_seconds=self._settings.rate_limit_window_seconds,
        )
        if retry_after is not None:
            await self._response(429, "Trop de requetes. Reessayez plus tard.", send, retry_after)
            return

        try:
            content_length = int(headers.get("content-length", "0"))
        except ValueError:
            content_length = 0
        if content_length > max_body_bytes:
            await self._response(413, "Fichier trop volumineux." if is_kyb_upload else "Image trop volumineuse.", send)
            return

        received_bytes = 0
        messages = deque()
        while True:
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > max_body_bytes:
                    await self._response(413, "Fichier trop volumineux." if is_kyb_upload else "Image trop volumineuse.", send)
                    return
                messages.append(message)
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                return

        async def replay_receive():
            if messages:
                return messages.popleft()
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    def _is_upload_path(self, path: str) -> bool:
        prefix = self._settings.api_v1_prefix
        return path == f"{prefix}/cooks/me/photo" or (
            path.startswith(f"{prefix}/dishes/") and path.endswith("/photo")
        ) or self._is_kyb_upload_path(path)

    def _is_kyb_upload_path(self, path: str) -> bool:
        return path.startswith(f"{self._settings.api_v1_prefix}/kyb/cases/") and path.endswith("/documents")

    @staticmethod
    async def _response(status_code: int, detail: str, send, retry_after: int | None = None) -> None:
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        response = JSONResponse({"detail": detail}, status_code=status_code, headers=headers)
        await response({"type": "http"}, None, send)


def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    limit: int,
    user_id: str | None = None,
    subject: str | None = None,
) -> None:
    settings = get_settings()
    if subject is not None:
        identity = f"subject:{subject}"
    elif user_id is not None:
        identity = f"user:{user_id}"
    else:
        identity = f"ip:{client_identifier(request, settings)}"
    limiter: InMemoryRateLimiter = request.app.state.rate_limiter
    retry_after = limiter.consume(
        f"{scope}:{identity}",
        limit=limit,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de requetes. Reessayez plus tard.",
            headers={"Retry-After": str(retry_after)},
        )
