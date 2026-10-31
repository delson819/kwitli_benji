from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.database import get_db_session
from backend.app.core.config import get_settings
from backend.app.repositories.sqlalchemy import SqlAlchemyMarketplaceRepository
from backend.app.services.marketplace import MarketplaceService
from backend.app.services.payments.service import PaymentService
from backend.app.services.payments.payu import PayUPaymentProvider
from backend.app.persistence.models import User
from backend.app.security import decode_access_token_claims

bearer_scheme = HTTPBearer(auto_error=False)


def get_marketplace_service(session: Session = Depends(get_db_session)) -> MarketplaceService:
    return MarketplaceService(repository=SqlAlchemyMarketplaceRepository(session))


def get_payment_service(session: Session = Depends(get_db_session)) -> PaymentService:
    settings = get_settings()
    return PaymentService(SqlAlchemyMarketplaceRepository(session), PayUPaymentProvider(settings), settings)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db_session),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise.")
    claims = decode_access_token_claims(credentials.credentials)
    user_id = claims.get("sub") if claims else None
    user = session.get(User, user_id) if user_id else None
    token_version = claims.get("ver", 0) if claims else None
    if user is None or not user.is_active or token_version != user.auth_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalide ou expiree.")
    return user
