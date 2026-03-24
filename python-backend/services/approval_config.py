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
    change_type: str
    fields: set[tuple[str, str]]  # (table, field) pairs
    allow_self_approve: bool = False  # four-eyes: requester != approver
    display_name: str = ""


# Phase 1 + Phase 2 fields
POLICIES: dict[str, ApprovalPolicy] = {
    # Phase 1: independent fields
    "exchange_rate_update": ApprovalPolicy(
        change_type="exchange_rate_update",
        fields={("exchange_rate", "rate")},
        display_name="Exchange Rate Change",
    ),
    "guarantee_update": ApprovalPolicy(
        change_type="guarantee_update",
        fields={
            ("production_guarantee", "guaranteed_kwh"),
            ("production_guarantee", "p50_annual_kwh"),
        },
        display_name="Guarantee Value Change",
    ),
    # Phase 2: pricing and contract fields
    "base_rate_update": ApprovalPolicy(
        change_type="base_rate_update",
        fields={
            ("clause_tariff", "base_rate"),
            ("clause_tariff", "lp_floor_rate"),
            ("clause_tariff", "lp_ceiling_rate"),
            ("clause_tariff", "lp_discount_pct"),
        },
        display_name="Base Rate / Pricing Bounds Change",
    ),
    "tariff_rate_update": ApprovalPolicy(
        change_type="tariff_rate_update",
        fields={("tariff_rate", "effective_rate_contract_ccy")},
        display_name="Tariff Rate Change",
    ),
    "contract_terms_update": ApprovalPolicy(
        change_type="contract_terms_update",
        fields={
            ("contract", "effective_date"),
            ("contract", "end_date"),
            ("contract", "contract_term_years"),
        },
        display_name="Contract Terms Change",
    ),
    # Phase 3: endpoint-level policies (full-row proposals, not field-level)
    "billing_entry": ApprovalPolicy(
        change_type="billing_entry",
        fields=set(),
        display_name="Monthly Billing Entry",
    ),
    "performance_entry": ApprovalPolicy(
        change_type="performance_entry",
        fields=set(),
        display_name="Plant Performance Entry",
    ),
    "mrp_manual_entry": ApprovalPolicy(
        change_type="mrp_manual_entry",
        fields=set(),
        display_name="Manual MRP Rate Entry",
    ),
    "mrp_upload": ApprovalPolicy(
        change_type="mrp_upload",
        fields=set(),
        display_name="MRP Invoice Upload",
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


def find_policy_by_change_type(change_type: str) -> Optional[ApprovalPolicy]:
    """Return the ApprovalPolicy for a given change_type, or None."""
    return POLICIES.get(change_type)


def requires_approval(table: str, field: str) -> bool:
    """Check if a field requires two-step approval."""
    return (table, field) in _APPROVAL_LOOKUP
