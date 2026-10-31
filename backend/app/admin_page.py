from html import escape
import hashlib
import hmac
from ipaddress import ip_address
import time
from datetime import date, datetime, time as datetime_time, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.core.service_areas import ServiceAreaInput, environment_scope
from backend.app.database import get_db_session
from backend.app.dependencies import get_marketplace_service
from backend.app.kyb.policies import get_policy
from backend.app.kyb.security import KybSecurityError, decrypt_document, private_path
from backend.app.persistence.models import (
    CookProfile, MerchantVerificationCase, MerchantVerificationDocument,
    MerchantVerificationEvent, User,
)
from backend.app.repositories.service_areas import (
    ServiceAreaConflictError, ServiceAreaNotFoundError, SqlAlchemyServiceAreaRepository,
)
from fastapi.responses import Response
from pathlib import Path
from sqlalchemy.orm import Session
from backend.app.rate_limit import enforce_rate_limit
from backend.app.services.marketplace import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    MarketplaceService,
    NotFoundError,
)

router = APIRouter(tags=["admin html"])
basic_auth = HTTPBasic(auto_error=False)
CSRF_TOKEN_TTL_SECONDS = 15 * 60


def _authenticate_admin(
    request: Request,
    credentials: HTTPBasicCredentials | None,
    service: MarketplaceService,
) -> User:
    client_host = request.client.host if request.client is not None else ""
    try:
        is_loopback = ip_address(client_host).is_loopback
    except ValueError:
        is_loopback = get_settings().app_env.strip().lower() == "test" and client_host == "testclient"
    if request.url.scheme != "https" and not is_loopback:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Introuvable.")

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise.",
            headers={"WWW-Authenticate": 'Basic realm="Kwitli Admin"'},
        )
    try:
        user = service.authenticate(credentials.username, credentials.password)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants invalides.",
            headers={"WWW-Authenticate": 'Basic realm="Kwitli Admin"'},
        ) from exc
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès réservé à l’administration Kwitli.")
    return user


def _csrf_token(admin_id: str, cook_id: str, action: str) -> str:
    expires = int(time.time()) + CSRF_TOKEN_TTL_SECONDS
    message = f"{admin_id}:{cook_id}:{action}:{expires}".encode()
    signature = hmac.new(get_settings().secret_key.encode(), message, hashlib.sha256).hexdigest()
    return f"{expires}.{signature}"


def _valid_csrf_token(token: str, admin_id: str, cook_id: str, action: str) -> bool:
    try:
        expires_text, supplied_signature = token.split(".", 1)
        expires = int(expires_text)
    except (ValueError, TypeError):
        return False
    now = int(time.time())
    if expires < now or expires > now + CSRF_TOKEN_TTL_SECONDS:
        return False
    message = f"{admin_id}:{cook_id}:{action}:{expires}".encode()
    expected = hmac.new(get_settings().secret_key.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied_signature, expected)


def _action_form(admin_id: str, restaurant: dict, action: str, label: str) -> str:
    token = escape(_csrf_token(admin_id, restaurant["id"], action))
    cook_id = escape(restaurant["id"])
    reason_field = ""
    if action == "reject":
        reason_field = '<label>Raison du refus <textarea name="reason" required maxlength="1000"></textarea></label>'
    elif action == "suspend":
        reason_field = '<label>Motif (facultatif) <input name="reason" maxlength="1000"></label>'
    disabled = ' disabled title="Complétez la checklist avant approbation"' if action == "approve" and not restaurant["ready"] else ""
    return (
        f'<form method="post" action="/admin/restaurants/{cook_id}/decision">'
        f'<input type="hidden" name="action" value="{action}">'
        f'<input type="hidden" name="csrf_token" value="{token}">'
        f'{reason_field}<button type="submit"{disabled}>{label}</button></form>'
    )


def _restaurant_card(admin_id: str, restaurant: dict) -> str:
    checks = {
        "Nom rempli": bool((restaurant["display_name"] or "").strip()),
        "Description remplie": bool((restaurant["bio"] or "").strip()),
        "Point GPS présent": restaurant["latitude"] is not None and restaurant["longitude"] is not None,
        "Point GPS dans une zone commerciale active": restaurant["service_area_eligible"],
        "Horaires configurés (7 jours)": restaurant["hours_configured"],
        "Au moins un article actif": restaurant["active_dish_count"] > 0,
        "Compte propriétaire actif": restaurant["owner_active"],
    }
    checklist = "<ul>" + "".join(
        f"<li>{'✓' if checked else '—'} {escape(label)}</li>" for label, checked in checks.items()
    ) + "</ul>"
    actions = ""
    if restaurant["approval_status"] == "pending_review":
        actions = _action_form(admin_id, restaurant, "approve", "Approuver")
        actions += _action_form(admin_id, restaurant, "reject", "Refuser")
    elif restaurant["approval_status"] == "approved":
        actions = _action_form(admin_id, restaurant, "suspend", "Suspendre")
    elif restaurant["approval_status"] == "suspended":
        actions = _action_form(admin_id, restaurant, "reactivate", "Réactiver / approuver")

    reason = (
        f'<p>Motif enregistré : {escape(restaurant["approval_reason"])}</p>'
        if restaurant["approval_reason"] else ""
    )
    service_area_notice = (
        "<p>Restaurant situé hors des zones commerciales actuellement actives</p>"
        if restaurant["outside_active_service_area"] else ""
    )
    return f"""<article>
<h3>{escape(restaurant['display_name'])}</h3>
<p>Propriétaire : {escape(restaurant['owner_email'])}</p>
<p>Description : {escape(restaurant['bio'] or 'Non renseignée')}</p>
<p>Point de retrait : {escape(str(restaurant['latitude']))}, {escape(str(restaurant['longitude']))}</p>
<p>Horaires configurés : {'Oui' if restaurant['hours_configured'] else 'Non'} ({restaurant['hours_count']}/7 jours)</p>
<p>Articles actifs : {restaurant['active_dish_count']}</p>
<p>Compte propriétaire actif : {'Oui' if restaurant['owner_active'] else 'Non'}</p>
<p>Statut : <strong>{escape(restaurant['approval_status'])}</strong></p>{reason}{service_area_notice}
<h4>Prêt à valider</h4>{checklist}<p>{'Fiche complète' if restaurant['ready'] else 'Fiche à compléter avant approbation'}</p>
<div>{actions}</div></article>"""



def _kyb_section(session: Session, admin_id: str) -> str:
    cases = session.scalars(select(MerchantVerificationCase).order_by(
        MerchantVerificationCase.created_at.desc()).limit(100)).all()
    cards = []
    for case in cases:
        cook = session.get(CookProfile, case.cook_profile_id)
        owner = session.get(User, cook.user_id) if cook else None
        docs = session.scalars(select(MerchantVerificationDocument).where(
            MerchantVerificationDocument.case_id == case.id
        ).order_by(MerchantVerificationDocument.uploaded_at)).all()
        documents = "".join(
            f"<li>{escape(doc.requirement_code)} — {escape('expired' if doc.expires_at and doc.expires_at <= datetime.now(timezone.utc) else doc.status)} — analyse: {escape(doc.scan_status)} "
            f"<a href=\"/admin/kyb/documents/{escape(doc.id)}\">Consulter la pièce</a> "
            f"<form method=\"post\" action=\"/admin/kyb/documents/{escape(doc.id)}/verification\">"
            f"<input type=\"hidden\" name=\"csrf_token\" value=\"{escape(_csrf_token(admin_id, case.id, 'kyb-document-review'))}\">"
            "<label>Méthode <select name=\"method\"><option value=\"visual_review\">Examen visuel</option>"
            "<option value=\"authorized_source\">Source autorisée</option></select></label>"
            "<label>Source (si utilisée) <select name=\"source\"><option value=\"\">Aucune</option>"
            "<option value=\"official_registry\">Registre officiel</option><option value=\"government_portal\">Portail gouvernemental</option>"
            "<option value=\"authorized_issuer\">Émetteur autorisé</option><option value=\"other_authorized_source\">Autre source autorisée</option></select></label>"
            "<label>Résultat <select name=\"result\"><option value=\"consistent\">Cohérent visuellement</option>"
            "<option value=\"confirmed\">Confirmé par source</option><option value=\"not_verifiable\">Non vérifiable</option>"
            "<option value=\"mismatch\">Incohérence</option></select></label>"
            "<label>Expiration indiquée par la pièce (si la politique le permet) <input type=\"date\" name=\"expires_on\"></label>"
            "<button>Enregistrer l'examen</button></form></li>"
            for doc in docs
        ) or "<li>Aucune pièce déposée.</li>"
        actions = "".join(
            f"<form method=\"post\" action=\"/admin/kyb/{escape(case.id)}/decision\">"
            f"<input type=\"hidden\" name=\"csrf_token\" value=\"{escape(_csrf_token(admin_id, case.id, 'kyb-decision'))}\">"
            f"<input type=\"hidden\" name=\"action\" value=\"{action}\">"
            f"<label>Code de motif <input name=\"reason_code\" maxlength=\"80\" {'required' if action in {'request_correction','reject','suspend'} else ''}></label>"
            + ("<label>Code de pièce supplémentaire <input name=\"additional_code\" maxlength=\"80\" required></label>"
               "<label>Libellé de la pièce <input name=\"additional_label\" maxlength=\"120\" required></label>"
               if action == "request_correction" else "")
            + f"<button>{label}</button></form>"
            for action, label in (("under_review", "Prendre en vérification"),
                                  ("request_correction", "Demander une correction"),
                                  ("approve", "Approuver KYB"), ("reject", "Refuser KYB"),
                                  ("suspend", "Suspendre KYB"), ("reactivate", "Réactiver KYB"))
            if (action == "under_review" and case.status == "submitted"
                or action == "request_correction" and case.status in {"submitted", "under_review"}
                or action == "approve" and case.status in {"submitted", "under_review"}
                or action == "reject" and case.status in {"submitted", "under_review", "correction_required"}
                or action == "suspend" and case.status == "approved"
                or action == "reactivate" and case.status == "suspended")
        )
        legal = escape(case.policy_snapshot.get("legal_review", "pending_legal_review"))
        cards.append(f"""<article><h3>{escape(cook.display_name if cook else 'Commerce indisponible')}</h3>
<p>Propriétaire : {escape(owner.email if owner else 'Indisponible')}</p>
<p>Juridiction : {escape(case.country_code)} / {escape(case.jurisdiction_code)}; statut KYB : <strong>{escape(case.status)}</strong></p>
<p>Politique : {escape(case.policy_version)} — revue juridique : {legal}</p>
<p>Une pièce déposée n'est pas présumée authentique. « Examen visuel » ne signifie pas vérification officielle.</p>
<ul>{documents}</ul><p>Historique :</p><ul>{_kyb_event_list(session, case.id)}</ul>{actions}</article>""")
    return "<section><h2>Dossiers KYB</h2><p>Les décisions KYB sont distinctes de l'approbation commerciale. La politique Sénégal reste en revue juridique.</p>" + ("".join(cards) or "<p>Aucun dossier KYB.</p>") + "</section>"


def _kyb_event_list(session: Session, case_id: str) -> str:
    events = session.scalars(select(MerchantVerificationEvent).where(
        MerchantVerificationEvent.case_id == case_id
    ).order_by(MerchantVerificationEvent.created_at, MerchantVerificationEvent.id)).all()
    return "".join(f"<li>{escape(event.created_at.isoformat())} — {escape(event.action)} — "
                   f"{escape(event.from_status or '')} → {escape(event.to_status or '')} — "
                   f"{escape(event.verification_method or '')} / {escape(event.verification_result or '')}</li>"
                   for event in events)


def _service_area_fields(area: dict | None = None, *, allow_status: bool = True) -> str:
    area = area or {}
    fields = (
        ("area_id", "Identifiant stable", "text"), ("code", "Code", "text"),
        ("label", "Libellé", "text"), ("country_code", "Code pays", "text"),
        ("country", "Pays", "text"), ("city", "Ville", "text"),
        ("center_latitude", "Latitude du centre", "number"),
        ("center_longitude", "Longitude du centre", "number"),
        ("radius_km", "Rayon (km)", "number"), ("timezone", "Fuseau IANA", "text"),
        ("locale", "Locale", "text"), ("currency", "Devise", "text"),
    )
    rendered = []
    for name, label, kind in fields:
        value = area.get(name, "")
        step = ' step="any"' if kind == "number" else ""
        rendered.append(
            f'<label>{label} <input name="{name}" type="{kind}" value="{escape(str(value))}" required{step}></label>'
        )
    selected_status = area.get("status", "planned")
    status_options = "".join(
        f'<option value="{value}"{" selected" if selected_status == value else ""}>{label}</option>'
        for value, label in (
            ("planned", "Non ouverte"), ("recruiting", "Recrutement"),
            ("active", "Commercialement active"), ("suspended", "Suspendue"),
        )
    )
    unit = area.get("distance_unit", "km")
    rendered.append(
        f'<label>Unité de distance <select name="distance_unit">'
        f'<option value="km"{" selected" if unit == "km" else ""}>km</option>'
        f'<option value="mi"{" selected" if unit == "mi" else ""}>mi</option></select></label>'
    )
    if allow_status:
        rendered.append(f'<label>Statut <select name="status">{status_options}</select></label>')
    else:
        rendered.append('<input type="hidden" name="status" value="planned">')
    return "".join(rendered)


def _service_area_management_section(admin_id: str, app_env: str, repository: SqlAlchemyServiceAreaRepository) -> str:
    environment = environment_scope(app_env)
    cards = []
    for area in repository.list_for_environment(environment):
        history = repository.history(area.row_id, environment)
        history_html = "".join(
            f'<li>{escape(event.created_at.isoformat())} — {escape(event.action)} — '
            f'version {event.from_version if event.from_version is not None else "initiale"} → {event.to_version} — '
            f'administrateur {escape(event.actor_user_id)} — {escape(event.reason)}</li>'
            for event in history
        )
        token = escape(_csrf_token(admin_id, f"service-area:{area.row_id}", "update-service-area"))
        current = {
            "area_id": area.area_id, "code": area.code, "label": area.label,
            "country_code": area.country_code, "country": area.country, "city": area.city,
            "center_latitude": area.center_latitude, "center_longitude": area.center_longitude,
            "radius_km": area.radius_km, "timezone": area.timezone, "locale": area.locale,
            "currency": area.currency, "distance_unit": area.distance_unit, "status": area.status,
        }
        cards.append(f'''<article><h3>{escape(area.label)} — {escape(area.status)}</h3>
<p>Identifiant : {escape(area.area_id)}; code : {escape(area.code)}; environnement : {escape(area.environment)}</p>
<p>Version de configuration : {area.version}</p>
<form method="post" action="/admin/service-areas/{escape(area.row_id)}">
<input type="hidden" name="expected_version" value="{area.version}">
<input type="hidden" name="csrf_token" value="{token}">
{_service_area_fields(current)}
<label>Justification <textarea name="reason" required maxlength="500"></textarea></label>
<button type="submit">Enregistrer la version {area.version + 1}</button></form>
<details><summary>Historique immuable ({len(history)})</summary><ul>{history_html}</ul></details></article>''')
    create_token = escape(_csrf_token(admin_id, "service-area:create", "create-service-area"))
    create_form = f'''<form method="post" action="/admin/service-areas/create">
<input type="hidden" name="csrf_token" value="{create_token}">
{_service_area_fields(allow_status=False)}
<label>Justification <textarea name="reason" required maxlength="500"></textarea></label>
<button type="submit">Créer une zone (état planifié)</button></form>'''
    return (
        f'<section><h2>Zones commerciales — {escape(environment)}</h2>'
        '<p>Seules les zones actives de cet environnement autorisent l’approbation, la découverte et les nouveaux checkouts. '
        'Les configurations sont isolées par environnement.</p>'
        + ("".join(cards) or "<p>Aucune zone configurée. Le système reste fermé jusqu’à l’initialisation.</p>")
        + "<h3>Ajouter une zone</h3>" + create_form + "</section>"
    )


def _service_area_payload(form) -> ServiceAreaInput:
    names = (
        "area_id", "code", "label", "country_code", "country", "city",
        "center_latitude", "center_longitude", "radius_km", "timezone", "locale",
        "currency", "distance_unit", "status",
    )
    try:
        return ServiceAreaInput.model_validate({name: form.get(name) for name in names})
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Configuration de zone invalide.") from exc


def _admin_page_with_zones(user: User, service: MarketplaceService, session: Session,
                           request: Request, *, notice: str = "", error: str = "") -> HTMLResponse:
    return _page(
        user, service.list_admin_restaurants(user),
        notice, error, kyb_html=_kyb_section(session, user.id),
        service_areas_html=_service_area_management_section(
            user.id, get_settings().app_env, SqlAlchemyServiceAreaRepository(session)
        ),
    )


def _page(
    user: User,
    restaurants: list[dict],
    notice: str = "",
    error: str = "",
    kyb_html: str = "",
    service_areas_html: str = "",
) -> HTMLResponse:
    by_status = {
        status_name: [item for item in restaurants if item["approval_status"] == status_name]
        for status_name in ("pending_review", "draft", "approved", "rejected", "suspended")
    }
    sections = (
        ("pending_review", "Restaurants en attente"),
        ("draft", "Brouillons (non publics)"),
        ("approved", "Restaurants approuvés"),
        ("rejected", "Restaurants refusés"),
        ("suspended", "Restaurants suspendus"),
    )
    content = "".join(
        f"<section><h2>{title}</h2>" + (
            "".join(_restaurant_card(user.id, item) for item in by_status[status_name])
            if by_status[status_name] else "<p>Aucun restaurant dans cette section.</p>"
        ) + "</section>"
        for status_name, title in sections
    )
    full_name = " ".join(part for part in (user.first_name, user.last_name) if part)
    notice_html = f"<p role=\"status\">{escape(notice)}</p>" if notice else ""
    error_html = f"<p role=\"alert\">{escape(error)}</p>" if error else ""
    body = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Admin Kwitli</title></head><body>
<main><h1>Admin Kwitli</h1>
<p>Utilisateur connecté : <strong>{escape(full_name)}</strong> ({escape(user.email)})</p>
<p>Rôle : <strong>Administrateur (is_admin)</strong></p>
<p><strong>Accès admin autorisé</strong></p>{notice_html}{error_html}
{service_areas_html}{kyb_html}{content}</main></body></html>"""
    return HTMLResponse(body, headers={
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    })


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_page(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
    service: MarketplaceService = Depends(get_marketplace_service),
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    enforce_rate_limit(request, scope="admin-html-auth", limit=get_settings().rate_limit_login_requests)
    user = _authenticate_admin(request, credentials, service)
    try:
        restaurants = service.list_admin_restaurants(user)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return _page(
        user, restaurants, request.query_params.get("notice", ""),
        kyb_html=_kyb_section(session, user.id),
        service_areas_html=_service_area_management_section(
            user.id, get_settings().app_env, SqlAlchemyServiceAreaRepository(session)
        ),
    )


@router.post("/admin/service-areas/create", response_class=HTMLResponse, include_in_schema=False)
async def create_admin_service_area(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
    service: MarketplaceService = Depends(get_marketplace_service),
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    enforce_rate_limit(request, scope="admin-service-area", limit=get_settings().rate_limit_login_requests)
    user = _authenticate_admin(request, credentials, service)
    form = await request.form()
    resource, action = "service-area:create", "create-service-area"
    if not _valid_csrf_token(str(form.get("csrf_token", "")), user.id, resource, action):
        raise HTTPException(status_code=403, detail="Jeton de formulaire invalide ou expiré.")
    payload = _service_area_payload(form).model_copy(update={"status": "planned"})
    repository = SqlAlchemyServiceAreaRepository(session)
    try:
        repository.create(payload, get_settings().app_env, user.id, str(form.get("reason", "")))
    except ServiceAreaConflictError as exc:
        page = _admin_page_with_zones(user, service, session, request, error=str(exc))
        return HTMLResponse(page.body, status_code=409, headers=dict(page.headers))
    return RedirectResponse("/admin?notice=Zone%20créée", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/service-areas/{row_id}", response_class=HTMLResponse, include_in_schema=False)
async def update_admin_service_area(
    row_id: str,
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
    service: MarketplaceService = Depends(get_marketplace_service),
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    enforce_rate_limit(request, scope="admin-service-area", limit=get_settings().rate_limit_login_requests)
    user = _authenticate_admin(request, credentials, service)
    form = await request.form()
    resource, action = f"service-area:{row_id}", "update-service-area"
    if not _valid_csrf_token(str(form.get("csrf_token", "")), user.id, resource, action):
        raise HTTPException(status_code=403, detail="Jeton de formulaire invalide ou expiré.")
    payload = _service_area_payload(form)
    try:
        expected_version = int(str(form.get("expected_version", "")))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Version de configuration invalide.") from exc
    repository = SqlAlchemyServiceAreaRepository(session)
    try:
        repository.update(
            row_id, expected_version, payload, get_settings().app_env, user.id,
            str(form.get("reason", "")),
        )
    except ServiceAreaNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ServiceAreaConflictError as exc:
        page = _admin_page_with_zones(user, service, session, request, error=str(exc))
        return HTMLResponse(page.body, status_code=409, headers=dict(page.headers))
    return RedirectResponse("/admin?notice=Zone%20mise%20à%20jour", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/kyb/documents/{document_id}", include_in_schema=False)
def admin_view_kyb_document(
    document_id: str,
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
    service: MarketplaceService = Depends(get_marketplace_service),
    session: Session = Depends(get_db_session),
) -> Response:
    user = _authenticate_admin(request, credentials, service)
    enforce_rate_limit(request, scope="admin-kyb-view", limit=get_settings().rate_limit_upload_requests, user_id=user.id)
    document = session.get(MerchantVerificationDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    if document.scan_status != "clean" or document.status in {"rejected", "replaced", "expired"}:
        raise HTTPException(status_code=404, detail="Document indisponible.")
    if document.expires_at is not None and document.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="Document expiré.")
    try:
        encrypted = private_path(Path(get_settings().kyb_private_storage_dir), document.storage_key).read_bytes()
        clear = decrypt_document(encrypted)
    except (OSError, KybSecurityError) as exc:
        raise HTTPException(status_code=404, detail="Document indisponible.") from exc
    if not hmac.compare_digest(hashlib.sha256(clear).hexdigest(), document.sha256):
        raise HTTPException(status_code=410, detail="Intégrité du document non vérifiable.")
    event = MerchantVerificationEvent(
        case_id=document.case_id, document_id=document.id, actor_user_id=user.id,
        action="document_viewed", policy_version=session.get(MerchantVerificationCase, document.case_id).policy_version,
    )
    session.add(event)
    session.commit()
    return Response(clear, media_type=document.media_type, headers={
        "Cache-Control": "no-store, private", "Pragma": "no-cache",
        "Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })


@router.post("/admin/kyb/documents/{document_id}/verification", include_in_schema=False)
async def admin_review_kyb_document(
    document_id: str, request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
    service: MarketplaceService = Depends(get_marketplace_service),
    session: Session = Depends(get_db_session),
) -> RedirectResponse:
    user = _authenticate_admin(request, credentials, service)
    enforce_rate_limit(request, scope="admin-kyb-action", limit=get_settings().rate_limit_upload_requests, user_id=user.id)
    form = await request.form()
    document = session.get(MerchantVerificationDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    case = session.scalar(select(MerchantVerificationCase).where(
        MerchantVerificationCase.id == document.case_id).with_for_update())
    if not _valid_csrf_token(str(form.get("csrf_token", "")), user.id, case.id, "kyb-document-review"):
        raise HTTPException(status_code=403, detail="Jeton de formulaire invalide ou expiré.")
    method, result, source = str(form.get("method", "")), str(form.get("result", "")), str(form.get("source", ""))
    expires_on = str(form.get("expires_on", "")).strip()
    if method not in {"visual_review", "authorized_source"} or result not in {"consistent", "confirmed", "not_verifiable", "mismatch"}:
        raise HTTPException(status_code=422, detail="Examen de document invalide.")
    if method == "authorized_source" and (not source or len(source) > 100):
        raise HTTPException(status_code=422, detail="Une source autorisée est requise.")
    if method == "authorized_source" and source not in {
        "official_registry", "government_portal", "authorized_issuer", "other_authorized_source",
    }:
        raise HTTPException(status_code=422, detail="Code de source non autorisé.")
    if method == "visual_review" and result == "confirmed":
        raise HTTPException(status_code=422, detail="Un examen visuel ne peut pas confirmer l'authenticité.")
    if result == "confirmed" and method != "authorized_source":
        raise HTTPException(status_code=422, detail="Une source autorisée est requise pour confirmer l'authenticité.")
    if document.scan_status != "clean":
        raise HTTPException(status_code=409, detail="Document non analysé.")
    if expires_on:
        policy = get_policy(case.country_code, case.jurisdiction_code, case.legal_entity_type, case.business_activity)
        requirements = (case.policy_snapshot.get("requirements", []) + case.additional_requirements)
        rule = next((item for item in requirements if item.get("code") == document.requirement_code), None)
        if (policy is None or policy.get("version") != case.policy_version or rule is None
                or rule.get("expiry_policy") != "document_date"):
            raise HTTPException(status_code=422, detail="La politique du dossier ne permet pas de saisir une date d'expiration.")
        try:
            expiry_date = date.fromisoformat(expires_on)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Date d'expiration invalide.") from exc
        document.expires_at = datetime.combine(expiry_date, datetime_time.max, tzinfo=timezone.utc)
    old_status = document.status
    if result == "confirmed":
        document.status = "source_verified"
    elif result == "not_verifiable":
        document.status = "not_verifiable"
    elif result == "mismatch":
        document.status = "rejected"
    elif method == "visual_review" and result == "consistent":
        document.status = "visually_reviewed"
    else:
        document.status = "under_review"
    session.add(MerchantVerificationEvent(
        case_id=case.id, document_id=document.id, actor_user_id=user.id,
        action="document_reviewed", from_status=old_status, to_status=document.status,
        verification_method=method, verification_source=source or None,
        verification_result=result, policy_version=case.policy_version,
    ))
    session.commit()
    return RedirectResponse("/admin?notice=Examen%20KYB%20enregistré", status_code=303)


@router.post("/admin/kyb/{case_id}/decision", include_in_schema=False)
async def admin_decide_kyb_case(
    case_id: str, request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
    service: MarketplaceService = Depends(get_marketplace_service),
    session: Session = Depends(get_db_session),
) -> RedirectResponse:
    user = _authenticate_admin(request, credentials, service)
    enforce_rate_limit(request, scope="admin-kyb-action", limit=get_settings().rate_limit_upload_requests, user_id=user.id)
    form = await request.form()
    case = session.scalar(select(MerchantVerificationCase).where(
        MerchantVerificationCase.id == case_id).with_for_update())
    if case is None:
        raise HTTPException(status_code=404, detail="Dossier KYB introuvable.")
    if not _valid_csrf_token(str(form.get("csrf_token", "")), user.id, case.id, "kyb-decision"):
        raise HTTPException(status_code=403, detail="Jeton de formulaire invalide ou expiré.")
    action, reason = str(form.get("action", "")), str(form.get("reason_code", "")).strip()
    requested_code = str(form.get("additional_code", "")).strip().lower()
    requested_label = str(form.get("additional_label", "")).strip()
    targets = {"under_review": "under_review", "request_correction": "correction_required",
               "approve": "approved", "reject": "rejected", "suspend": "suspended"}
    allowed_from = {"under_review": {"submitted"}, "request_correction": {"submitted", "under_review"},
                    "approve": {"submitted", "under_review"}, "reject": {"submitted", "under_review", "correction_required"},
                    "suspend": {"approved"}}
    if action == "reactivate":
        targets[action] = "under_review"
        allowed_from[action] = {"suspended"}
    if action not in targets or case.status not in allowed_from[action]:
        raise HTTPException(status_code=409, detail="Transition KYB invalide.")
    valid_reasons = {
        "missing_information", "invalid_document", "expired_document", "identity_mismatch",
        "policy_noncompliance", "other",
    }
    if action in {"request_correction", "reject", "suspend"} and reason not in valid_reasons:
        raise HTTPException(status_code=422, detail="Un code de motif est requis.")
    if reason and reason not in valid_reasons:
        raise HTTPException(status_code=422, detail="Code de motif invalide.")
    if len(reason) > 80:
        raise HTTPException(status_code=422, detail="Code de motif invalide.")
    if action == "request_correction":
        if (not requested_code or len(requested_code) > 80 or not requested_code.replace("_", "").isalnum()
                or not requested_label or len(requested_label) > 120):
            raise HTTPException(status_code=422, detail="Code et libellé de pièce supplémentaires requis.")
    if action == "approve":
        policy = get_policy(case.country_code, case.jurisdiction_code, case.legal_entity_type, case.business_activity)
        if (policy is None or not policy.get("active") or policy.get("legal_review") != "confirmed"
                or policy.get("version") != case.policy_version):
            raise HTTPException(status_code=409, detail="La politique juridique active correspondant à ce dossier n'est pas validée.")
        required = [item["code"] for item in policy["requirements"] if item.get("required") is True]
        required.extend(item["code"] for item in case.additional_requirements if item.get("required") is True)
        documents = session.scalars(select(MerchantVerificationDocument).where(
            MerchantVerificationDocument.case_id == case.id)).all()
        for code in required:
            candidates = [doc for doc in documents if doc.requirement_code == code
                          and doc.status == "source_verified" and doc.scan_status == "clean"
                          and (doc.expires_at is None or doc.expires_at > datetime.now(timezone.utc))]
            if not candidates:
                raise HTTPException(status_code=409, detail="Le dossier ne satisfait pas la politique KYB active.")
    previous = case.status
    case.status = targets[action]
    if action == "request_correction":
        entries = list(case.additional_requirements or [])
        if not any(item.get("code") == requested_code for item in entries):
            entries.append({"code": requested_code, "label": requested_label, "status": "admin_requested", "required": True})
            case.additional_requirements = entries
    if action == "under_review":
        case.submitted_at = case.submitted_at or datetime.now(timezone.utc)
    if action in {"approve", "reject", "suspend"}:
        case.reviewed_at = datetime.now(timezone.utc)
    session.add(MerchantVerificationEvent(
        case_id=case.id, actor_user_id=user.id, action=action, from_status=previous,
        to_status=case.status, reason_code=reason or None,
        requested_requirement_code=requested_code or None, policy_version=case.policy_version,
    ))
    session.commit()
    return RedirectResponse("/admin?notice=Décision%20KYB%20enregistrée", status_code=303)


@router.post("/admin/restaurants/{cook_id}/decision", response_class=HTMLResponse, include_in_schema=False)
async def decide_restaurant(
    cook_id: str,
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> HTMLResponse:
    enforce_rate_limit(request, scope="admin-html-action", limit=get_settings().rate_limit_login_requests)
    user = _authenticate_admin(request, credentials, service)
    form = await request.form()
    action = str(form.get("action", ""))
    token = str(form.get("csrf_token", ""))
    if not _valid_csrf_token(token, user.id, cook_id, action):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Jeton de formulaire invalide ou expiré.")
    try:
        service.decide_admin_restaurant(cook_id, action, str(form.get("reason", "")), user)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        restaurants = service.list_admin_restaurants(user)
        response = _page(user, restaurants, error=str(exc))
        response.status_code = status.HTTP_409_CONFLICT
        return response
    return RedirectResponse(url="/admin?notice=Décision%20enregistrée", status_code=status.HTTP_303_SEE_OTHER)
