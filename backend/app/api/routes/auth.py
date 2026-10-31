import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.app.core.config import get_settings
from backend.app.dependencies import get_current_user, get_marketplace_service
from backend.app.persistence.models import User
from backend.app.rate_limit import enforce_rate_limit
from backend.app.schemas.users import (
    GenericMessageResponse,
    LoginRequest,
    MeResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    TokenResponse,
    UserRegisterRequest,
)
from backend.app.security import create_access_token
from backend.app.services.marketplace import AuthenticationError, ConflictError, MarketplaceService
from backend.app.services.password_reset_email import PasswordResetEmailSender, get_password_reset_email_sender

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserRegisterRequest,
    request: Request,
    service: MarketplaceService = Depends(get_marketplace_service),
) -> TokenResponse:
    enforce_rate_limit(
        request,
        scope="auth-register",
        limit=get_settings().rate_limit_register_requests,
    )
    try:
        user = service.register_user(payload)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TokenResponse(access_token=create_access_token(user.id, user.auth_version))


@router.post("/auth/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    service: MarketplaceService = Depends(get_marketplace_service),
) -> TokenResponse:
    enforce_rate_limit(
        request,
        scope="auth-login",
        limit=get_settings().rate_limit_login_requests,
    )
    # Second compteur par compte : plusieurs IP ne contournent pas la limite.
    account_key = hashlib.sha256(str(payload.email).strip().lower().encode()).hexdigest()
    enforce_rate_limit(
        request,
        scope="auth-login-account",
        limit=get_settings().rate_limit_login_account_requests,
        subject=account_key,
    )
    try:
        user = service.authenticate(str(payload.email), payload.password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return TokenResponse(access_token=create_access_token(user.id, user.auth_version))


@router.post(
    "/auth/password-reset/request",
    response_model=GenericMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    service: MarketplaceService = Depends(get_marketplace_service),
    sender: PasswordResetEmailSender = Depends(get_password_reset_email_sender),
) -> GenericMessageResponse:
    enforce_rate_limit(
        request,
        scope="auth-password-reset",
        limit=get_settings().rate_limit_password_reset_requests,
    )
    service.request_password_reset(str(payload.email), sender)
    return GenericMessageResponse(
        message="Si un compte correspond a cette adresse, les instructions seront envoyees lorsque le service sera disponible."
    )


@router.post("/auth/password-reset/confirm", response_model=GenericMessageResponse)
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    request: Request,
    service: MarketplaceService = Depends(get_marketplace_service),
) -> GenericMessageResponse:
    enforce_rate_limit(
        request,
        scope="auth-password-reset-confirm",
        limit=get_settings().rate_limit_password_reset_requests,
    )
    if not service.reset_password(payload.token, payload.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lien de recuperation invalide ou expire.",
        )
    return GenericMessageResponse(message="Mot de passe mis a jour. Reconnectez-vous.")


@router.get("/me", response_model=MeResponse)
def me(
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> MeResponse:
    user, cook_profile = service.get_me(current_user)
    return MeResponse(user=user, cook_profile=cook_profile)
