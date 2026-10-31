"""Catalogue versionné; la configuration Sénégal est non normative en attente d'avis juridique."""

from copy import deepcopy


POLICIES = {
    ("SN", "SN", "local_business", "food_service"): {
        "version": "sn-food-service-draft-1",
        "active": False,
        "legal_review": "pending_legal_review",
        "requirements": [
            {"code": "business_identifier", "label": "Identification de l'entreprise (NINEA)", "status": "pending_legal_review", "required": None, "expiry_policy": "pending_legal_review"},
            {"code": "commercial_registration", "label": "Immatriculation commerciale (RCCM, selon statut)", "status": "pending_legal_review", "required": None, "expiry_policy": "pending_legal_review"},
            {"code": "responsible_identity", "label": "Identité du responsable", "status": "pending_legal_review", "required": None, "expiry_policy": "pending_legal_review"},
            {"code": "operating_permit", "label": "Autorisation d'exploitation applicable", "status": "pending_legal_review", "required": None, "expiry_policy": "pending_legal_review"},
            {"code": "sanitary_proof", "label": "Justificatif sanitaire applicable", "status": "pending_legal_review", "required": None, "expiry_policy": "pending_legal_review"},
        ],
    }
}


def get_policy(country_code: str, jurisdiction_code: str, entity_type: str, activity: str) -> dict | None:
    policy = POLICIES.get((country_code.upper(), jurisdiction_code.upper(), entity_type, activity))
    return deepcopy(policy) if policy else None


def active_policy_versions(country_code: str) -> list[str]:
    code = country_code.upper()
    return sorted({policy["version"] for (country, _jurisdiction, _entity, _activity), policy in POLICIES.items()
                   if country == code and policy.get("active") and policy.get("legal_review") == "confirmed"})
