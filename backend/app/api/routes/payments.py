from html import escape
import json
from decimal import Decimal
import logging
import re
import secrets
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from backend.app.core.config import get_settings
from backend.app.dependencies import get_current_user, get_payment_service
from backend.app.persistence.models import User
from backend.app.rate_limit import enforce_rate_limit
from backend.app.schemas.payments import PaymentConfirmationResponse, PaymentCreateRequest, PaymentResponse
from backend.app.services.marketplace import AuthorizationError, ConflictError, NotFoundError
from backend.app.services.payments.service import PaymentLimitError, PaymentService
from backend.app.services.payments.payu import PayUValidationError
from backend.app.services.payments.provider import ProviderError, InvalidProviderConfirmation
from backend.app.services.payments.flutterwave import FlutterwaveProvider

router = APIRouter(prefix="/payments", tags=["payments"])
logger = logging.getLogger(__name__)


def unique_json_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


@router.post("/flutterwave/webhook", response_model=PaymentConfirmationResponse)
async def flutterwave_webhook(request: Request, service: PaymentService = Depends(get_payment_service)):
    try:
        FlutterwaveProvider(get_settings()).verify_webhook_secret(request.headers.get("verif-hash"))
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536:
                raise HTTPException(status_code=413, detail="Notification trop volumineuse.")
        payload = json.loads(raw, object_pairs_hook=unique_json_fields, parse_float=Decimal)
        if not isinstance(payload, dict):
            raise ValueError()
        await run_in_threadpool(service.process_flutterwave_confirmation, payload)
        return {"received": True}
    except (ValueError, UnicodeError):
        raise HTTPException(status_code=400, detail="Notification invalide.") from None
    except InvalidProviderConfirmation:
        raise HTTPException(status_code=403, detail="Notification Flutterwave invalide.") from None
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Paiement inconnu.") from None
    except ProviderError:
        raise HTTPException(status_code=503, detail="Verification Flutterwave indisponible.") from None


@router.post("/paytech/confirmation", response_model=PaymentConfirmationResponse)
async def paytech_confirmation(request: Request, service: PaymentService = Depends(get_payment_service)):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 65536:
            raise HTTPException(status_code=413, detail="Notification trop volumineuse.")
    try:
        if request.headers.get("content-type", "").split(";")[0] == "application/json":
            payload = json.loads(raw, object_pairs_hook=unique_json_fields, parse_float=Decimal)
            if not isinstance(payload, dict):
                raise ValueError()
        else:
            parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=100)
            if any(len(values) != 1 for values in parsed.values()):
                raise ValueError()
            payload = {key: values[0] for key, values in parsed.items()}
        await run_in_threadpool(service.process_paytech_confirmation, payload)
        return {"received": True}
    except (ValueError, UnicodeError):
        raise HTTPException(status_code=400, detail="Notification invalide.") from None
    except InvalidProviderConfirmation:
        raise HTTPException(status_code=403, detail="Notification PayTech invalide.") from None
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Paiement inconnu.") from None
    except ProviderError:
        raise HTTPException(status_code=503, detail="Verification PayTech indisponible.") from None


@router.get("/paytech/return", response_class=HTMLResponse, include_in_schema=False)
def paytech_return():
    # Le retour navigateur ne modifie jamais un paiement.
    return HTMLResponse("<!doctype html><html><body><p>Retournez dans KWITLI pour verifier le paiement.</p></body></html>",
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                 "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"})


def public_payment_url(path: str) -> str:
    configured_base = get_settings().public_api_url.rstrip("/")
    if not configured_base:
        raise PayUValidationError("PUBLIC_API_URL HTTPS est requis pour le checkout PayU.")
    return f"{configured_base}{path}"


def payment_response(payment, checkout_url: str | None = None) -> dict:
    return {
        "id": payment.id, "order_id": payment.order_id, "availability_id": payment.availability_id, "quantity": payment.quantity,
        "amount_in_cents": payment.amount_in_cents, "currency": payment.currency, "provider": payment.provider,
        "provider_reference": payment.provider_reference, "status": payment.status,
        "checkout_url": checkout_url or getattr(payment, "checkout_url", None),
        "created_at": payment.created_at, "approved_at": payment.approved_at, "declined_at": payment.declined_at,
        "items": payment.items,
        "next_action": getattr(payment, "next_action", None),
    }


@router.post("", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: PaymentCreateRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=128),
    current_user: User = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentResponse:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", idempotency_key):
        raise HTTPException(status_code=422, detail="Clé d’idempotence invalide.")
    enforce_rate_limit(
        request,
        scope="payments-create",
        limit=get_settings().rate_limit_payment_requests,
        user_id=current_user.id,
    )
    try:
        payment, checkout_url = service.create_payment(payload, current_user, idempotency_key)
        return payment_response(payment, checkout_url)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(get_settings().payment_hold_minutes * 60)},
        ) from exc
    except (PayUValidationError, ProviderError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/by-tx-ref/{tx_ref}", response_model=PaymentResponse)
def get_payment_by_reference(tx_ref: str, request: Request, current_user: User = Depends(get_current_user), service: PaymentService = Depends(get_payment_service)) -> PaymentResponse:
    try:
        payment = service.get_payment_by_reference_for_user(tx_ref, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return get_payment(payment.id, request, current_user, service)


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: str, request: Request, current_user: User = Depends(get_current_user), service: PaymentService = Depends(get_payment_service)) -> PaymentResponse:
    try:
        payment = service.get_payment_for_user(payment_id, current_user)
        if payment.provider == "paydunya":
            enforce_rate_limit(request, scope="paydunya-status", limit=get_settings().rate_limit_payment_requests, user_id=current_user.id)
            payment = service.refresh_paydunya(payment)
        if payment.provider == "flutterwave" and payment.status == "pending":
            enforce_rate_limit(request, scope="flutterwave-status", limit=get_settings().rate_limit_payment_requests, user_id=current_user.id)
            payment = service.refresh_flutterwave(payment)
        payment, checkout_url = service.restore_payment_action(payment)
        return payment_response(payment, checkout_url)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{payment_id}/paydunya/test-payment", response_model=PaymentResponse)
def paydunya_test_payment(payment_id: str, request: Request, current_user: User = Depends(get_current_user),
                         service: PaymentService = Depends(get_payment_service)):
    enforce_rate_limit(request, scope="paydunya-test", limit=get_settings().rate_limit_payment_requests, user_id=current_user.id)
    try:
        return payment_response(service.paydunya_test_payment(payment_id, current_user))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/paydunya/confirmation", response_model=PaymentConfirmationResponse)
async def paydunya_confirmation(request: Request, service: PaymentService = Depends(get_payment_service)):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 65536:
            raise HTTPException(status_code=413, detail="Confirmation trop volumineuse.")
    try:
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=200)
        if any(len(values) != 1 for values in parsed.values()):
            raise ValueError()
        await run_in_threadpool(service.process_paydunya_confirmation, {key: values[0] for key, values in parsed.items()})
        return {"received": True}
    except (UnicodeError, ValueError):
        raise HTTPException(status_code=400, detail="Confirmation invalide.") from None
    except InvalidProviderConfirmation:
        raise HTTPException(status_code=403, detail="Confirmation PayDunya invalide.") from None
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Facture inconnue.") from None
    except ProviderError:
        raise HTTPException(status_code=503, detail="Verification PayDunya indisponible.") from None


def payu_relay(payment_id: str, token: str, service: PaymentService) -> HTMLResponse:
    try:
        action, fields = service.get_payu_checkout_fields(
            payment_id,
            token,
            public_payment_url("/api/v1/payments/payu/confirmation"),
            public_payment_url("/api/v1/payments/payu/response"),
        )
        inputs = "".join(f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">' for name, value in fields.items())
        nonce = secrets.token_urlsafe(16)
        response = HTMLResponse(f'<!doctype html><html><body><form id="payu-checkout" method="post" action="{escape(action)}">{inputs}</form><script nonce="{nonce}">document.getElementById("payu-checkout").submit();</script></body></html>')
        response.headers["Content-Security-Policy"] = (
            f"default-src 'none'; script-src 'nonce-{nonce}'; "
            f"form-action {escape(action)}; base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PayUValidationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{payment_id}/payu/checkout", response_class=HTMLResponse, include_in_schema=False)
def payu_checkout(payment_id: str) -> HTMLResponse:
    nonce = secrets.token_urlsafe(16)
    action = f"/api/v1/payments/{escape(payment_id)}/payu/checkout"
    html = (
        '<!doctype html><html><body><form id="checkout-token" method="post" '
        f'action="{action}"><input id="token" type="hidden" name="token"></form>'
        f'<script nonce="{nonce}">'
        'const value=new URLSearchParams(window.location.hash.slice(1)).get("token");'
        'if(!value){document.body.textContent="Enlace de pago inválido.";}else{'
        'document.getElementById("token").value=value;history.replaceState(null,"",window.location.pathname);'
        'document.getElementById("checkout-token").submit();}</script></body></html>'
    )
    response = HTMLResponse(html)
    response.headers["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/{payment_id}/payu/checkout", response_class=HTMLResponse, include_in_schema=False)
def submit_payu_checkout(
    payment_id: str,
    token: str = Form(...),
    service: PaymentService = Depends(get_payment_service),
) -> HTMLResponse:
    return payu_relay(payment_id, token, service)


@router.get("/payu/response", response_class=HTMLResponse, include_in_schema=False)
def payu_response() -> HTMLResponse:
    # La confirmation serveur PayU reste l'unique source de verite du paiement.
    return HTMLResponse("<!doctype html><html><body><p>Tu pago esta siendo confirmado.</p></body></html>")


@router.post("/payu/confirmation", response_model=PaymentConfirmationResponse, name="payu_confirmation")
async def payu_confirmation(request: Request, service: PaymentService = Depends(get_payment_service)) -> PaymentConfirmationResponse:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 65536:
            raise HTTPException(status_code=413, detail="Confirmation trop volumineuse.")
    try:
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=200)
        if any(len(values) != 1 for values in parsed.values()):
            raise ValueError()
        payload = {key: values[0] for key, values in parsed.items()}
        await run_in_threadpool(service.process_payu_confirmation, payload)
        return {"received": True}
    except (UnicodeError, ValueError):
        raise HTTPException(status_code=400, detail="Confirmation invalide.") from None
    except PayUValidationError as exc:
        logger.warning("Confirmation PayU rejetee: %s", exc)
        raise HTTPException(status_code=403, detail="Confirmation PayU invalide.") from exc
