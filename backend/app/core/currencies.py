"""Devises et fournisseurs du contexte de test actuel, sans conversion."""
from decimal import Decimal


SANDBOX_PROVIDER_BY_CURRENCY = {"COP": "payu", "XOF": "flutterwave"}


class ProviderNotReadyError(ValueError):
    pass


def sandbox_provider_for(currency: str) -> str:
    if currency not in SANDBOX_PROVIDER_BY_CURRENCY:
        raise ValueError("Devise non prise en charge.")
    if currency == "XOF":
        from backend.app.core.config import get_settings
        return get_settings().xof_payment_provider
    return SANDBOX_PROVIDER_BY_CURRENCY[currency]


def amount_storage_units(amount: Decimal, currency: str) -> int:
    sandbox_provider_for(currency)
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Montant invalide.")
    if currency == "XOF" and amount != amount.to_integral_value():
        raise ValueError("Un montant XOF doit etre entier.")
    scaled = amount * 100
    if scaled != scaled.to_integral_value():
        raise ValueError("Precision monetaire invalide.")
    # Convention historique amount_in_cents : centiemes de la devise indiquee.
    # XOF 4500 est stocke 450000, sans changer sa valeur ni sa devise.
    return int(scaled)


def require_currency_environment(currency: str) -> None:
    from backend.app.core.config import get_settings

    # Staging reste autorise : tous les fournisseurs XOF y sont forces en mode test.
    if currency == "XOF" and get_settings().app_env not in {"development", "test", "staging"}:
        raise ValueError("XOF est reserve aux donnees development/test/staging pour le moment.")
