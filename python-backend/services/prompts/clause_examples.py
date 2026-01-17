# parked and unused for now

"""
Gold-standard example extractions for each clause category.

These examples guide Claude on:
- What good extractions look like
- How to populate normalized_payload fields correctly
- Key legal/financial terms to identify per category
"""

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
                "conditions_list": [
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
                "threshold_percent": 95.0,
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
                "guaranteed_performance_ratio_percent": 80.0,
                "guaranteed_capacity_factor_percent": 25.0,
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
                "base_rate": 0.045,
                "base_rate_unit": "$/kWh",
                "escalation_rate_percent_per_year": 2.0,
                "escalation_index": "fixed",
                "escalation_start_year": 2,
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
                "billing_frequency": "monthly",
                "invoice_timing": "10 business days after month end",
                "payment_due_days": 30,
                "late_payment_interest_rate_percent": "Prime + 2%",
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
                "defined_events": [
                    "Acts of God, earthquakes, floods, hurricanes",
                    "War, terrorism, civil unrest",
                    "Strikes or labor disputes",
                    "Governmental authority actions",
                    "Grid emergencies"
                ],
                "notification_period_hours": 48,
                "documentation_required": "reasonable efforts to mitigate",
                "max_duration_days": 365,
                "payment_obligations_during_fm": "suspended"
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
                "required_permits": [
                    "Environmental permits",
                    "Building permits",
                    "Interconnection approvals"
                ],
                "environmental_standards": ["Environmental regulations", "Renewable energy standards"],
                "reporting_obligations": "Quarterly compliance reports",
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
                "security_type": "letter_of_credit",
                "security_amount": 2000000,
                "security_amount_formula": None,
                "issuer_requirements": "Bank with S&P rating A- or better",
                "release_conditions": "12 months after Commercial Operation Date",
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


def get_example_for_category(category_code: str) -> dict:
    """Get the example for a specific category."""
    return CLAUSE_EXAMPLES.get(category_code, None)


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
