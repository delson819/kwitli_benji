from __future__ import annotations

import hashlib
import base64
import hmac
from datetime import timedelta
from uuid import uuid4
from types import SimpleNamespace
from urllib.parse import urlparse

from backend.app.core.config import Settings
from backend.app.core.time import utc_now, as_utc
from backend.app.core.currencies import ProviderNotReadyError
from backend.app.persistence.models import Payment, User, StockHold
from backend.app.repositories.sqlalchemy import HoldLimitExceededError, SqlAlchemyMarketplaceRepository
from backend.app.schemas.payments import PaymentCreateRequest
from backend.app.services.marketplace import AuthorizationError, ConflictError, NotFoundError
from backend.app.services.payments.payu import PayUPaymentProvider, PayUValidationError
from backend.app.services.payments.paydunya import PayDunyaProvider
from backend.app.services.payments.paytech import PayTechProvider
from backend.app.services.payments.flutterwave import FlutterwaveProvider
from backend.app.services.payments.provider import ProviderError, ProviderRejected, PaymentProvider, InvalidProviderConfirmation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


class PaymentLimitError(Exception):
    pass


class PaymentService:
    def __init__(
        self,
        repository: SqlAlchemyMarketplaceRepository,
        provider: PayUPaymentProvider,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._settings = settings
        self._paydunya = PayDunyaProvider(settings)
        self._paytech = PayTechProvider(settings)
        self._flutterwave = FlutterwaveProvider(settings)
        self._providers: dict[str, PaymentProvider] = {
            self._provider.name: self._provider, self._paydunya.name: self._paydunya,
            self._paytech.name: self._paytech,
            self._flutterwave.name: self._flutterwave,
        }

    def create_payment(self, payload: PaymentCreateRequest, user: User, idempotency_key: str) -> tuple[Payment, str | None]:
        now = utc_now()
        payment_id = str(uuid4())
        checkout_token = self._payu_checkout_token(payment_id)
        checkout_token_hash = hashlib.sha256(checkout_token.encode()).hexdigest()
        token_minutes = min(self._settings.checkout_token_expire_minutes, self._provider.hold_minutes)
        idempotency_key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
        phone = payload.phone_number or user.phone
        intent_context = {
            "network": payload.network,
            "phone_hash": hashlib.sha256(phone.strip().encode()).hexdigest() if phone else None,
            "return_url_hash": hashlib.sha256(payload.return_url.encode()).hexdigest() if payload.return_url else None,
        }
        try:
            payment = self._repository.create_pending_payment_with_hold(
                user_id=user.id,
                availability_id=str(payload.availability_id) if payload.availability_id else None,
                quantity=payload.quantity,
                items=[(str(line.availability_id), line.quantity) for line in payload.items
                       if line.availability_id is not None] if payload.items and payload.items[0].availability_id else None,
                dish_items=[(str(line.dish_id), line.quantity) for line in payload.items
                            if line.dish_id is not None] if payload.items and payload.items[0].dish_id else None,
                payment_id=payment_id,
                provider_reference=f"KWITLI{payment_id.replace('-', '').upper()}",
                expires_at=now + timedelta(minutes=self._provider.hold_minutes),
                checkout_token_hash=checkout_token_hash,
                checkout_token_expires_at=now + timedelta(minutes=token_minutes),
                now=now,
                max_active_holds_per_user=self._settings.max_active_holds_per_user,
                max_held_portions_per_user=self._settings.max_held_portions_per_user,
                idempotency_key_hash=idempotency_key_hash,
                intent_context=intent_context,
            )
        except ProviderNotReadyError as error:
            raise PayUValidationError(str(error)) from error
        except HoldLimitExceededError as error:
            raise PaymentLimitError(str(error)) from error
        except LookupError as error:
            raise NotFoundError(str(error)) from error
        except ValueError as error:
            raise ConflictError(str(error)) from error
        if getattr(payment, "_idempotency_reused", False):
            return self._restore_payment_action(payment)
        selected_provider = self._providers[payment.provider]
        if selected_provider.name == self._flutterwave.name:
            return self.create_flutterwave(payment, payload, user), None
        if selected_provider.name == self._paytech.name:
            try:
                self._paytech.require_settings()
            except ProviderError:
                payment.status = "error"
                payment.provider_creation_state = "failed"
                payment.failure_reason = "paytech_configuration_invalid"
                self._repository.update(payment)
                raise
            parsed_public_url = urlparse(self._settings.public_api_url)
            if parsed_public_url.scheme != "https" or not parsed_public_url.hostname:
                payment.status = "error"
                payment.provider_creation_state = "failed"
                payment.failure_reason = "paytech_checkout_configuration_invalid"
                self._repository.update(payment)
                raise ProviderError("PUBLIC_API_URL HTTPS valide requis pour PayTech.")
            try:
                token, checkout_url = self._paytech.create_payment(payment)
                payment.provider_transaction_id = token
                payment.provider_creation_state = "ready"
                self._repository.update(payment)
            except ProviderRejected:
                payment.status = "error"
                payment.provider_creation_state = "failed"
                payment.failure_reason = "paytech_creation_rejected"
                self._repository.update(payment)
                self._repository.release_hold(payment.id)
                raise
            except ProviderError:
                # L'appel fournisseur peut avoir abouti sans que sa reponse soit arrivee.
                # Garder la tentative en attente et interdire une nouvelle collecte.
                payment.provider_creation_state = "uncertain"
                payment.provider_action = {"type": "wait"}
                payment.failure_reason = "paytech_creation_unconfirmed"
                self._repository.update(payment)
                raise
            except IntegrityError:
                self._repository.session.rollback()
                payment = self._repository.get_payment(payment_id)
                payment.provider_creation_state = "uncertain"
                payment.provider_action = {"type": "wait"}
                payment.failure_reason = "paytech_creation_unconfirmed"
                self._repository.update(payment)
                raise ProviderError("Reference PayTech deja utilisee; verification requise.") from None
            return payment, checkout_url
        if selected_provider.name == self._paydunya.name:
            try:
                self._paydunya.require_settings()
            except ProviderError:
                payment.status = "error"
                payment.provider_creation_state = "failed"
                payment.failure_reason = "paydunya_configuration_invalid"
                self._repository.update(payment)
                raise
            parsed_public_url = urlparse(self._settings.public_api_url)
            if parsed_public_url.scheme != "https" or not parsed_public_url.hostname:
                payment.status = "error"
                payment.provider_creation_state = "failed"
                payment.failure_reason = "paydunya_checkout_configuration_invalid"
                self._repository.update(payment)
                raise ProviderError("PUBLIC_API_URL HTTPS valide requis pour PayDunya.")
            try:
                token = self._paydunya.create_invoice(payment)
                # Champ unique existant; jamais expose dans la reponse mobile.
                payment.provider_transaction_id = token
                payment.provider_creation_state = "ready"
                self._repository.update(payment)
            except ProviderRejected:
                payment.status = "error"
                payment.provider_creation_state = "failed"
                payment.failure_reason = "paydunya_creation_rejected"
                self._repository.update(payment)
                self._repository.release_hold(payment.id)
                raise
            except ProviderError:
                # Un timeout ne prouve pas que la facture n'a pas ete creee.
                payment.provider_creation_state = "uncertain"
                payment.provider_action = {"type": "wait"}
                payment.failure_reason = "invoice_creation_unconfirmed"
                self._repository.update(payment)
                raise
            except IntegrityError:
                self._repository.session.rollback()
                payment = self._repository.get_payment(payment_id)
                payment.provider_creation_state = "uncertain"
                payment.provider_action = {"type": "wait"}
                payment.failure_reason = "invoice_creation_unconfirmed"
                self._repository.update(payment)
                raise ProviderError("Reference de facture deja utilisee; verification requise.") from None
            return payment, None
        return payment, self._payu_checkout_url(payment)

    def _payu_checkout_token(self, payment_id: str) -> str:
        digest = hmac.new(
            self._settings.secret_key.encode(),
            b"kwitli-payu-checkout:" + payment_id.encode(),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def _payu_checkout_url(self, payment: Payment) -> str | None:
        if (payment.provider != "payu" or payment.status != "pending"
                or payment.checkout_token_used_at is not None
                or payment.checkout_token_expires_at is None
                or as_utc(payment.checkout_token_expires_at) <= utc_now()):
            return None
        token = self._payu_checkout_token(payment.id)
        if not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), payment.checkout_token_hash or ""):
            return None
        return f"/api/v1/payments/{payment.id}/payu/checkout#token={token}"

    def _restore_payment_action(self, payment: Payment) -> tuple[Payment, str | None]:
        payment.next_action = None
        checkout_url = None
        if payment.status == "pending":
            if payment.provider == "payu":
                checkout_url = self._payu_checkout_url(payment)
            elif payment.provider == "paytech" and payment.provider_transaction_id:
                checkout_url = self._paytech.checkout_url(payment.provider_transaction_id)
            elif payment.provider == "paytech":
                payment.next_action = {"type": "wait"}
            elif payment.provider == "flutterwave":
                action = payment.provider_action
                payment.next_action = action if isinstance(action, dict) else {"type": "wait"}
            elif payment.provider == "paydunya" and payment.provider_creation_state != "ready":
                payment.next_action = {"type": "wait"}
        return payment, checkout_url

    def restore_payment_action(self, payment: Payment) -> tuple[Payment, str | None]:
        return self._restore_payment_action(payment)

    def create_flutterwave(self, payment: Payment, payload: PaymentCreateRequest, user: User) -> Payment:
        phone = payload.phone_number or user.phone
        try:
            self._flutterwave.require_settings()
            if payload.network is None or not phone:
                raise ProviderError("Choisir Wave ou Orange Money et un telephone test.")
            self._flutterwave.payment_return_url(payload.return_url, payment.id)
        except ProviderError:
            payment.status = "error"
            payment.provider_creation_state = "failed"
            self._repository.update(payment)
            self._repository.release_hold(payment.id)
            raise
        snapshot = SimpleNamespace(id=payment.id, provider_reference=payment.provider_reference,
                                   amount_in_cents=payment.amount_in_cents, currency=payment.currency)
        customer = SimpleNamespace(email=user.email, first_name=user.first_name, last_name=user.last_name)
        self._repository.session.rollback()
        identifier, action, uncertain = None, {"type": "wait"}, False
        try:
            identifier, action = self._flutterwave.create_payment(
                snapshot, customer, payload.network, phone, payload.return_url)
        except ProviderError:
            # Apres un appel reseau, un echec local ne prouve pas l'absence de debit.
            # Conserver le Payment et ses holds, sans retenter la collecte ni changer de provider.
            uncertain = True
        payment = self._repository.get_payment_by_reference_for_update(snapshot.provider_reference)
        if payment is None:
            raise ProviderError("Paiement Flutterwave introuvable apres creation; verification requise.")
        self._repository.session.refresh(payment)
        if identifier and payment.provider_transaction_id not in {None, identifier}:
            raise InvalidProviderConfirmation("Transaction Flutterwave incoherente.")
        if identifier:
            payment.provider_transaction_id = identifier
        if payment.status == "pending":
            payment.failure_reason = "flutterwave_creation_unconfirmed" if uncertain else None
        payment.provider_creation_state = "uncertain" if uncertain else "ready"
        payment.provider_action = action
        try:
            self._repository.update(payment)
        except IntegrityError:
            raise InvalidProviderConfirmation("Transaction Flutterwave deja utilisee.") from None
        payment.next_action = action if payment.status == "pending" else None
        return payment

    def reconcile_pending_payment(self, payment_id: str, transaction_id: str | None = None) -> Payment:
        """Verification distante puis reconciliation atomique; aucun nouvel encaissement.

        Seuls les adaptateurs disposant d'une verification serveur sont acceptes.
        Les conflits payes restent bloques pour resolution, sans remboursement.
        """
        session = self._repository.session
        payment = self._repository.get_payment(payment_id)
        if payment is None:
            raise NotFoundError("Paiement introuvable.")
        if payment.status != "pending":
            return payment
        if payment.order_id is not None:
            raise ConflictError("Paiement pending deja lie a une commande; resolution requise.")
        reference, amount, currency, provider = (
            payment.provider_reference, payment.amount_in_cents, payment.currency, payment.provider
        )
        stored_id = payment.provider_transaction_id
        if transaction_id and stored_id and transaction_id != stored_id:
            raise InvalidProviderConfirmation("Transaction fournisseur incoherente.")
        # Les anciens paiements sans lignes restent sur leur chemin legacy.
        # Ne pas inventer de lignes historiques pendant une reconciliation.
        if not payment.items:
            raise ConflictError("Reconciliation sans PaymentItems non prise en charge.")
        session.rollback()
        if provider == "flutterwave" and currency == "XOF":
            identifier, status = self._flutterwave.verify(reference, amount, transaction_id or stored_id)
        elif provider == "paydunya" and currency == "XOF" and (transaction_id or stored_id):
            identifier = transaction_id or stored_id
            status = self._paydunya.confirm(identifier, reference, amount)
        else:
            raise ProviderError("Verification serveur indisponible pour ce fournisseur.")
        try:
            payment = self._repository.get_payment_by_reference_for_update(reference)
            if payment is None:
                raise NotFoundError("Paiement introuvable.")
            session.refresh(payment)
            if (payment.id != payment_id or payment.provider != provider or payment.currency != currency
                    or payment.amount_in_cents != amount or payment.provider_transaction_id not in {None, identifier}):
                raise InvalidProviderConfirmation("Paiement modifie pendant la verification.")
            # Un webhook concurrent peut avoir termine la commande pendant le GET.
            if payment.status != "pending":
                session.commit()
                return payment
            if payment.order_id is not None:
                raise ConflictError("Paiement pending deja lie a une commande; resolution requise.")
            payment.provider_transaction_id = identifier
            payment.provider_status = status
            session.flush()
            if status == "approved":
                payment.failure_reason = None
                return self._repository.approve_payment_and_create_order(payment, utc_now(), reconcile=True)[0]
            if status in {"declined", "cancelled"}:
                payment.status = status
                for hold in session.scalars(select(StockHold).where(StockHold.payment_id == payment.id).with_for_update()):
                    if hold.status == "active":
                        hold.status = "released"
            session.commit()
            return payment
        except IntegrityError:
            session.rollback()
            raise InvalidProviderConfirmation("Transaction fournisseur deja utilisee.") from None
        except Exception:
            session.rollback()
            raise

    def refresh_flutterwave(self, payment: Payment, transaction_id: str | None = None) -> Payment:
        if payment.provider != "flutterwave" or payment.currency != "XOF":
            raise InvalidProviderConfirmation("Fournisseur Flutterwave incoherent.")
        if payment.status in {"paid_stock_conflict", "reconcile_required"}:
            return payment
        if payment.status == "pending" and payment.items:
            return self.reconcile_pending_payment(payment.id, transaction_id)
        reference, amount = payment.provider_reference, payment.amount_in_cents
        stored_id = payment.provider_transaction_id
        if transaction_id and stored_id and transaction_id != stored_id:
            raise InvalidProviderConfirmation("Transaction Flutterwave incoherente.")
        # L'appel de verification est hors verrou SQL. Meme un webhook authentifie
        # ne peut fournir a lui seul le statut, le montant ou la devise faisant foi.
        self._repository.session.rollback()
        identifier, status = self._flutterwave.verify(reference, amount, transaction_id or stored_id)
        payment = self._repository.get_payment_by_reference_for_update(reference)
        self._repository.session.refresh(payment)
        if (payment.provider != "flutterwave" or payment.currency != "XOF" or payment.amount_in_cents != amount
                or payment.provider_transaction_id not in {None, identifier}):
            raise InvalidProviderConfirmation("Transaction Flutterwave incoherente.")
        if payment.status in {"approved", "refund_pending", "refunded", "paid_stock_conflict", "reconcile_required"}:
            return payment
        payment.provider_transaction_id = identifier
        try:
            self._repository.session.flush()
        except IntegrityError:
            self._repository.session.rollback()
            raise InvalidProviderConfirmation("Transaction Flutterwave deja utilisee.") from None
        payment.provider_status = status
        payment.failure_reason = None
        if status == "approved":
            return self._repository.approve_payment_and_create_order(payment, utc_now())[0]
        if status in {"declined", "cancelled"} and payment.status == "pending":
            payment.status = status
            self._repository.update(payment)
            self._repository.release_hold(payment.id)
        else:
            self._repository.update(payment)
        return payment

    def process_flutterwave_confirmation(self, payload: dict) -> None:
        if payload.get("event") != "charge.completed":
            return
        data = payload.get("data")
        if not isinstance(data, dict):
            raise InvalidProviderConfirmation("Notification Flutterwave invalide.")
        reference = data.get("tx_ref")
        if not isinstance(reference, str) or len(reference) > 120:
            raise InvalidProviderConfirmation("Reference Flutterwave invalide.")
        identifier = self._flutterwave.transaction_id(data.get("id"))
        payment = self._repository.get_payment_by_reference(reference)
        if payment is None:
            raise NotFoundError("Paiement introuvable.")
        self.refresh_flutterwave(payment, identifier)

    def refresh_paydunya(self, payment: Payment) -> Payment:
        if payment.provider != "paydunya":
            raise ConflictError("Ce paiement n'utilise pas PayDunya.")
        if payment.status in {"approved", "refund_pending", "refunded", "paid_stock_conflict", "reconcile_required"}:
            return payment
        token, reference, amount = payment.provider_transaction_id, payment.provider_reference, payment.amount_in_cents
        if not token:
            return payment
        if payment.status == "pending" and payment.items:
            return self.reconcile_pending_payment(payment.id)
        # Pas de verrou SQL pendant l'appel reseau. Relecture verrouillee ensuite.
        self._repository.session.rollback()
        status = self._paydunya.confirm(token, reference, amount)
        payment = self._repository.get_payment_by_reference_for_update(reference)
        self._repository.session.refresh(payment)
        if payment.provider_transaction_id != token or payment.currency != "XOF" or payment.amount_in_cents != amount:
            raise ProviderError("Paiement modifie pendant la verification.")
        if payment.status in {"approved", "refund_pending", "refunded", "paid_stock_conflict", "reconcile_required"}:
            return payment
        if status == "approved":
            return self._repository.approve_payment_and_create_order(payment, utc_now())[0]
        if payment.status == "pending" and status in {"declined", "cancelled"}:
            payment.status = status
            payment.declined_at = utc_now()
            self._repository.update(payment)
            self._repository.release_hold(payment.id)
        return payment

    def paydunya_test_payment(self, payment_id: str, user: User) -> Payment:
        self._paydunya.require_settings()
        payment = self.get_payment_for_user(payment_id, user)
        if payment.provider != "paydunya":
            raise ConflictError("Ce paiement n'utilise pas PayDunya.")
        reference = payment.provider_reference
        self._repository.session.rollback()
        payment = self._repository.get_payment_by_reference_for_update(reference)
        self._repository.session.refresh(payment)
        if payment.status != "pending" or payment.provider_status == "softpay_requested":
            return self.refresh_paydunya(payment)
        if not payment.provider_transaction_id:
            raise ConflictError("Facture Sandbox non disponible.")
        self._paydunya.require_test_customer()
        holds = list(self._repository.session.scalars(select(StockHold).where(
            StockHold.payment_id == payment.id).with_for_update()))
        if not holds or any(hold.status != "active" or as_utc(hold.expires_at) <= utc_now() for hold in holds):
            raise ConflictError("Reservation expiree; ne pas effectuer ce paiement test.")
        token = payment.provider_transaction_id
        payment.provider_status = "softpay_requested"
        self._repository.update(payment)
        # Un timeout ne declenche pas une nouvelle collecte : reconciliation seulement.
        self._paydunya.pay_test_invoice(token)
        return self.refresh_paydunya(payment)

    def process_paydunya_confirmation(self, payload: dict[str, str]) -> None:
        self._paydunya.verify_hash(payload.get("data[hash]"))
        token = payload.get("data[invoice][token]")
        if not self._paydunya.valid_token(token):
            raise ProviderError("Reference de confirmation PayDunya invalide.")
        reference = payload.get("data[custom_data][kwitli_reference]")
        payment = self._repository.get_payment_by_reference(reference) if reference else None
        if payment is not None and payment.provider_transaction_id not in {None, token}:
            raise InvalidProviderConfirmation("Reference de facture PayDunya incoherente.")
        if payment is not None and payment.status == "pending" and payment.items:
            self.reconcile_pending_payment(payment.id, token)
            return
        if payment is None:
            payment = self._repository.session.scalar(select(Payment).where(
                Payment.provider == "paydunya", Payment.provider_transaction_id == token))
        if payment is None:
            raise NotFoundError("Facture PayDunya introuvable.")
        # Le hash IPN est statique, il ne signe pas le montant : verification API obligatoire.
        self.refresh_paydunya(payment)

    def process_paytech_confirmation(self, payload: dict) -> None:
        reference, token, amount, status = self._paytech.verify_notification(payload)
        payment = self._repository.get_payment_by_reference_for_update(reference)
        if payment is None:
            raise NotFoundError("Paiement introuvable.")
        self._repository.session.refresh(payment)
        if (payment.provider != "paytech" or payment.currency != "XOF"
                or payment.provider_transaction_id not in {None, token} or payment.amount_in_cents != amount):
            raise InvalidProviderConfirmation("Notification PayTech incoherente.")
        if payment.provider_transaction_id is None:
            payment.provider_transaction_id = token
        if payment.status in {"approved", "refund_pending", "refunded", "paid_stock_conflict", "reconcile_required"}:
            self._repository.update(payment)
            return
        if status == "approved" and payment.status != "pending":
            # La signature PayTech ne couvre pas type_event : une approbation qui
            # arrive apres un etat terminal ne cree jamais de commande seule.
            payment.status = "reconcile_required"
            payment.failure_reason = "paytech_approved_after_terminal_state"
            self._repository.update(payment)
            return
        if status == "approved":
            self._repository.approve_payment_and_create_order(payment, utc_now())
        elif status == "cancelled" and payment.status == "pending":
            payment.status = "cancelled"
            self._repository.update(payment)
            self._repository.release_hold(payment.id)

    def get_payment_by_reference_for_user(self, reference: str, user: User) -> Payment:
        payment = self._repository.get_payment_by_reference(reference)
        if payment is None or payment.user_id != user.id:
            raise NotFoundError("Paiement introuvable.")
        return payment

    def get_payment_for_user(self, payment_id: str, user: User) -> Payment:
        payment = self._repository.get_payment(payment_id)
        if payment is None:
            raise NotFoundError("Paiement introuvable.")
        if payment.user_id != user.id:
            raise AuthorizationError("Vous ne pouvez pas consulter ce paiement.")
        payment, checkout_url = self._restore_payment_action(payment)
        payment.checkout_url = checkout_url
        return payment

    def get_payu_checkout_fields(self, payment_id: str, token: str, confirmation_url: str, response_url: str) -> tuple[str, dict[str, str]]:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        try:
            payment = self._repository.consume_checkout_token(payment_id, token_hash, utc_now())
        except ValueError as error:
            raise ConflictError(str(error)) from error
        if payment is None or payment.provider != "payu":
            raise NotFoundError("Paiement PayU introuvable.")
        user = self._repository.get_user(payment.user_id)
        if user is None:
            raise NotFoundError("Utilisateur introuvable.")
        full_name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
        return self._provider.checkout_url, self._provider.checkout_fields(
            reference=payment.provider_reference, amount_in_cents=payment.amount_in_cents,
            currency=payment.currency, buyer_email=user.email, buyer_full_name=full_name,
            buyer_phone=user.phone, confirmation_url=confirmation_url, response_url=response_url,
        )

    def process_payu_confirmation(self, payload: dict[str, str]) -> Payment | None:
        confirmation = self._provider.validate_confirmation(payload)
        payment = self._repository.get_payment_by_reference_for_update(confirmation.reference)
        if payment is None:
            return None
        if payment.status == "approved" and payment.order_id is not None:
            return payment
        if payment.status in {"approved", "refund_pending", "refunded", "paid_stock_conflict", "reconcile_required"}:
            # Un etat deja confirme ou en resolution n'est jamais retrograde par une notification.
            self._repository.session.commit()
            return payment
        if payment.provider != "payu" or payment.amount_in_cents != confirmation.amount_in_cents or payment.currency != confirmation.currency:
            payment.status = "error"
            payment.failure_reason = "provider_payload_mismatch"
            payment.provider_status = confirmation.provider_status
            self._repository.update(payment)
            self._repository.release_hold(payment.id)
            return payment
        payment.provider_status = confirmation.provider_status
        mapped = self._provider.map_status(confirmation.provider_status)
        if mapped == "approved":
            payment.provider_transaction_id = confirmation.provider_transaction_id
            return self._repository.approve_payment_and_create_order(payment, utc_now())[0]
        if payment.status == "pending":
            payment.status = mapped
            if mapped == "declined":
                payment.declined_at = utc_now()
            self._repository.update(payment)
            if mapped in {"declined", "error", "cancelled"}:
                self._repository.release_hold(payment.id)
        return payment
