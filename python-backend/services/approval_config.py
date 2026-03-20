"""
Approval policy registry.

Defines which (table, field) pairs require two-step approval.
When an editor edits a designated field, the backend creates a
change_request row instead of applying the change directly.
Admin/approver edits bypass the queue (auto-approved with audit trail).

To enable/disable approval for a field, add/remove it from POLICIES.
Empty POLICIES dict = all edits are immediate (rollback switch).
"""

from dataclasses import dataclass, field as dataclass_field
from typing import Optional


@dataclass
class ApprovalPolicy:
    policy_key: str
    fields: set[tuple[str, str]]  # (table, field) pairs
    allow_self_approve: bool = False  # four-eyes: requester != approver
    display_name: str = ""


# Phase 1 + Phase 2 fields
POLICIES: dict[str, ApprovalPolicy] = {
    # Phase 1: independent fields
    "exchange_rate_update": ApprovalPolicy(
        policy_key="exchange_rate_update",
        fields={("exchange_rate", "rate")},
        display_name="Exchange Rate Change",
    ),
    "guarantee_update": ApprovalPolicy(
        policy_key="guarantee_update",
        fields={
            ("production_guarantee", "guaranteed_kwh"),
            ("production_guarantee", "p50_annual_kwh"),
        },
        display_name="Guarantee Value Change",
    ),
    # Phase 2: pricing and contract fields
    "base_rate_update": ApprovalPolicy(
        policy_key="base_rate_update",
        fields={
            ("clause_tariff", "base_rate"),
            ("clause_tariff", "lp_floor_rate"),
            ("clause_tariff", "lp_ceiling_rate"),
            ("clause_tariff", "lp_discount_pct"),
        },
        display_name="Base Rate / Pricing Bounds Change",
    ),
    "tariff_rate_update": ApprovalPolicy(
        policy_key="tariff_rate_update",
        fields={("tariff_rate", "effective_rate_contract_ccy")},
        display_name="Tariff Rate Change",
    ),
    "contract_terms_update": ApprovalPolicy(
        policy_key="contract_terms_update",
        fields={
            ("contract", "effective_date"),
            ("contract", "end_date"),
            ("contract", "contract_term_years"),
        },
        display_name="Contract Terms Change",
    ),
}

# Pre-compute lookup set for fast checks
_APPROVAL_LOOKUP: dict[tuple[str, str], ApprovalPolicy] = {}
for _policy in POLICIES.values():
    for _tf in _policy.fields:
        _APPROVAL_LOOKUP[_tf] = _policy


def find_policy(table: str, field: str) -> Optional[ApprovalPolicy]:
    """Return the ApprovalPolicy for a (table, field) pair, or None."""
    return _APPROVAL_LOOKUP.get((table, field))


def requires_approval(table: str, field: str) -> bool:
    """Check if a field requires two-step approval."""
    return (table, field) in _APPROVAL_LOOKUP
