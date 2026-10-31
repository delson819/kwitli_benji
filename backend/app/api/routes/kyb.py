from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.database import get_db_session
from backend.app.dependencies import get_current_user
from backend.app.kyb.policies import get_policy
from backend.app.kyb.security import KybInfectedError, KybSecurityError, collection_ready, private_path, scan_and_encrypt
from backend.app.persistence.models import CookProfile, MerchantVerificationCase, MerchantVerificationDocument, MerchantVerificationEvent, User
from backend.app.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/kyb", tags=["merchant verification"])
ALLOWED_DOCUMENTS = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}


class CaseCreate(BaseModel):
    country_code: str = Field(min_length=2, max_length=2)
    jurisdiction_code: str = Field(min_length=2, max_length=64)
    legal_entity_type: str = Field(min_length=2, max_length=64)
    business_activity: str = Field(min_length=2, max_length=64)
    legal_data: dict[str, str] = Field(default_factory=dict, max_length=20)


class CaseLegalDataUpdate(BaseModel):
    legal_data: dict[str, str] = Field(max_length=20)


def _require_enabled() -> None:
    if not collection_ready():
        raise HTTPException(status_code=503, detail="Le dépôt sécurisé KYB n'est pas activé ou ses contrôles de sécurité sont indisponibles.")


def _cook_for_user(session: Session, user: User) -> CookProfile:
    cook = session.scalar(select(CookProfile).where(CookProfile.user_id == user.id))
    if cook is None or not user.can_cook or not user.is_active:
        raise HTTPException(status_code=403, detail="Profil commerçant requis.")
    return cook


def _lock_owned_cook(session: Session, user: User) -> CookProfile:
    cook = session.scalar(select(CookProfile).where(CookProfile.user_id == user.id).with_for_update())
    if cook is None or not user.can_cook or not user.is_active:
        raise HTTPException(status_code=403, detail="Profil commerçant requis.")
    return cook


def _event(session: Session, case: MerchantVerificationCase, actor: User, action: str,
           *, document_id: str | None = None, from_status: str | None = None,
           to_status: str | None = None, method: str | None = None,
           source: str | None = None, result: str | None = None, reason: str | None = None) -> None:
    session.add(MerchantVerificationEvent(
        case_id=case.id, document_id=document_id, actor_user_id=actor.id, action=action,
        from_status=from_status, to_status=to_status, verification_method=method,
        verification_source=source, verification_result=result, reason_code=reason,
        policy_version=case.policy_version,
    ))


@router.get("/policies")
def kyb_policy(country_code: str = "SN", jurisdiction_code: str = "SN",
               legal_entity_type: str = "local_business", business_activity: str = "food_service"):
    policy = get_policy(country_code, jurisdiction_code, legal_entity_type, business_activity)
    if policy is None:
        raise HTTPException(status_code=404, detail="Aucune politique KYB configurée pour cette juridiction.")
    return policy


@router.get("/cases")
def list_my_kyb_cases(user: User = Depends(get_current_user), session: Session = Depends(get_db_session)):
    cook = _cook_for_user(session, user)
    cases = session.scalars(select(MerchantVerificationCase).where(
        MerchantVerificationCase.cook_profile_id == cook.id
    ).order_by(MerchantVerificationCase.created_at.desc()).limit(20)).all()
    return [{"id": case.id, "country_code": case.country_code, "policy_version": case.policy_version,
             "status": case.status, "created_at": case.created_at,
             "requirements": case.policy_snapshot.get("requirements", []) + case.additional_requirements,
             "documents": [{"id": doc.id, "requirement_code": doc.requirement_code, "status": doc.status,
                            "scan_status": doc.scan_status,
                            "expires_at": doc.expires_at,
                            "effective_status": ("expired" if doc.expires_at and doc.expires_at <= datetime.now(timezone.utc)
                                                 else doc.status)}
                           for doc in session.scalars(select(MerchantVerificationDocument).where(
                               MerchantVerificationDocument.case_id == case.id)).all()]}
            for case in cases]


@router.post("/cases/{case_id}/submit")
def submit_kyb_case(case_id: str, request: Request, user: User = Depends(get_current_user),
                    session: Session = Depends(get_db_session)):
    _require_enabled()
    enforce_rate_limit(request, scope="kyb-case-submit", limit=get_settings().rate_limit_upload_requests, user_id=user.id)
    cook = _cook_for_user(session, user)
    case = session.scalar(select(MerchantVerificationCase).where(
        MerchantVerificationCase.id == case_id, MerchantVerificationCase.cook_profile_id == cook.id
    ).with_for_update())
    if case is None:
        raise HTTPException(status_code=404, detail="Dossier KYB introuvable.")
    if case.status not in {"incomplete", "correction_required"}:
        raise HTTPException(status_code=409, detail="Ce dossier ne peut pas être soumis dans son état actuel.")
    policy = get_policy(case.country_code, case.jurisdiction_code, case.legal_entity_type, case.business_activity)
    if policy and policy.get("active") and policy.get("legal_review") == "confirmed":
        required_codes = {item["code"] for item in policy["requirements"] if item.get("required") is True}
        required_codes.update(item["code"] for item in case.additional_requirements if item.get("required") is True)
        uploaded_codes = set(session.scalars(select(MerchantVerificationDocument.requirement_code).where(
            MerchantVerificationDocument.case_id == case.id,
            MerchantVerificationDocument.scan_status == "clean",
            MerchantVerificationDocument.status.notin_(["rejected", "replaced", "expired"]),
        )).all())
        if not required_codes.issubset(uploaded_codes):
            raise HTTPException(status_code=409, detail="Des pièces requises manquent ou ne passent pas les contrôles techniques.")
    previous = case.status
    case.status = "submitted"
    case.submitted_at = datetime.now(timezone.utc)
    _event(session, case, user, "case_submitted", from_status=previous, to_status=case.status)
    session.commit()
    return {"id": case.id, "status": case.status}


@router.patch("/cases/{case_id}/legal-data")
def update_kyb_legal_data(case_id: str, payload: CaseLegalDataUpdate, request: Request,
                          user: User = Depends(get_current_user), session: Session = Depends(get_db_session)):
    _require_enabled()
    enforce_rate_limit(request, scope="kyb-case-update", limit=get_settings().rate_limit_upload_requests, user_id=user.id)
    cook = _cook_for_user(session, user)
    case = session.scalar(select(MerchantVerificationCase).where(
        MerchantVerificationCase.id == case_id, MerchantVerificationCase.cook_profile_id == cook.id
    ).with_for_update())
    if case is None:
        raise HTTPException(status_code=404, detail="Dossier KYB introuvable.")
    if case.status not in {"incomplete", "correction_required"}:
        raise HTTPException(status_code=409, detail="Le dossier n'accepte pas de modification dans son état actuel.")
    if any(len(key) > 80 or len(value) > 500 for key, value in payload.legal_data.items()):
        raise HTTPException(status_code=422, detail="Données du dossier invalides.")
    try:
        from backend.app.kyb.security import encrypt_document
        case.legal_data_ciphertext = encrypt_document(json.dumps(
            payload.legal_data, ensure_ascii=False, sort_keys=True).encode())
    except KybSecurityError as exc:
        raise HTTPException(status_code=503, detail="Le chiffrement KYB n'est pas disponible.") from exc
    _event(session, case, user, "legal_data_updated", from_status=case.status, to_status=case.status)
    session.commit()
    return {"id": case.id, "status": case.status}


@router.post("/cases", status_code=201)
def create_kyb_case(payload: CaseCreate, request: Request, user: User = Depends(get_current_user),
                    session: Session = Depends(get_db_session)):
    _require_enabled()
    enforce_rate_limit(request, scope="kyb-case", limit=get_settings().rate_limit_upload_requests, user_id=user.id)
    cook = _lock_owned_cook(session, user)
    policy = get_policy(payload.country_code, payload.jurisdiction_code,
                        payload.legal_entity_type, payload.business_activity)
    if policy is None:
        raise HTTPException(status_code=422, detail="Type de dossier KYB non configuré.")
    if any(len(key) > 80 or len(value) > 500 for key, value in payload.legal_data.items()):
        raise HTTPException(status_code=422, detail="Données du dossier invalides.")
    try:
        from backend.app.kyb.security import encrypt_document
        encrypted = encrypt_document(json.dumps(payload.legal_data, ensure_ascii=False, sort_keys=True).encode())
    except KybSecurityError as exc:
        raise HTTPException(status_code=503, detail="Le chiffrement KYB n'est pas disponible.") from exc
    active = session.scalar(select(MerchantVerificationCase).where(
        MerchantVerificationCase.cook_profile_id == cook.id,
        MerchantVerificationCase.status.in_(["incomplete", "submitted", "under_review", "correction_required"]),
    ).limit(1))
    if active:
        raise HTTPException(status_code=409, detail="Un dossier KYB est déjà en cours.")
    case = MerchantVerificationCase(
        cook_profile_id=cook.id, country_code=payload.country_code.upper(),
        jurisdiction_code=payload.jurisdiction_code.upper(), legal_entity_type=payload.legal_entity_type,
        business_activity=payload.business_activity, policy_version=policy["version"],
        policy_snapshot=policy, legal_data_ciphertext=encrypted, status="incomplete",
    )
    session.add(case)
    session.flush()
    _event(session, case, user, "case_created", to_status="incomplete")
    session.commit()
    return {"id": case.id, "status": case.status, "policy_version": case.policy_version,
            "legal_review": policy["legal_review"], "requirements": policy["requirements"]}


@router.post("/cases/{case_id}/documents", status_code=201)
async def upload_kyb_document(case_id: str, request: Request, requirement_code: str,
                              document: UploadFile = File(...), user: User = Depends(get_current_user),
                              session: Session = Depends(get_db_session)):
    _require_enabled()
    settings = get_settings()
    cook = _cook_for_user(session, user)
    case = session.scalar(select(MerchantVerificationCase).where(
        MerchantVerificationCase.id == case_id,
        MerchantVerificationCase.cook_profile_id == cook.id,
    ).with_for_update())
    if case is None:
        raise HTTPException(status_code=404, detail="Dossier KYB introuvable.")
    requirements = {item["code"] for item in case.policy_snapshot.get("requirements", [])}
    requirements.update(item["code"] for item in case.additional_requirements)
    if requirement_code not in requirements or case.status not in {"incomplete", "correction_required"}:
        raise HTTPException(status_code=409, detail="Pièce non attendue dans ce dossier.")
    enforce_rate_limit(request, scope="kyb-upload", limit=settings.rate_limit_upload_requests, user_id=user.id)
    media_type = document.content_type or ""
    signatures = ALLOWED_DOCUMENTS.get(media_type)
    if signatures is None:
        raise HTTPException(status_code=415, detail="Format de document non pris en charge.")
    data = await document.read(settings.kyb_max_document_bytes + 1)
    await document.close()
    if not data or len(data) > settings.kyb_max_document_bytes or not any(data.startswith(sig) for sig in signatures):
        raise HTTPException(status_code=415, detail="Contenu de document invalide.")
    root = Path(settings.kyb_private_storage_dir)
    try:
        storage_key, ciphertext, digest = scan_and_encrypt(data)
    except KybInfectedError as exc:
        raise HTTPException(status_code=422, detail="Le document a été refusé par le contrôle de sécurité.") from exc
    except KybSecurityError as exc:
        raise HTTPException(status_code=503, detail="Le contrôle de sécurité des documents est indisponible.") from exc
    target = private_path(root, storage_key)
    target_created = False
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        target_created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(ciphertext)
            stream.flush()
            os.fsync(stream.fileno())
        row = MerchantVerificationDocument(
            case_id=case.id, requirement_code=requirement_code, storage_key=storage_key,
            media_type=media_type, size_bytes=len(data), sha256=digest, status="technically_valid",
            scan_status="clean", scanned_at=datetime.now(timezone.utc),
        )
        session.add(row)
        session.flush()
        previous_docs = session.scalars(select(MerchantVerificationDocument).where(
            MerchantVerificationDocument.case_id == case.id,
            MerchantVerificationDocument.requirement_code == requirement_code,
            MerchantVerificationDocument.id != row.id,
            MerchantVerificationDocument.status.notin_(["replaced", "rejected"]),
        ).with_for_update()).all()
        for previous in previous_docs:
            old_status = previous.status
            previous.status = "replaced"
            previous.replaced_by_id = row.id
            _event(session, case, user, "document_replaced", document_id=previous.id,
                   from_status=old_status, to_status="replaced")
        _event(session, case, user, "document_uploaded", document_id=row.id,
               to_status=row.status, method="clamav", result="clean")
        session.commit()
        return {"id": row.id, "requirement_code": row.requirement_code,
                "status": row.status, "scan_status": row.scan_status}
    except Exception:
        if target_created:
            target.unlink(missing_ok=True)
        session.rollback()
        raise
