"""
Gold-standard example extractions for each clause category.

These examples guide Claude on:
- What good extractions look like
- How to populate normalized_payload fields correctly
- Key legal/financial terms to identify per category

Canonical Ontology Layer:
- CANONICAL_SCHEMAS: Defines the expected fields per category with types, roles, and aliases
- CANONICAL_TERMINOLOGY: Maps every known alias to its canonical field name
- Role annotations: T=Threshold, FI=Formula Input, FD=Formula Definition,
                    S=Schedule, C=Configuration, R=Reference
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# CANONICAL SCHEMAS — one per category
# =============================================================================
# Each field has: name, type, role, required, aliases (legacy names), description
# Role codes: T=Threshold, FI=Formula Input, FD=Formula Definition,
#             S=Schedule, C=Configuration, R=Reference

CANONICAL_SCHEMAS = {
    "AVAILABILITY": {
        "fields": [
            {"name": "threshold", "type": "number", "role": "T", "required": True,
             "aliases": ["threshold_percent", "guaranteed_availability_percent", "minimum_availability_percent", "availability_percent"],
             "description": "Guaranteed minimum availability percentage"},
            {"name": "measurement_period", "type": "string", "role": "C", "required": True,
             "aliases": ["evaluation_period", "period"],
             "description": "Measurement period: monthly, quarterly, annual"},
            {"name": "calculation_method", "type": "string", "role": "FD", "required": False,
             "aliases": ["formula", "availability_formula"],
             "description": "How availability is calculated"},
            {"name": "excused_events", "type": "list", "role": "S", "required": False,
             "aliases": ["excluded_events", "exemptions"],
             "description": "Events excluded from availability calculation"},
            {"name": "ld_rate", "type": "number", "role": "FI", "required": False,
             "aliases": ["ld_per_point", "penalty_rate"],
             "description": "Liquidated damages rate per shortfall point"},
            {"name": "ld_cap", "type": "number", "role": "FI", "required": False,
             "aliases": ["ld_cap_annual", "cap_amount", "damages_cap"],
             "description": "Annual cap on liquidated damages"},
            {"name": "scheduled_outage_max_hours_per_year", "type": "number", "role": "C", "required": False,
             "aliases": ["max_scheduled_hours", "outage_limit"],
             "description": "Maximum scheduled outage hours per year"},
            {"name": "scheduled_outage_notice_days", "type": "number", "role": "C", "required": False,
             "aliases": ["notice_days", "advance_notice_days"],
             "description": "Advance notice required for scheduled outages"},
        ]
    },
    "PERFORMANCE_GUARANTEE": {
        "fields": [
            {"name": "variant", "type": "string", "role": "C", "required": False,
             "aliases": ["guarantee_type", "performance_type"],
             "description": "Type: performance_ratio, capacity_factor, annual_production"},
            {"name": "threshold", "type": "number", "role": "T", "required": True,
             "aliases": ["threshold_percent", "guaranteed_performance_ratio_percent", "guaranteed_capacity_factor_percent"],
             "description": "Guaranteed performance threshold"},
            {"name": "degradation_rate_percent_per_year", "type": "number", "role": "FI", "required": False,
             "aliases": ["degradation_rate", "annual_degradation"],
             "description": "Permitted annual degradation rate"},
            {"name": "guarantee_period_years", "type": "number", "role": "C", "required": False,
             "aliases": ["term_years", "guarantee_term"],
             "description": "Duration of the performance guarantee"},
            {"name": "measurement_period", "type": "string", "role": "C", "required": True,
             "aliases": ["evaluation_period", "period"],
             "description": "Measurement period: monthly, quarterly, annual"},
            {"name": "weather_adjustment_method", "type": "string", "role": "FD", "required": False,
             "aliases": ["irradiance_adjustment", "weather_method"],
             "description": "How weather affects performance calculations"},
            {"name": "guaranteed_annual_production_kwh", "type": "number", "role": "T", "required": False,
             "aliases": ["annual_production", "guaranteed_output"],
             "description": "Guaranteed annual production in kWh"},
            {"name": "performance_ratio_schedule", "type": "list", "role": "S", "required": False,
             "aliases": ["pr_schedule", "monthly_pr_targets"],
             "description": "Monthly or periodic performance ratio targets (list of {month, target_percent} objects)"},
        ]
    },
    "PRICING": {
        "fields": [
            {"name": "base_rate_per_kwh", "type": "number", "role": "FI", "required": True,
             "aliases": ["base_rate", "rate", "price", "tariff", "energy_rate", "contract_price", "ppa_price"],
             "description": "Base energy rate per kWh"},
            {"name": "base_rate_unit", "type": "string", "role": "C", "required": False,
             "aliases": ["rate_unit", "unit", "price_unit"],
             "description": "Unit for rate: $/kWh, $/MWh"},
            {"name": "escalation_rate", "type": "number", "role": "FI", "required": False,
             "aliases": ["escalation_rate_percent_per_year", "escalation_percent", "annual_escalation"],
             "description": "Annual escalation rate percentage"},
            {"name": "escalation_index", "type": "string", "role": "C", "required": False,
             "aliases": ["index", "price_index", "escalation_basis"],
             "description": "Escalation index: fixed, CPI, PPI"},
            {"name": "pricing_structure", "type": "string", "role": "C", "required": False,
             "aliases": ["structure", "price_type"],
             "description": "fixed, escalating, indexed, tiered, time_of_use"},
            {"name": "billing_components", "type": "list", "role": "S", "required": False,
             "aliases": ["components", "tariff_components"],
             "description": "List of billing components"},
            {"name": "fx_indemnity", "type": "object", "role": "FD", "required": False,
             "aliases": ["currency_protection", "fx_protection"],
             "description": "Foreign exchange indemnity terms"},
            {"name": "deemed_energy_method", "type": "string", "role": "C", "required": False,
             "aliases": ["deemed_generation", "curtailment_compensation"],
             "description": "Method for calculating deemed energy"},
            {"name": "includes_environmental_attributes", "type": "boolean", "role": "C", "required": False,
             "aliases": ["includes_recs", "includes_green_attributes"],
             "description": "Whether rate includes RECs/environmental attributes"},
            {"name": "rate_schedule", "type": "list", "role": "S", "required": False,
             "aliases": ["rate_tiers", "tiered_rates", "pricing_tiers"],
             "description": "Rate schedule for tiered/time-varying pricing (list of {period, rate, unit} objects)"},
            {"name": "billing_currency", "type": "string", "role": "C", "required": False,
             "aliases": ["payment_currency", "invoice_currency"],
             "description": "Currency for billing and invoicing"},
        ]
    },
    "PAYMENT_TERMS": {
        "fields": [
            {"name": "invoice_frequency", "type": "string", "role": "C", "required": True,
             "aliases": ["billing_frequency", "billing_cycle", "frequency"],
             "description": "How often invoices are issued: monthly, quarterly"},
            {"name": "payment_due_days", "type": "number", "role": "C", "required": True,
             "aliases": ["due_days", "net_days", "payment_terms"],
             "description": "Days after invoice receipt to pay"},
            {"name": "late_interest_rate", "type": "string", "role": "FI", "required": False,
             "aliases": ["late_payment_interest_rate_percent", "interest_rate", "late_fee"],
             "description": "Interest rate on overdue amounts"},
            {"name": "currency", "type": "string", "role": "C", "required": False,
             "aliases": ["payment_currency"],
             "description": "Payment currency code"},
            {"name": "billing_components", "type": "list", "role": "R", "required": False,
             "aliases": ["line_items", "invoice_components"],
             "description": "Reference to billing components from PRICING"},
            {"name": "invoice_timing", "type": "string", "role": "C", "required": False,
             "aliases": ["invoice_deadline"],
             "description": "When invoices are issued relative to period end"},
            {"name": "minimum_purchase_percent", "type": "number", "role": "FI", "required": False,
             "aliases": ["take_or_pay_percent", "min_offtake"],
             "description": "Minimum annual offtake as percentage"},
            {"name": "take_or_pay_shortfall_rate", "type": "number", "role": "FI", "required": False,
             "aliases": ["shortfall_rate", "shortfall_price_multiplier"],
             "description": "Rate multiplier for take-or-pay shortfall payment"},
        ]
    },
    "CONDITIONS_PRECEDENT": {
        "fields": [
            {"name": "conditions", "type": "list", "role": "S", "required": True,
             "aliases": ["conditions_list", "cp_list", "precedent_conditions"],
             "description": "List of conditions that must be satisfied"},
            {"name": "longstop_date", "type": "string", "role": "C", "required": False,
             "aliases": ["satisfaction_deadline", "deadline_date", "cp_deadline"],
             "description": "Final date by which all CPs must be met"},
            {"name": "milestone_dates", "type": "object", "role": "S", "required": False,
             "aliases": ["milestones", "cp_milestones"],
             "description": "Key milestone dates for CP satisfaction"},
            {"name": "responsible_party_by_condition", "type": "string", "role": "C", "required": False,
             "aliases": ["responsible_party"],
             "description": "Who satisfies each condition"},
            {"name": "satisfaction_deadline_days", "type": "number", "role": "C", "required": False,
             "aliases": ["deadline_days"],
             "description": "Days to satisfy all CPs"},
            {"name": "waiver_rights", "type": "boolean", "role": "C", "required": False,
             "aliases": ["waivable"],
             "description": "Whether CPs can be waived"},
            {"name": "failure_consequences", "type": "string", "role": "C", "required": False,
             "aliases": ["consequence_of_failure"],
             "description": "What happens if CPs not satisfied"},
        ]
    },
    "DEFAULT": {
        "fields": [
            {"name": "variant", "type": "string", "role": "C", "required": False,
             "aliases": ["default_type"],
             "description": "buyer, seller, or mutual"},
            {"name": "events", "type": "list", "role": "S", "required": True,
             "aliases": ["default_events", "events_of_default"],
             "description": "List of default trigger events"},
            {"name": "owner_default_events", "type": "list", "role": "S", "required": False,
             "aliases": ["seller_defaults", "seller_default_events"],
             "description": "Seller/owner-specific default events"},
            {"name": "buyer_default_events", "type": "list", "role": "S", "required": False,
             "aliases": ["offtaker_defaults", "buyer_defaults"],
             "description": "Buyer/offtaker-specific default events"},
            {"name": "cure_period_days", "type": "number", "role": "FI", "required": True,
             "aliases": ["cure_days", "cure_period"],
             "description": "Standard cure period in days"},
            {"name": "extended_cure_period_days", "type": "number", "role": "FI", "required": False,
             "aliases": ["extended_cure_days"],
             "description": "Extended cure period for complex cures"},
            {"name": "remedy", "type": "string", "role": "C", "required": False,
             "aliases": ["remedies", "available_remedies"],
             "description": "Available remedies upon default"},
            {"name": "cure_notice_method", "type": "string", "role": "C", "required": False,
             "aliases": ["notice_method"],
             "description": "How cure notice must be given"},
            {"name": "cross_default_applies", "type": "boolean", "role": "C", "required": False,
             "aliases": ["cross_default"],
             "description": "Whether cross-default provisions apply"},
        ]
    },
    "TERMINATION": {
        "fields": [
            {"name": "variant", "type": "string", "role": "C", "required": False,
             "aliases": ["termination_type"],
             "description": "declining_per_wp, tiered_by_event, convenience, default"},
            {"name": "initial_term_years", "type": "number", "role": "C", "required": False,
             "aliases": ["term_years", "contract_term"],
             "description": "Primary contract duration in years"},
            {"name": "termination_fee_formula", "type": "string", "role": "FD", "required": False,
             "aliases": ["fee_formula", "termination_payment"],
             "description": "Formula for calculating termination fee"},
            {"name": "declining_schedule", "type": "list", "role": "S", "required": False,
             "aliases": ["fee_schedule", "termination_schedule"],
             "description": "Declining termination fee schedule"},
            {"name": "extension_term_years", "type": "number", "role": "C", "required": False,
             "aliases": ["renewal_term"],
             "description": "Extension period length in years"},
            {"name": "extension_count", "type": "number", "role": "C", "required": False,
             "aliases": ["renewal_count", "extension_options"],
             "description": "Number of extensions allowed"},
            {"name": "early_termination_by_owner", "type": "string", "role": "C", "required": False,
             "aliases": ["seller_termination_rights"],
             "description": "Conditions for owner/seller termination"},
            {"name": "early_termination_by_buyer", "type": "string", "role": "C", "required": False,
             "aliases": ["buyer_termination_rights"],
             "description": "Conditions for buyer termination"},
            {"name": "termination_notice_days", "type": "number", "role": "C", "required": False,
             "aliases": ["notice_days", "notice_period"],
             "description": "Required notice period for termination"},
            {"name": "purchase_option_exists", "type": "boolean", "role": "C", "required": False,
             "aliases": ["buyout_option"],
             "description": "Whether buyer has purchase option"},
            {"name": "purchase_price_basis", "type": "string", "role": "C", "required": False,
             "aliases": ["buyout_basis", "fmv_basis"],
             "description": "Basis for purchase price: fair_market_value, book_value, fixed_price"},
        ]
    },
    "MAINTENANCE": {
        "fields": [
            {"name": "sla_targets", "type": "object", "role": "T", "required": False,
             "aliases": ["service_levels", "sla_metrics"],
             "description": "SLA target metrics"},
            {"name": "response_time_hours", "type": "number", "role": "FI", "required": False,
             "aliases": ["response_time", "sla_response"],
             "description": "Required response time for issues"},
            {"name": "spare_parts_obligation", "type": "string", "role": "C", "required": False,
             "aliases": ["spare_parts", "parts_obligation"],
             "description": "Spare parts inventory obligations"},
            {"name": "maintenance_responsible_party", "type": "string", "role": "C", "required": True,
             "aliases": ["responsible_party", "om_provider"],
             "description": "Who performs maintenance: owner, buyer, third_party"},
            {"name": "maintenance_standard", "type": "string", "role": "C", "required": False,
             "aliases": ["performance_standard", "industry_standard"],
             "description": "Standard to be met (e.g., prudent industry practice)"},
            {"name": "resolution_time_hours", "type": "number", "role": "FI", "required": False,
             "aliases": ["resolution_time", "repair_time"],
             "description": "Time to resolve issues"},
            {"name": "scheduled_outage_notice_days", "type": "number", "role": "C", "required": False,
             "aliases": ["notice_days"],
             "description": "Advance notice for planned outages"},
            {"name": "scheduled_outage_max_hours_per_year", "type": "number", "role": "C", "required": False,
             "aliases": ["max_outage_hours"],
             "description": "Maximum scheduled outage hours per year"},
        ]
    },
    "SECURITY_PACKAGE": {
        "fields": [
            {"name": "instrument_type", "type": "string", "role": "C", "required": True,
             "aliases": ["security_type", "type", "guarantee_type"],
             "description": "letter_of_credit, surety_bond, parent_guarantee, cash_deposit"},
            {"name": "amount", "type": "number", "role": "FI", "required": True,
             "aliases": ["security_amount", "lc_amount", "guarantee_amount"],
             "description": "Security amount in currency"},
            {"name": "security_currency", "type": "string", "role": "C", "required": False,
             "aliases": ["currency"],
             "description": "Currency of security instrument"},
            {"name": "release_conditions", "type": "list", "role": "S", "required": False,
             "aliases": ["release_triggers", "termination_conditions"],
             "description": "Conditions for releasing security"},
            {"name": "security_amount_formula", "type": "string", "role": "FD", "required": False,
             "aliases": ["amount_formula"],
             "description": "Formula if amount varies"},
            {"name": "issuer_requirements", "type": "string", "role": "C", "required": False,
             "aliases": ["issuer_rating", "bank_requirements"],
             "description": "Requirements for issuing institution"},
            {"name": "draw_conditions", "type": "list", "role": "S", "required": False,
             "aliases": ["call_conditions", "draw_triggers"],
             "description": "Conditions under which security can be drawn"},
            {"name": "replenishment_days", "type": "number", "role": "C", "required": False,
             "aliases": ["top_up_days", "replenishment_period"],
             "description": "Days to replenish security after a draw"},
        ]
    },
    "FORCE_MAJEURE": {
        "fields": [
            {"name": "events", "type": "list", "role": "S", "required": True,
             "aliases": ["defined_events", "fm_events", "qualifying_events"],
             "description": "List of qualifying force majeure events"},
            {"name": "notice_period_days", "type": "number", "role": "C", "required": False,
             "aliases": ["notification_period_hours", "notice_hours", "notice_days"],
             "description": "Time to notify other party"},
            {"name": "relief_scope", "type": "string", "role": "C", "required": False,
             "aliases": ["payment_obligations_during_fm", "relief_type"],
             "description": "Scope of relief during FM: suspended, partial, none"},
            {"name": "max_duration_days", "type": "number", "role": "C", "required": False,
             "aliases": ["maximum_duration", "termination_trigger_days"],
             "description": "Maximum FM period before termination rights"},
            {"name": "documentation_required", "type": "string", "role": "C", "required": False,
             "aliases": ["proof_required", "evidence_requirements"],
             "description": "Documentation needed to claim FM"},
        ]
    },
    "COMPLIANCE": {
        "fields": [
            {"name": "standards", "type": "list", "role": "S", "required": False,
             "aliases": ["required_permits", "environmental_standards", "applicable_standards"],
             "description": "List of compliance standards and permits"},
            {"name": "reporting_frequency", "type": "string", "role": "C", "required": False,
             "aliases": ["reporting_obligations", "report_frequency"],
             "description": "How often compliance reports are due"},
            {"name": "audit_rights", "type": "string", "role": "C", "required": False,
             "aliases": ["inspection_rights", "verification_rights"],
             "description": "Rights to audit/inspect compliance"},
            {"name": "compliance_responsible_party", "type": "string", "role": "C", "required": False,
             "aliases": ["responsible_party"],
             "description": "Who ensures compliance"},
            {"name": "change_in_law_provisions", "type": "string", "role": "C", "required": False,
             "aliases": ["change_of_law"],
             "description": "How law changes are handled"},
        ]
    },
    "LIQUIDATED_DAMAGES": {
        "fields": [
            {"name": "trigger_type", "type": "string", "role": "C", "required": True,
             "aliases": ["ld_type", "damages_type"],
             "description": "availability_shortfall, performance_shortfall, delay, non_delivery"},
            {"name": "calculation_type", "type": "string", "role": "C", "required": True,
             "aliases": ["calc_type", "method"],
             "description": "per_point, per_day, per_kwh, flat_fee, formula"},
            {"name": "rate", "type": "number", "role": "FI", "required": True,
             "aliases": ["ld_rate", "ld_per_point", "penalty_rate", "damages_rate"],
             "description": "LD rate value"},
            {"name": "rate_unit", "type": "string", "role": "C", "required": False,
             "aliases": ["unit"],
             "description": "Unit for rate: $/point, $/day, $/kWh"},
            {"name": "cap_type", "type": "string", "role": "C", "required": False,
             "aliases": ["cap_basis"],
             "description": "annual, cumulative, per_event, percentage_of_contract"},
            {"name": "cap_amount", "type": "number", "role": "FI", "required": False,
             "aliases": ["ld_cap", "ld_cap_annual", "damages_cap"],
             "description": "Cap value in currency"},
            {"name": "cumulative_cap", "type": "number", "role": "FI", "required": False,
             "aliases": ["lifetime_cap", "total_cap"],
             "description": "Cumulative cap over contract term"},
            {"name": "threshold_percent", "type": "number", "role": "T", "required": False,
             "aliases": ["trigger_threshold"],
             "description": "Threshold at which LDs are triggered"},
        ]
    },
    "GENERAL": {
        "fields": [
            {"name": "governing_law", "type": "string", "role": "C", "required": False,
             "aliases": ["applicable_law", "jurisdiction"],
             "description": "Applicable law/jurisdiction"},
            {"name": "dispute_resolution_method", "type": "string", "role": "C", "required": False,
             "aliases": ["dispute_method", "resolution_method"],
             "description": "litigation, arbitration, mediation"},
            {"name": "dispute_venue", "type": "string", "role": "C", "required": False,
             "aliases": ["venue", "forum"],
             "description": "Where disputes are heard"},
            {"name": "notice_method", "type": "string", "role": "C", "required": False,
             "aliases": ["notice_requirements"],
             "description": "How notices must be given"},
            {"name": "assignment_restrictions", "type": "string", "role": "C", "required": False,
             "aliases": ["assignment_rights"],
             "description": "Limitations on assignment"},
            {"name": "confidentiality_period_years", "type": "number", "role": "C", "required": False,
             "aliases": ["confidentiality_term"],
             "description": "Duration of confidentiality obligation"},
        ]
    },
}


# =============================================================================
# CANONICAL TERMINOLOGY — maps every known alias to canonical name
# =============================================================================
# Built dynamically from CANONICAL_SCHEMAS to stay in sync

def _build_canonical_terminology() -> dict:
    """Build the alias→canonical mapping from CANONICAL_SCHEMAS."""
    terminology = {}
    for category, schema in CANONICAL_SCHEMAS.items():
        for field in schema["fields"]:
            canonical_name = field["name"]
            for alias in field.get("aliases", []):
                terminology[alias] = canonical_name
    return terminology


CANONICAL_TERMINOLOGY = _build_canonical_terminology()


# =============================================================================
# CLAUSE EXAMPLES — gold-standard extractions using canonical field names
# =============================================================================

CLAUSE_EXAMPLES = {
    "CONDITIONS_PRECEDENT": {
        "example_raw_text": """
The obligations of Buyer under this Agreement are subject to the satisfaction
of the following conditions precedent on or before the Commercial Operation Date:
(a) Seller has obtained all permits and approvals required for construction and
operation of the Facility; (b) Seller has executed an interconnection agreement
with the Transmission Provider; (c) Seller has provided evidence of insurance
as required under Section 12; (d) The Facility has achieved Initial Synchronization
and operated continuously for 72 hours at 90% of Contract Capacity.
""",
        "example_extraction": {
            "clause_name": "Conditions Precedent to Commercial Operation",
            "category": "CONDITIONS_PRECEDENT",
            "normalized_payload": {
                "conditions": [
                    "All permits and approvals obtained",
                    "Interconnection agreement executed",
                    "Evidence of insurance provided",
                    "72-hour continuous operation at 90% capacity"
                ],
                "responsible_party_by_condition": "Seller",
                "satisfaction_deadline_days": None,
                "waiver_rights": False,
                "failure_consequences": "Buyer obligations not effective"
            }
        }
    },

    "AVAILABILITY": {
        "example_raw_text": """
Seller guarantees that the Facility shall achieve an Annual Availability of at
least ninety-five percent (95%) during each Contract Year, calculated as:
Availability = (Total Hours - Forced Outage Hours - Scheduled Maintenance Hours) / Total Hours.
Scheduled maintenance shall not exceed 200 hours per Contract Year and requires
30 days advance notice. Curtailment by the Transmission Provider shall be excluded
from the availability calculation.
""",
        "example_extraction": {
            "clause_name": "Availability Guarantee",
            "category": "AVAILABILITY",
            "normalized_payload": {
                "threshold": 95.0,
                "measurement_period": "annual",
                "calculation_method": "(Total Hours - Forced Outage - Scheduled Maintenance) / Total Hours",
                "excused_events": ["Transmission Provider curtailment"],
                "scheduled_outage_max_hours_per_year": 200,
                "scheduled_outage_notice_days": 30
            }
        }
    },

    "PERFORMANCE_GUARANTEE": {
        "example_raw_text": """
Seller guarantees that the Facility shall achieve a Performance Ratio of at least
80% and a Capacity Factor of at least 25% on an annual basis, adjusted for actual
solar irradiance. The Facility is permitted an annual degradation rate of 0.5%
per year from the baseline established in Year 1. Performance shall be measured
using data from the on-site meteorological station.
""",
        "example_extraction": {
            "clause_name": "Performance Guarantee",
            "category": "PERFORMANCE_GUARANTEE",
            "normalized_payload": {
                "threshold": 80.0,
                "variant": "performance_ratio",
                "guaranteed_annual_production_kwh": None,
                "measurement_period": "annual",
                "degradation_rate_percent_per_year": 0.5,
                "weather_adjustment_method": "Actual solar irradiance from on-site met station"
            }
        }
    },

    "LIQUIDATED_DAMAGES": {
        "example_raw_text": """
For each percentage point (or portion thereof) by which Annual Availability falls
below the Guaranteed Availability of 95%, Seller shall pay Buyer liquidated damages
equal to Fifty Thousand Dollars ($50,000) per percentage point. Liquidated damages
under this Section shall be capped at Five Hundred Thousand Dollars ($500,000) per
Contract Year and Ten Million Dollars ($10,000,000) over the Term.
""",
        "example_extraction": {
            "clause_name": "Availability Liquidated Damages",
            "category": "LIQUIDATED_DAMAGES",
            "normalized_payload": {
                "trigger_type": "availability_shortfall",
                "calculation_type": "per_point",
                "rate": 50000,
                "rate_unit": "$/percentage_point",
                "threshold_percent": 95.0,
                "cap_type": "annual",
                "cap_amount": 500000,
                "cumulative_cap": 10000000
            }
        }
    },

    "PRICING": {
        "example_raw_text": """
Buyer shall pay Seller for all Delivered Energy at a rate of $0.045 per kWh
(the "Contract Price") during the first Contract Year. The Contract Price shall
escalate annually at a fixed rate of 2.0% per year, commencing on the first
anniversary of the Commercial Operation Date. The Contract Price includes
compensation for all Environmental Attributes.
""",
        "example_extraction": {
            "clause_name": "Energy Pricing",
            "category": "PRICING",
            "normalized_payload": {
                "pricing_structure": "escalating",
                "base_rate_per_kwh": 0.045,
                "base_rate_unit": "$/kWh",
                "escalation_rate": 2.0,
                "escalation_index": "fixed",
                "includes_environmental_attributes": True
            }
        }
    },

    "PAYMENT_TERMS": {
        "example_raw_text": """
Seller shall submit monthly invoices to Buyer within ten (10) Business Days after
the end of each calendar month. Buyer shall pay all undisputed amounts within
thirty (30) days of receipt of invoice. Late payments shall accrue interest at
the Prime Rate plus 2%. Buyer commits to a minimum annual offtake of 80% of
Estimated Annual Production; shortfalls shall be paid at 75% of the Contract Price.
""",
        "example_extraction": {
            "clause_name": "Payment Terms",
            "category": "PAYMENT_TERMS",
            "normalized_payload": {
                "invoice_frequency": "monthly",
                "invoice_timing": "10 business days after month end",
                "payment_due_days": 30,
                "late_interest_rate": "Prime + 2%",
                "currency": "USD",
                "minimum_purchase_percent": 80,
                "take_or_pay_shortfall_rate": 0.75
            }
        }
    },

    "DEFAULT": {
        "example_raw_text": """
The following shall constitute Events of Default: (a) Seller fails to achieve
Commercial Operation within 18 months of the Effective Date; (b) Either Party
fails to make any payment when due and such failure continues for 30 days after
written notice; (c) Either Party becomes insolvent or files for bankruptcy.
The non-defaulting Party shall provide written notice and the defaulting Party
shall have 30 days to cure (or 90 days if the cure cannot reasonably be completed
within 30 days, provided diligent efforts are being made).
""",
        "example_extraction": {
            "clause_name": "Events of Default",
            "category": "DEFAULT",
            "normalized_payload": {
                "variant": "mutual",
                "owner_default_events": [
                    "Failure to achieve COD within 18 months",
                    "Failure to pay within 30 days of notice",
                    "Insolvency or bankruptcy"
                ],
                "buyer_default_events": [
                    "Failure to pay within 30 days of notice",
                    "Insolvency or bankruptcy"
                ],
                "cure_period_days": 30,
                "extended_cure_period_days": 90,
                "cure_notice_method": "written notice",
                "cross_default_applies": False
            }
        }
    },

    "FORCE_MAJEURE": {
        "example_raw_text": """
"Force Majeure" means any event beyond the reasonable control of the affected
Party, including: acts of God, earthquakes, floods, hurricanes; war, terrorism,
civil unrest; strikes or labor disputes; actions of governmental authorities;
and grid emergencies declared by the System Operator. The affected Party must
provide notice within 48 hours and use reasonable efforts to mitigate. If Force
Majeure continues for more than 365 consecutive days, either Party may terminate.
""",
        "example_extraction": {
            "clause_name": "Force Majeure",
            "category": "FORCE_MAJEURE",
            "normalized_payload": {
                "events": [
                    "Acts of God, earthquakes, floods, hurricanes",
                    "War, terrorism, civil unrest",
                    "Strikes or labor disputes",
                    "Governmental authority actions",
                    "Grid emergencies"
                ],
                "notice_period_days": 2,
                "documentation_required": "reasonable efforts to mitigate",
                "max_duration_days": 365,
                "relief_scope": "suspended"
            }
        }
    },

    "TERMINATION": {
        "example_raw_text": """
This Agreement shall have an initial term of twenty (20) years from the Commercial
Operation Date. Buyer shall have the option to extend for two (2) additional
five (5) year periods upon 180 days written notice prior to expiration. Either
Party may terminate for uncured default. Buyer has the option to purchase the
Facility at Fair Market Value upon expiration or early termination.
""",
        "example_extraction": {
            "clause_name": "Term and Termination",
            "category": "TERMINATION",
            "normalized_payload": {
                "initial_term_years": 20,
                "extension_term_years": 5,
                "extension_count": 2,
                "early_termination_by_owner": "uncured default",
                "early_termination_by_buyer": "uncured default",
                "termination_notice_days": 180,
                "purchase_option_exists": True,
                "purchase_price_basis": "fair_market_value"
            }
        }
    },

    "MAINTENANCE": {
        "example_raw_text": """
Seller shall operate and maintain the Facility in accordance with Prudent Industry
Practice and manufacturer recommendations. Seller shall respond to any outage
or material degradation within 4 hours and use best efforts to restore operation
within 24 hours. Scheduled maintenance requiring Facility shutdown shall not
exceed 168 hours per Contract Year and requires 14 days advance notice.
""",
        "example_extraction": {
            "clause_name": "Operation and Maintenance",
            "category": "MAINTENANCE",
            "normalized_payload": {
                "maintenance_responsible_party": "Seller",
                "maintenance_standard": "Prudent Industry Practice and manufacturer recommendations",
                "response_time_hours": 4,
                "resolution_time_hours": 24,
                "scheduled_outage_notice_days": 14,
                "scheduled_outage_max_hours_per_year": 168
            }
        }
    },

    "COMPLIANCE": {
        "example_raw_text": """
Seller shall obtain and maintain all permits, licenses, and approvals required
for construction and operation of the Facility, including environmental permits,
building permits, and interconnection approvals. Seller shall comply with all
applicable laws, including environmental regulations and renewable energy standards.
Seller shall provide quarterly compliance reports to Buyer.
""",
        "example_extraction": {
            "clause_name": "Regulatory Compliance",
            "category": "COMPLIANCE",
            "normalized_payload": {
                "compliance_responsible_party": "Seller",
                "standards": [
                    "Environmental permits",
                    "Building permits",
                    "Interconnection approvals"
                ],
                "reporting_frequency": "quarterly",
                "change_in_law_provisions": None
            }
        }
    },

    "SECURITY_PACKAGE": {
        "example_raw_text": """
Within 30 days of the Effective Date, Seller shall provide to Buyer a Letter of
Credit in the amount of $2,000,000 from a bank with a credit rating of at least
A- from S&P. The Letter of Credit shall remain in place until 12 months after
the Commercial Operation Date. Buyer may draw on the Letter of Credit upon any
uncured Event of Default by Seller or failure to achieve Commercial Operation Date.
""",
        "example_extraction": {
            "clause_name": "Performance Security",
            "category": "SECURITY_PACKAGE",
            "normalized_payload": {
                "instrument_type": "letter_of_credit",
                "amount": 2000000,
                "security_amount_formula": None,
                "issuer_requirements": "Bank with S&P rating A- or better",
                "release_conditions": ["12 months after Commercial Operation Date"],
                "draw_conditions": ["Uncured Event of Default", "Failure to achieve COD"]
            }
        }
    },

    "GENERAL": {
        "example_raw_text": """
This Agreement shall be governed by and construed in accordance with the laws of
the State of Texas. Any dispute shall first be subject to mediation, and if
unresolved within 60 days, shall be submitted to binding arbitration under AAA
Commercial Rules in Houston, Texas. Neither Party may assign this Agreement
without prior written consent, except to affiliates or for financing purposes.
""",
        "example_extraction": {
            "clause_name": "Governing Law and Disputes",
            "category": "GENERAL",
            "normalized_payload": {
                "governing_law": "State of Texas",
                "dispute_resolution_method": "mediation, then arbitration",
                "dispute_venue": "Houston, Texas (AAA Commercial Rules)",
                "notice_method": None,
                "assignment_restrictions": "Prior written consent required, except affiliates/financing",
                "confidentiality_period_years": None
            }
        }
    }
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_example_for_category(category_code: str) -> Optional[dict]:
    """Get the example for a specific category."""
    return CLAUSE_EXAMPLES.get(category_code, None)


def get_schema_for_category(category: str) -> Optional[dict]:
    """
    Returns the canonical schema for a category.

    Args:
        category: Category code (e.g., "AVAILABILITY")

    Returns:
        Schema dict with 'fields' list, or None if unknown category
    """
    return CANONICAL_SCHEMAS.get(category)


def get_required_fields(category: str) -> list:
    """
    Returns the list of required canonical field names for a category.

    Args:
        category: Category code (e.g., "PRICING")

    Returns:
        List of required field name strings
    """
    schema = CANONICAL_SCHEMAS.get(category)
    if not schema:
        return []
    return [f["name"] for f in schema["fields"] if f.get("required")]


def resolve_aliases(payload: dict, category: str) -> dict:
    """
    Rename aliased keys in a payload to their canonical names.

    Uses the category-specific schema first (for precision), then
    falls back to the global CANONICAL_TERMINOLOGY dict.

    Args:
        payload: The normalized_payload dict from extraction
        category: The clause category code

    Returns:
        New dict with canonical field names
    """
    if not payload:
        return {}

    # Build category-specific alias map
    category_aliases = {}
    schema = CANONICAL_SCHEMAS.get(category)
    if schema:
        for field in schema["fields"]:
            for alias in field.get("aliases", []):
                category_aliases[alias] = field["name"]

    resolved = {}
    for key, value in payload.items():
        # Try category-specific alias first
        canonical = category_aliases.get(key)
        if not canonical:
            # Fall back to global terminology
            canonical = CANONICAL_TERMINOLOGY.get(key, key)
        resolved[canonical] = value

    return resolved


def format_example_for_prompt(category_code: str) -> str:
    """Format an example for inclusion in the extraction prompt."""
    example = CLAUSE_EXAMPLES.get(category_code)
    if not example:
        return ""

    raw_text = example["example_raw_text"].strip()
    extraction = example["example_extraction"]

    # Format normalized_payload as compact JSON-like string
    payload_items = []
    for key, value in extraction["normalized_payload"].items():
        if value is not None:
            if isinstance(value, list):
                payload_items.append(f'"{key}": {value}')
            elif isinstance(value, str):
                payload_items.append(f'"{key}": "{value}"')
            else:
                payload_items.append(f'"{key}": {value}')

    payload_str = ", ".join(payload_items[:4])  # Limit to 4 items for brevity

    return f'''
**EXAMPLE:**
Raw: "{raw_text[:200]}..."
Extracted: {{"clause_name": "{extraction['clause_name']}", "normalized_payload": {{{payload_str}}}}}
'''


def format_schema_for_prompt(category: str) -> str:
    """
    Format the canonical schema for a category as prompt text with role annotations.

    Args:
        category: Category code

    Returns:
        Formatted string listing fields with types, roles, and descriptions
    """
    schema = CANONICAL_SCHEMAS.get(category)
    if not schema:
        return ""

    lines = []
    for field in schema["fields"]:
        required_tag = " (REQUIRED)" if field.get("required") else ""
        lines.append(
            f"- {field['name']} [{field['role']}] ({field['type']}){required_tag}: "
            f"{field['description']}"
        )
    return "\n".join(lines)
