from datetime import datetime

from backend.app.persistence.models import Order
from backend.app.repositories.sqlalchemy import SqlAlchemyMarketplaceRepository


class RefundService:
    """Prepare une annulation financiere sans appeler l'API de remboursement PayU."""

    def __init__(self, repository: SqlAlchemyMarketplaceRepository) -> None:
        self._repository = repository

    def cancel_order(self, order: Order, now: datetime, reason: str | None) -> Order:
        return self._repository.cancel_order_with_stock_restore(order, now, reason)
