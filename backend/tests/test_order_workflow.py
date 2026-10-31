"""Workflow operationnel sans paiement ni mouvement de stock supplementaire."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from sqlalchemy import select, event

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.time import utc_now
from backend.app.database import get_session_factory
from backend.app.persistence.models import CookProfile, DishAvailability, Order, OrderItem, Payment, PaymentItem, PickupVerification, StockHold, User
from backend.app.repositories.sqlalchemy import SqlAlchemyMarketplaceRepository
from backend.app.security import create_access_token
from backend.app.services.marketplace import MarketplaceService, ConflictError, AuthorizationError
from backend.tests.test_cart_checkout import cart_fixture
from backend.tests.test_mvp import create_cook_marketplace, create_paid_order, payu_confirmation, register


@pytest.fixture
def cart_order(client):
    customer, lines = cart_fixture(client)
    payment = client.post('/api/v1/payments', headers=customer, json={'items': lines}).json()
    assert client.post('/api/v1/payments/payu/confirmation', data=payu_confirmation(payment)).status_code == 200
    with get_session_factory()() as session:
        order = session.scalar(select(Order))
        cook = session.get(CookProfile, order.cook_id)
        return {'id': order.id, 'customer': customer, 'merchant_id': cook.user_id,
                'merchant': {'Authorization': 'Bearer ' + create_access_token(cook.user_id)}, 'cook_id': cook.id}


def patch(client, order, status, headers=None):
    return client.patch(f"/api/v1/orders/{order['id']}/status", headers=headers or order['merchant'], json={'status': status})


def internal(order, target, proof_id=None):
    with get_session_factory()() as session:
        service = MarketplaceService(SqlAlchemyMarketplaceRepository(session))
        actor = session.get(User, order['merchant_id'])
        result = service.transition_order_status(order['id'], target, actor, pickup_verification_id=proof_id)
        return result.status, result.picked_up_at


def proof(order, **changes):
    with get_session_factory()() as session:
        stored = session.get(Order, order['id'])
        now = utc_now()
        values = dict(order_id=stored.id, customer_id=stored.customer_id, merchant_user_id=order['merchant_id'],
                      method='proximity', status='verified', created_at=now, used_at=now,
                      expires_at=now + timedelta(minutes=2), token_hash=sha256(uuid4().bytes).hexdigest())
        row = PickupVerification(**(values | changes))
        session.add(row)
        session.commit()
        return row.id


def protected_snapshot():
    with get_session_factory()() as session:
        return {model.__tablename__: session.execute(select(model.__table__).order_by(model.id)).all()
                for model in (DishAvailability, StockHold, Payment, PaymentItem, OrderItem)}


def test_full_workflow_no_financial_or_stock_effect(client, cart_order):
    order = cart_order
    before = protected_snapshot()
    initial = client.get(f"/api/v1/orders/{order['id']}", headers=order['customer']).json()
    assert initial['status'] == 'ordered' and len(initial['items']) == 2
    assert initial['in_progress_at'] is None and initial['picked_up_at'] is None
    for status, timestamp in [('in_progress', 'in_progress_at'), ('ready', 'ready_at')]:
        first = patch(client, order, status)
        assert first.status_code == 200 and first.json()[timestamp]
        assert patch(client, order, status).json()[timestamp] == first.json()[timestamp]
    proof_id = proof(order)
    first = internal(order, 'picked_up', proof_id)
    assert first[0] == 'picked_up' and internal(order, 'picked_up', proof_id) == first
    result = client.get(f"/api/v1/orders/{order['id']}", headers=order['customer']).json()
    assert result['items'] == initial['items'] and result['total_price'] == initial['total_price']
    assert result['status'] == 'picked_up' and result['picked_up_at']
    assert 'token_hash' not in result and 'pickup_verification_id' not in result
    assert protected_snapshot() == before
    assert client.get('/api/v1/orders?scope=merchant&active_only=true', headers=order['merchant']).json() == []
    assert len(client.get('/api/v1/orders?scope=merchant', headers=order['merchant']).json()) == 1
    review = client.post('/api/v1/reviews', headers=order['customer'], json={'order_id': order['id'], 'rating': 5})
    assert review.status_code == 201
    assert review.json()['comment'] is None
    assert client.get('/api/v1/orders?scope=customer', headers=order['customer']).json()[0]['review_comment'] is None
    with get_session_factory()() as session:
        assert MarketplaceService(SqlAlchemyMarketplaceRepository(session)).get_public_cook_profile(order['cook_id'])['orders_completed'] == 1


@pytest.mark.parametrize('source,target', [('ordered', 'ready'), ('ordered', 'picked_up'), ('in_progress', 'picked_up'), ('ready', 'in_progress')])
def test_invalid_jumps(client, cart_order, source, target):
    if source in {'in_progress', 'ready'}:
        assert patch(client, cart_order, 'in_progress').status_code == 200
    if source == 'ready':
        assert patch(client, cart_order, 'ready').status_code == 200
    with pytest.raises(ConflictError):
        internal(cart_order, target, 'missing' if target == 'picked_up' else None)
    assert client.get(f"/api/v1/orders/{cart_order['id']}", headers=cart_order['customer']).json()['status'] == source


def test_terminal_and_pickup_not_public(client, cart_order):
    assert patch(client, cart_order, 'picked_up').status_code == 422
    assert patch(client, cart_order, 'completed').status_code == 422
    patch(client, cart_order, 'in_progress'); patch(client, cart_order, 'ready')
    assert client.post(f"/api/v1/orders/{cart_order['id']}/pickup/confirm", headers=cart_order['merchant'], json={'pickup_code': '123456'}).status_code == 409
    with pytest.raises(ConflictError):
        internal(cart_order, 'picked_up')
    proof_id = proof(cart_order)
    internal(cart_order, 'picked_up', proof_id)
    for target in ('ordered', 'in_progress', 'ready', 'completed', 'cancelled'):
        with pytest.raises(ConflictError):
            internal(cart_order, target)


def test_customer_cannot_change_ready_order_to_picked_up(client, cart_order):
    before = protected_snapshot()
    endpoint = f"/api/v1/orders/{cart_order['id']}/pickup/confirm"
    assert client.post(endpoint, headers=cart_order['customer'], json={}).status_code == 409
    patch(client, cart_order, 'in_progress')
    assert client.post(endpoint, headers=cart_order['customer'], json={}).status_code == 409
    patch(client, cart_order, 'ready')
    ready = client.get(f"/api/v1/orders/{cart_order['id']}", headers=cart_order['customer']).json()
    assert ready['status'] == 'ready'
    assert client.post(endpoint, headers=cart_order['customer'], json={}).status_code == 409
    assert client.get(f"/api/v1/orders/{cart_order['id']}", headers=cart_order['customer']).json()['status'] == 'ready'
    assert protected_snapshot() == before
    assert len(client.get('/api/v1/orders?scope=customer&active_only=true', headers=cart_order['customer']).json()) == 1


def test_double_validation_pickup_code_ready_to_picked_up(client, cart_order):
    order_id = cart_order['id']
    endpoint = f"/api/v1/orders/{order_id}/pickup/code"
    assert client.post(endpoint, headers=cart_order['customer'], json={}).status_code == 409
    assert client.post(endpoint, headers=cart_order['merchant'], json={}).status_code == 403
    patch(client, cart_order, 'in_progress')
    patch(client, cart_order, 'ready')

    issued = client.post(endpoint, headers=cart_order['customer'], json={})
    assert issued.status_code == 200
    code = issued.json()['pickup_code']
    assert code.isdigit() and len(code) == 6
    assert client.post(endpoint, headers=cart_order['customer'], json={}).json()['pickup_code'] == code
    assert client.get(f"/api/v1/orders/{order_id}", headers=cart_order['merchant']).json()['pickup_code'] is None

    confirm = f"/api/v1/orders/{order_id}/pickup/confirm"
    assert client.post(confirm, headers=cart_order['customer'], json={'pickup_code': code}).status_code == 403
    wrong_code = f"{(int(code) + 1) % 1_000_000:06d}"
    assert client.post(confirm, headers=cart_order['merchant'], json={'pickup_code': wrong_code}).status_code == 409
    intruder, _, _, _ = create_cook_marketplace(client, email='pickup-other-merchant@example.co')
    assert client.post(confirm, headers=intruder, json={'pickup_code': code}).status_code == 403

    before = protected_snapshot()
    accepted = client.post(confirm, headers=cart_order['merchant'], json={'pickup_code': code})
    assert accepted.status_code == 200
    assert accepted.json()['status'] == 'picked_up'
    assert accepted.json()['picked_up_at'] is not None
    duplicate = client.post(confirm, headers=cart_order['merchant'], json={'pickup_code': code})
    assert duplicate.status_code == 200
    assert duplicate.json()['status'] == 'picked_up'
    assert duplicate.json()['picked_up_at'] == accepted.json()['picked_up_at']
    assert protected_snapshot() == before

    after_review = client.get(f"/api/v1/orders/{order_id}", headers=cart_order['customer']).json()
    assert after_review['status'] == 'picked_up'
    assert after_review['pickup_code'] == code
    assert client.post('/api/v1/reviews', headers=cart_order['customer'], json={
        'order_id': order_id, 'rating': 5,
    }).status_code == 201


@pytest.mark.parametrize('kind', ['pending', 'expired', 'missing', 'wrong_merchant'])
def test_pickup_requires_existing_valid_proof(client, cart_order, kind):
    patch(client, cart_order, 'in_progress'); patch(client, cart_order, 'ready')
    changes = {}
    if kind == 'pending':
        changes = {'status': 'pending', 'used_at': None}
    elif kind == 'expired':
        now = utc_now()
        changes = {'created_at': now-timedelta(minutes=3), 'used_at': now-timedelta(minutes=2), 'expires_at': now-timedelta(minutes=1)}
    elif kind == 'wrong_merchant':
        register(client, 'other@example.co', 'Autre')
        with get_session_factory()() as session:
            changes = {'merchant_user_id': session.scalar(select(User.id).where(User.email == 'other@example.co'))}
    proof_id = 'missing' if kind == 'missing' else proof(cart_order, **changes)
    with pytest.raises(ConflictError):
        internal(cart_order, 'picked_up', proof_id)


def test_authorization_and_scoped_reads(client, cart_order):
    intruder, _, _, _ = create_cook_marketplace(client, email='other-merchant@example.co')
    for headers in (cart_order['customer'], intruder):
        assert patch(client, cart_order, 'in_progress', headers).status_code == 403
    assert client.get(f"/api/v1/orders/{cart_order['id']}", headers=intruder).status_code == 403
    assert client.get('/api/v1/orders?scope=merchant', headers=intruder).json() == []
    assert client.get('/api/v1/orders?scope=merchant', headers=cart_order['customer']).status_code == 403
    assert client.get(f"/api/v1/orders/{cart_order['id']}").status_code == 401
    for scope, headers in [('customer', cart_order['customer']), ('merchant', cart_order['merchant']), ('cook', cart_order['merchant'])]:
        rows = client.get(f'/api/v1/orders?scope={scope}&active_only=true', headers=headers).json()
        assert len(rows) == 1 and len(rows[0]['items']) == 2
        assert rows[0]['cook_id'] == cart_order['cook_id']
    patch(client, cart_order, 'in_progress')
    # Meme une repetition idempotente doit etre autorisee.
    assert patch(client, cart_order, 'in_progress', intruder).status_code == 403


def test_concurrent_duplicate_transition(client, cart_order):
    before = protected_snapshot()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: patch(client, cart_order, 'in_progress'), range(2)))
    assert all(r.status_code == 200 for r in responses)
    assert responses[0].json()['in_progress_at'] == responses[1].json()['in_progress_at']
    assert protected_snapshot() == before


def test_legacy_completed_readable_and_counted(client):
    merchant, cook, _, availability = create_cook_marketplace(client)
    customer = register(client, 'legacy@example.co', 'Client')
    order = create_paid_order(client, customer, availability['id'])
    assert client.patch(f"/api/v1/orders/{order['id']}/status", headers=merchant, json={'status': 'ready'}).status_code == 200
    assert client.post(f"/api/v1/orders/{order['id']}/pickup/confirm", headers=merchant, json={'pickup_code': order['pickup_code']}).status_code == 200
    result = client.get(f"/api/v1/orders/{order['id']}", headers=customer).json()
    assert result['status'] == 'completed' and result['pickup_code'] == order['pickup_code']
    assert result['in_progress_at'] is None and result['picked_up_at'] is None
    assert client.get('/api/v1/orders?scope=merchant&active_only=true', headers=merchant).json() == []
    assert len(client.get('/api/v1/orders?scope=merchant', headers=merchant).json()) == 1
    assert client.post('/api/v1/reviews', headers=customer, json={'order_id': order['id'], 'rating': 4}).status_code == 201
    with get_session_factory()() as session:
        assert MarketplaceService(SqlAlchemyMarketplaceRepository(session)).get_public_cook_profile(cook['id'])['orders_completed'] == 1


def test_internal_transition_rejects_inactive_merchant(client, cart_order):
    with get_session_factory()() as session:
        session.get(User, cart_order['merchant_id']).is_active = False
        session.commit()
    with pytest.raises(AuthorizationError):
        internal(cart_order, 'in_progress')


def test_proof_for_another_order_rejected(client, cart_order):
    patch(client, cart_order, 'in_progress'); patch(client, cart_order, 'ready')
    with get_session_factory()() as session:
        current = session.get(Order, cart_order['id'])
        other = Order(customer_id=current.customer_id, cook_id=current.cook_id, status='ready',
                      total_price=current.total_price, currency=current.currency, ready_at=utc_now())
        session.add(other)
        session.commit()
        other_id = other.id
    proof_id = proof(cart_order, order_id=other_id)
    with pytest.raises(ConflictError):
        internal(cart_order, 'picked_up', proof_id)


def test_transition_failure_rolls_back(client, cart_order):
    before = protected_snapshot()
    def fail(*args):
        raise RuntimeError('Echec operationnel simule')
    event.listen(Order, 'before_update', fail)
    try:
        with pytest.raises(RuntimeError, match='Echec operationnel simule'):
            internal(cart_order, 'in_progress')
    finally:
        event.remove(Order, 'before_update', fail)
    with get_session_factory()() as session:
        order = session.get(Order, cart_order['id'])
        assert order.status == 'ordered' and order.in_progress_at is None
    assert protected_snapshot() == before


def test_new_order_cannot_enter_legacy_refund_flow(client, cart_order):
    patch(client, cart_order, 'in_progress'); patch(client, cart_order, 'ready')
    before = protected_snapshot()
    response = client.post(f"/api/v1/orders/{cart_order['id']}/cancel", headers=cart_order['merchant'], json={
        "reason": "ingredient_unavailable", "description": "Un ingredient manque.",
    })
    assert response.status_code == 200
    assert response.json()['request_type'] == 'merchant_cancellation'
    assert protected_snapshot() == before


def test_review_after_customer_pickup_only_once(client, cart_order):
    assert client.post('/api/v1/reviews', headers=cart_order['customer'], json={'order_id': cart_order['id'], 'rating': 5}).status_code == 409
    intruder = register(client, 'pickup-review-intruder@example.co', 'Intrus')
    patch(client, cart_order, 'in_progress')
    patch(client, cart_order, 'ready')
    assert client.post(f"/api/v1/orders/{cart_order['id']}/pickup/confirm", headers=intruder, json={}).status_code == 403
    assert client.post(f"/api/v1/orders/{cart_order['id']}/pickup/confirm", headers=cart_order['customer'], json={}).status_code == 409
    proof_id = proof(cart_order)
    internal(cart_order, 'picked_up', proof_id)
    first = client.post('/api/v1/reviews', headers=cart_order['customer'], json={
        'order_id': cart_order['id'], 'rating': 5, 'comment': 'Tres bon',
    })
    assert first.status_code == 201
    detail = client.get('/api/v1/orders?scope=customer', headers=cart_order['customer']).json()[0]
    assert detail['review_id'] == first.json()['id']
    assert detail['review_rating'] == 5
    assert detail['review_comment'] == 'Tres bon'
    assert client.post('/api/v1/reviews', headers=cart_order['customer'], json={'order_id': cart_order['id'], 'rating': 4}).status_code == 409
