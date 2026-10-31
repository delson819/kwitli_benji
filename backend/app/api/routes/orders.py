from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from backend.app.core.config import get_settings
from backend.app.dependencies import get_current_user, get_marketplace_service
from backend.app.persistence.models import User
from backend.app.rate_limit import enforce_rate_limit
from backend.app.schemas.orders import OrderCreateRequest, OrderHistoryResponse, OrderMessageCreate, OrderMessageResponse, OrderResponse, OrderResolutionDecision, OrderResolutionRequestCreate, OrderResolutionRequestResponse, OrderStatusUpdateRequest, PickupConfirmRequest
from backend.app.services.marketplace import AuthorizationError, ConflictError, MarketplaceService, NotFoundError

router = APIRouter(prefix="/orders", tags=["orders"])

@router.post("", response_model=OrderResponse, status_code=status.HTTP_409_CONFLICT)
def create_order(
    payload: OrderCreateRequest,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> OrderResponse:
    raise HTTPException(status_code=409, detail="Une commande doit etre confirmee par un paiement approuve.")

@router.get("", response_model=list[OrderHistoryResponse])
def list_orders(
    scope: str = Query(default="customer", pattern="^(customer|cook|merchant)$"),
    active_only: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> list[OrderHistoryResponse]:
    try:
        return service.list_orders_for_user(current_user, scope, active_only)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/resolution-requests", response_model=list[OrderResolutionRequestResponse])
def list_resolution_requests(
    status_filter: str | None = Query(default="submitted", alias="status", pattern="^(submitted|approved|rejected|resolution_requested)$"),
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> list[OrderResolutionRequestResponse]:
    try:
        return service.list_order_resolution_requests(current_user, status_filter)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.patch("/resolution-requests/{request_id}/decision", response_model=OrderResolutionRequestResponse)
def decide_resolution_request(
    request_id: str,
    payload: OrderResolutionDecision,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> OrderResolutionRequestResponse:
    try:
        return service.decide_order_resolution_request(request_id, payload, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> OrderResponse:
    try:
        order = service.get_order_for_user(order_id, current_user)
        return service.order_response_for_user(order, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{order_id}/messages", response_model=list[OrderMessageResponse])
def list_order_messages(
    order_id: str,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> list[OrderMessageResponse]:
    try:
        return service.list_order_messages(order_id, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{order_id}/messages", response_model=OrderMessageResponse, status_code=status.HTTP_201_CREATED)
def create_order_message(
    order_id: str,
    payload: OrderMessageCreate,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> OrderMessageResponse:
    try:
        return service.create_order_message(order_id, payload.body, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{order_id}/status", response_model=OrderResponse)
def update_order_status(
    order_id: str,
    payload: OrderStatusUpdateRequest,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> OrderResponse:
    try:
        order = service.update_order_status(order_id, payload.status, current_user)
        return service.order_response_for_user(order, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{order_id}/pickup/confirm", response_model=OrderResponse)
def confirm_pickup(
    order_id: str,
    payload: PickupConfirmRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> OrderResponse:
    enforce_rate_limit(
        request,
        scope="pickup-confirm",
        limit=get_settings().rate_limit_pickup_requests,
        user_id=current_user.id,
    )
    try:
        order = service.confirm_pickup(order_id, payload.pickup_code, current_user)
        return service.order_response_for_user(order, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{order_id}/pickup/code", response_model=OrderResponse)
def request_pickup_code(
    order_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> OrderResponse:
    enforce_rate_limit(
        request,
        scope="pickup-code",
        limit=get_settings().rate_limit_pickup_requests,
        user_id=current_user.id,
    )
    try:
        order = service.request_pickup_code(order_id, current_user)
        return service.order_response_for_user(order, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{order_id}/cancel", response_model=OrderResolutionRequestResponse, deprecated=True)
def cancel_order(
    order_id: str,
    payload: OrderResolutionRequestCreate,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> OrderResolutionRequestResponse:
    try:
        return service.submit_order_resolution_request(order_id, payload, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{order_id}/resolution-requests", response_model=OrderResolutionRequestResponse, status_code=status.HTTP_201_CREATED)
def create_resolution_request(
    order_id: str,
    payload: OrderResolutionRequestCreate,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> OrderResolutionRequestResponse:
    try:
        return service.submit_order_resolution_request(order_id, payload, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
