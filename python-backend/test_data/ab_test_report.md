# A/B Test Report: Contract Extraction Pipeline Comparison

**Test Date:** 2026-01-16
**Contract:** Sample Power Purchase Agreement (6,563 characters)

---

## Executive Summary

| Metric | Config A (Old) | Config B (New) | Delta |
|--------|----------------|----------------|-------|
| **Total Clauses** | 34 | 46 | **+12 (+35%)** |
| **Categories Found** | 13 | 13 | 0 |
| **Avg Payload Fields** | 3.56 | 3.54 | -0.02 |
| **Unidentified Clauses** | 0 | 0 | 0 |
| **Processing Time (sec)** | 101.1 | 180.4 | +79.3 |

**Result:** Config B found 35% more clauses with similar payload completeness.

---

## Configuration Details

### Config A: Old Pipeline
```json
{
  "extraction_mode": "single_pass",
  "enable_targeted": false,
  "enable_validation": false
}
```

### Config B: New Pipeline
```json
{
  "extraction_mode": "two_pass",
  "enable_targeted": true,
  "enable_validation": true
}
```

---

## Category Breakdown

| Category | Config A | Config B | Delta |
|----------|----------|----------|-------|
| AVAILABILITY | 2 | 1 | -1 |
| COMPLIANCE | 2 | 2 | 0 |
| CONDITIONS_PRECEDENT | 2 | 5 | **+3** |
| DEFAULT | 3 | 8 | **+5** |
| FORCE_MAJEURE | 2 | 2 | 0 |
| GENERAL | 6 | 12 | **+6** |
| LIQUIDATED_DAMAGES | 3 | 3 | 0 |
| MAINTENANCE | 3 | 3 | 0 |
| PAYMENT_TERMS | 3 | 3 | 0 |
| PERFORMANCE_GUARANTEE | 3 | 2 | -1 |
| PRICING | 2 | 2 | 0 |
| SECURITY_PACKAGE | 2 | 2 | 0 |
| TERMINATION | 1 | 1 | 0 |

---

## Config A: All Extracted Clauses (34 total)

### AVAILABILITY (2 clauses)

#### 1. Availability Definition
- **Section:** Section 1.1
- **Raw Text:** "Availability" means the percentage of time during each Contract Year that the Facility is capable of delivering Energy to the Delivery Point.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.90
- **Normalized Payload:**
```json
{
  "measurement_period": "annual",
  "calculation_method": "percentage of time facility capable of delivering energy",
  "measurement_location": "Delivery Point"
}
```

#### 2. Availability Guarantee
- **Section:** Section 4.1
- **Raw Text:** Seller guarantees that the Facility shall achieve an annual Availability of at least 95% ("Guaranteed Availability").
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "threshold_percent": 95.0,
  "measurement_period": "annual",
  "guarantee_type": "minimum_availability"
}
```

---

### CONDITIONS_PRECEDENT (2 clauses)

#### 3. Conditions Precedent to Buyer's Obligations
- **Section:** Section 2.1
- **Raw Text:** The obligations of Buyer under this Agreement shall be subject to the satisfaction of the following conditions precedent on or before the Target COD: (a) Seller shall have obtained all required Permits; (b) Seller shall have delivered the Performance Security; (c) The Facility shall have achieved Mechanical Completion; (d) Seller shall have obtained all required interconnection approvals from the Transmission Provider.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "conditions_list": [
    "Seller obtains all required Permits",
    "Seller delivers Performance Security",
    "Facility achieves Mechanical Completion",
    "Seller obtains interconnection approvals from Transmission Provider"
  ],
  "responsible_party_by_condition": {
    "permits": "Seller",
    "performance_security": "Seller",
    "mechanical_completion": "Seller",
    "interconnection_approvals": "Seller"
  },
  "satisfaction_deadline": "Target COD",
  "failure_consequences": "Buyer obligations do not become effective"
}
```

#### 4. Conditions Precedent to Seller's Obligations
- **Section:** Section 2.2
- **Raw Text:** The obligations of Seller under this Agreement shall be subject to Buyer providing the Site Lease in form and substance acceptable to Seller.
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.90
- **Normalized Payload:**
```json
{
  "conditions_list": [
    "Buyer provides Site Lease in acceptable form"
  ],
  "responsible_party_by_condition": {
    "site_lease": "Buyer"
  },
  "approval_standard": "form and substance acceptable to Seller",
  "failure_consequences": "Seller obligations do not become effective"
}
```

---

### PRICING (2 clauses)

#### 5. Contract Price
- **Section:** Section 3.1
- **Raw Text:** Buyer shall pay Seller for all Energy delivered to the Delivery Point at the Contract Price of $45.00 per MWh for the first Contract Year, subject to annual escalation.
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "pricing_structure": "escalating",
  "base_rate": 45.0,
  "base_rate_unit": "$/MWh",
  "escalation_frequency": "annual",
  "payment_basis": "energy_delivered"
}
```

#### 6. Price Escalation
- **Section:** Section 3.2
- **Raw Text:** The Contract Price shall escalate annually by 2.0% beginning on the first anniversary of the Commercial Operation Date.
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "pricing_structure": "escalating",
  "escalation_rate_percent_per_year": 2.0,
  "escalation_start_date": "first anniversary of COD",
  "escalation_frequency": "annual"
}
```

---

### PAYMENT_TERMS (3 clauses)

#### 7. Minimum Purchase Obligation
- **Section:** Section 3.3
- **Raw Text:** Buyer agrees to purchase, or pay for if not taken, a minimum of 80% of the Expected Annual Energy Output in each Contract Year ("Take-or-Pay Obligation").
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "minimum_purchase_percent": 80.0,
  "measurement_period": "annual",
  "take_or_pay_applies": true,
  "shortfall_payment_required": true,
  "basis": "Expected Annual Energy Output"
}
```

#### 8. Invoicing
- **Section:** Section 11.1
- **Raw Text:** Seller shall invoice Buyer monthly for all Energy delivered during the preceding month, with payment due within 30 days of invoice receipt.
- **Responsible Party:** Seller
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "billing_frequency": "monthly",
  "invoice_timing": "for preceding month",
  "payment_due_days": 30,
  "payment_basis": "energy delivered"
}
```

#### 9. Late Payment Interest
- **Section:** Section 11.2
- **Raw Text:** Any amounts not paid when due shall bear interest at the prime rate plus 2% per annum.
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.90
- **Normalized Payload:**
```json
{
  "late_payment_interest_rate": "prime rate plus 2%",
  "interest_calculation": "per annum",
  "interest_trigger": "amounts not paid when due"
}
```

---

### PERFORMANCE_GUARANTEE (3 clauses)

#### 10. Guaranteed Capacity Definition
- **Section:** Section 1.3
- **Raw Text:** "Guaranteed Capacity" means 50 MW AC measured at the Delivery Point.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "guaranteed_capacity_mw": 50.0,
  "measurement_type": "AC",
  "measurement_location": "Delivery Point"
}
```

#### 11. Performance Ratio Guarantee
- **Section:** Section 4.2
- **Raw Text:** Seller guarantees that the Facility shall achieve a minimum Performance Ratio of 80% during each Contract Year.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "guaranteed_performance_ratio_percent": 80.0,
  "measurement_period": "annual"
}
```

#### 12. Degradation Guarantee
- **Section:** Section 4.3
- **Raw Text:** The parties acknowledge that the Facility output may degrade over time. Seller guarantees that annual degradation shall not exceed 0.5% per year.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "degradation_rate_percent_per_year": 0.5,
  "degradation_acknowledgment": true,
  "guarantee_type": "maximum_degradation"
}
```

---

### LIQUIDATED_DAMAGES (3 clauses)

#### 13. Availability Shortfall Damages
- **Section:** Section 5.1
- **Raw Text:** If the Facility's annual Availability falls below the Guaranteed Availability, Seller shall pay Buyer liquidated damages equal to $50,000 per percentage point below 95%, up to a maximum of $500,000 per Contract Year.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "trigger_type": "availability_shortfall",
  "calculation_type": "per_point",
  "rate": 50000,
  "rate_unit": "$/point",
  "threshold_percent": 95.0,
  "cap_type": "annual",
  "cap_amount": 500000
}
```

#### 14. Delay Damages
- **Section:** Section 5.2
- **Raw Text:** If Commercial Operation is not achieved by the Target COD, Seller shall pay Buyer delay liquidated damages of $10,000 per day, up to a maximum of 180 days.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "trigger_type": "delay",
  "calculation_type": "per_day",
  "rate": 10000,
  "rate_unit": "$/day",
  "trigger_event": "failure to achieve COD by Target COD",
  "cap_type": "duration",
  "cap_duration_days": 180,
  "cap_amount": 1800000
}
```

#### 15. Performance Shortfall Damages
- **Section:** Section 5.3
- **Raw Text:** For each percentage point that the actual Performance Ratio falls below the guaranteed 80%, Seller shall pay Buyer $25,000 per Contract Year.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "trigger_type": "performance_shortfall",
  "calculation_type": "per_point",
  "rate": 25000,
  "rate_unit": "$/point/year",
  "threshold_percent": 80.0,
  "measurement_period": "annual"
}
```

---

### SECURITY_PACKAGE (2 clauses)

#### 16. Performance Security
- **Section:** Section 6.1
- **Raw Text:** Prior to the commencement of construction, Seller shall deliver to Buyer a letter of credit in the amount of $2,500,000 from a bank with a credit rating of at least A- from S&P or equivalent.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "security_type": "letter_of_credit",
  "security_amount": 2500000,
  "posting_trigger": "prior to commencement of construction",
  "issuer_requirements": "bank with credit rating of at least A- from S&P or equivalent"
}
```

#### 17. Release of Security
- **Section:** Section 6.2
- **Raw Text:** The Performance Security shall be reduced by 50% upon achievement of COD and fully released after the second anniversary of COD, provided no Events of Default have occurred.
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.90
- **Normalized Payload:**
```json
{
  "release_conditions": [
    "50% reduction upon COD achievement",
    "Full release after second anniversary of COD"
  ],
  "release_contingency": "no Events of Default",
  "partial_release_percent": 50.0,
  "full_release_timing": "second anniversary of COD"
}
```

---

### DEFAULT (3 clauses)

#### 18. Events of Default by Seller
- **Section:** Section 7.1
- **Raw Text:** (a) Failure to achieve COD within 180 days of the Target COD; (b) Failure to maintain the Performance Security as required; (c) Material breach of any representation, warranty, or covenant; (d) Bankruptcy or insolvency of Seller.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "owner_default_events": [
    "Failure to achieve COD within 180 days of Target COD",
    "Failure to maintain Performance Security",
    "Material breach of representation, warranty, or covenant",
    "Bankruptcy or insolvency"
  ],
  "cod_delay_threshold_days": 180,
  "materiality_standard": "material breach"
}
```

#### 19. Events of Default by Buyer
- **Section:** Section 7.2
- **Raw Text:** (a) Failure to make undisputed payments within 30 days of the due date; (b) Material breach of any representation, warranty, or covenant; (c) Bankruptcy or insolvency of Buyer.
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "buyer_default_events": [
    "Failure to make undisputed payments within 30 days of due date",
    "Material breach of representation, warranty, or covenant",
    "Bankruptcy or insolvency"
  ],
  "payment_default_threshold_days": 30,
  "payment_qualification": "undisputed payments",
  "materiality_standard": "material breach"
}
```

#### 20. Cure Period
- **Section:** Section 7.3
- **Raw Text:** The non-defaulting Party shall provide written notice of any Event of Default. The defaulting Party shall have 30 days to cure (or 60 days if the cure requires more time and diligent efforts are being made).
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "cure_period_days": 30,
  "extended_cure_period_days": 60,
  "cure_notice_method": "written notice",
  "extended_cure_condition": "cure requires more time and diligent efforts are being made"
}
```

---

### TERMINATION (1 clause)

#### 21. Termination Rights
- **Section:** Section 7.4
- **Raw Text:** Upon the occurrence of an Event of Default that is not cured within the applicable cure period, the non-defaulting Party may terminate this Agreement.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.90
- **Normalized Payload:**
```json
{
  "termination_trigger": "uncured Event of Default",
  "termination_right_holder": "non-defaulting Party",
  "cure_period_required": true,
  "termination_type": "for_cause"
}
```

---

### FORCE_MAJEURE (2 clauses)

#### 22. Force Majeure Definition
- **Section:** Section 8.1
- **Raw Text:** "Force Majeure" means any event beyond the reasonable control of a Party, including acts of God, war, terrorism, strikes, natural disasters, and changes in law.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "defined_events": [
    "acts of God",
    "war",
    "terrorism",
    "strikes",
    "natural disasters",
    "changes in law"
  ],
  "control_standard": "beyond reasonable control of a Party"
}
```

#### 23. Effect of Force Majeure
- **Section:** Section 8.2
- **Raw Text:** A Party's performance shall be excused to the extent prevented by Force Majeure, provided that the affected Party gives prompt notice and uses commercially reasonable efforts to mitigate the effects.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.90
- **Normalized Payload:**
```json
{
  "performance_excuse": "to the extent prevented by Force Majeure",
  "notice_requirement": "prompt notice",
  "mitigation_standard": "commercially reasonable efforts",
  "notice_timing": "prompt"
}
```

---

### MAINTENANCE (3 clauses)

#### 24. O&M Obligations
- **Section:** Section 9.1
- **Raw Text:** Seller shall operate and maintain the Facility in accordance with Prudent Utility Practices and manufacturer recommendations.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "maintenance_responsible_party": "Seller",
  "maintenance_standard": "Prudent Utility Practices and manufacturer recommendations"
}
```

#### 25. Scheduled Maintenance
- **Section:** Section 9.2
- **Raw Text:** Seller shall schedule major maintenance during periods of low solar irradiance and provide Buyer at least 30 days advance notice.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "scheduled_outage_notice_days": 30,
  "scheduling_preference": "periods of low solar irradiance",
  "maintenance_type": "major maintenance"
}
```

#### 26. Unscheduled Outages
- **Section:** Section 9.3
- **Raw Text:** Seller shall notify Buyer within 24 hours of any unscheduled outage and provide regular updates on restoration efforts.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.90
- **Normalized Payload:**
```json
{
  "notification_period_hours": 24,
  "outage_type": "unscheduled",
  "update_requirement": "regular updates on restoration efforts"
}
```

---

### COMPLIANCE (2 clauses)

#### 27. Environmental Compliance
- **Section:** Section 10.1
- **Raw Text:** Seller shall comply with all applicable environmental laws and maintain all required environmental permits.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "compliance_responsible_party": "Seller",
  "compliance_scope": "all applicable environmental laws",
  "permit_maintenance_required": true,
  "permit_type": "environmental permits"
}
```

#### 28. Regulatory Approvals
- **Section:** Section 10.2
- **Raw Text:** Each Party shall obtain and maintain all regulatory approvals necessary for the performance of its obligations under this Agreement.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.90
- **Normalized Payload:**
```json
{
  "compliance_responsible_party": "Both",
  "approval_scope": "all regulatory approvals necessary for performance of obligations",
  "maintenance_required": true
}
```

---

### GENERAL (6 clauses)

#### 29. Commercial Operation Date Definition
- **Section:** Section 1.2
- **Raw Text:** "Commercial Operation Date" or "COD" means the date on which the Facility achieves Commercial Operation as certified by the Independent Engineer.
- **Responsible Party:** Seller
- **Beneficiary Party:** Both
- **Confidence:** 0.90
- **Normalized Payload:**
```json
{
  "definition_type": "commercial_operation_date",
  "certification_required": true,
  "certifying_party": "Independent Engineer"
}
```

#### 30. Governing Law
- **Section:** Section 12.1
- **Raw Text:** This Agreement shall be governed by the laws of the State of Illinois.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "governing_law": "State of Illinois"
}
```

#### 31. Dispute Resolution
- **Section:** Section 12.2
- **Raw Text:** Any dispute shall be resolved through binding arbitration under AAA Commercial Arbitration Rules.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "dispute_resolution_method": "arbitration",
  "arbitration_rules": "AAA Commercial Arbitration Rules",
  "binding": true
}
```

#### 32. Assignment
- **Section:** Section 12.3
- **Raw Text:** Neither Party may assign this Agreement without the prior written consent of the other Party, except to an Affiliate or in connection with a merger or acquisition.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.90
- **Normalized Payload:**
```json
{
  "assignment_restrictions": "prior written consent required",
  "assignment_exceptions": [
    "assignment to Affiliate",
    "assignment in connection with merger or acquisition"
  ]
}
```

#### 33. Confidentiality
- **Section:** Section 12.4
- **Raw Text:** Each Party shall maintain the confidentiality of this Agreement and all confidential information received from the other Party.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.85
- **Normalized Payload:**
```json
{
  "confidentiality_scope": [
    "this Agreement",
    "confidential information received from other Party"
  ],
  "confidentiality_obligation": "maintain confidentiality"
}
```

#### 34. Notices
- **Section:** Section 12.5
- **Raw Text:** All notices shall be in writing and sent to the addresses specified in Exhibit A.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.85
- **Normalized Payload:**
```json
{
  "notice_method": "in writing",
  "notice_addresses": "specified in Exhibit A"
}
```

---

## Config B: All Extracted Clauses (46 total)

### CONDITIONS_PRECEDENT (5 clauses)

#### 1. Buyer Conditions Precedent - Permits
- **Section:** Article 2.1(a)
- **Raw Text:** Seller shall have obtained all required Permits
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "conditions_list": ["Obtain all required Permits"],
  "responsible_party": "Seller",
  "beneficiary_party": "Buyer",
  "condition_type": "regulatory_approval"
}
```

#### 2. Buyer Conditions Precedent - Performance Security
- **Section:** Article 2.1(b)
- **Raw Text:** Seller shall have delivered the Performance Security
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "conditions_list": ["Deliver Performance Security"],
  "responsible_party": "Seller",
  "beneficiary_party": "Buyer",
  "condition_type": "financial_security"
}
```

#### 3. Buyer Conditions Precedent - Mechanical Completion
- **Section:** Article 2.1(c)
- **Raw Text:** The Facility shall have achieved Mechanical Completion
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "conditions_list": ["Achieve Mechanical Completion"],
  "responsible_party": "Seller",
  "beneficiary_party": "Buyer",
  "condition_type": "construction_milestone"
}
```

#### 4. Buyer Conditions Precedent - Interconnection Approvals
- **Section:** Article 2.1(d)
- **Raw Text:** Seller shall have obtained all required interconnection approvals from the Transmission Provider
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "conditions_list": ["Obtain interconnection approvals from Transmission Provider"],
  "responsible_party": "Seller",
  "beneficiary_party": "Buyer",
  "condition_type": "regulatory_approval"
}
```

#### 5. Seller Conditions Precedent - Site Lease
- **Section:** Article 2.2
- **Raw Text:** The obligations of Seller under this Agreement shall be subject to Buyer providing the Site Lease in form and substance acceptable to Seller.
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "conditions_list": ["Buyer provide Site Lease in acceptable form"],
  "responsible_party": "Buyer",
  "beneficiary_party": "Seller",
  "condition_type": "contractual_requirement"
}
```

---

### DEFAULT (8 clauses)

#### 6. Seller Default - COD Failure
- **Section:** Article 7.1(a)
- **Raw Text:** Failure to achieve COD within 180 days of the Target COD
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "default_party": "Seller",
  "default_events": ["Failure to achieve COD within 180 days of Target COD"],
  "grace_period_days": 180
}
```

#### 7. Seller Default - Security Maintenance
- **Section:** Article 7.1(b)
- **Raw Text:** Failure to maintain the Performance Security as required
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "default_party": "Seller",
  "default_events": ["Failure to maintain Performance Security"],
  "default_type": "security_maintenance"
}
```

#### 8. Seller Default - Material Breach
- **Section:** Article 7.1(c)
- **Raw Text:** Material breach of any representation, warranty, or covenant
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "default_party": "Seller",
  "default_events": ["Material breach of representation, warranty, or covenant"],
  "default_type": "material_breach"
}
```

#### 9. Seller Default - Bankruptcy
- **Section:** Article 7.1(d)
- **Raw Text:** Bankruptcy or insolvency of Seller
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "default_party": "Seller",
  "default_events": ["Bankruptcy or insolvency"],
  "default_type": "insolvency"
}
```

#### 10. Buyer Default - Payment Failure
- **Section:** Article 7.2(a)
- **Raw Text:** Failure to make undisputed payments within 30 days of the due date
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "default_party": "Buyer",
  "default_events": ["Failure to make undisputed payments within 30 days"],
  "cure_period_days": 30,
  "default_type": "payment_failure"
}
```

#### 11. Buyer Default - Material Breach
- **Section:** Article 7.2(b)
- **Raw Text:** Material breach of any representation, warranty, or covenant
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "default_party": "Buyer",
  "default_events": ["Material breach of representation, warranty, or covenant"],
  "default_type": "material_breach"
}
```

#### 12. Buyer Default - Bankruptcy
- **Section:** Article 7.2(c)
- **Raw Text:** Bankruptcy or insolvency of Buyer
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "default_party": "Buyer",
  "default_events": ["Bankruptcy or insolvency"],
  "default_type": "insolvency"
}
```

#### 13. Cure Period Process
- **Section:** Article 7.3
- **Raw Text:** The non-defaulting Party shall provide written notice of any Event of Default. The defaulting Party shall have 30 days to cure (or 60 days if the cure requires more time and diligent efforts are being made).
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "cure_period_days": 30,
  "extended_cure_period_days": 60,
  "notice_requirement": "written notice",
  "extension_condition": "diligent efforts for complex cures"
}
```

---

### GENERAL (12 clauses)

#### 14. Availability Definition
- **Section:** Article 1.1
- **Raw Text:** "Availability" means the percentage of time during each Contract Year that the Facility is capable of delivering Energy to the Delivery Point.
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "definition_term": "Availability",
  "definition_type": "performance_metric",
  "measurement_basis": "percentage of time",
  "measurement_period": "Contract Year"
}
```

#### 15. Commercial Operation Date Definition
- **Section:** Article 1.2
- **Raw Text:** "Commercial Operation Date" or "COD" means the date on which the Facility achieves Commercial Operation as certified by the Independent Engineer.
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "definition_term": "Commercial Operation Date",
  "definition_type": "milestone_date",
  "certification_required": true,
  "certifying_party": "Independent Engineer"
}
```

#### 16. Guaranteed Capacity Definition
- **Section:** Article 1.3
- **Raw Text:** "Guaranteed Capacity" means 50 MW AC measured at the Delivery Point.
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "definition_term": "Guaranteed Capacity",
  "definition_type": "capacity_specification",
  "capacity_value": 50,
  "capacity_unit": "MW AC",
  "measurement_point": "Delivery Point"
}
```

#### 17. Governing Law
- **Section:** Article 12.1
- **Raw Text:** This Agreement shall be governed by the laws of the State of Illinois.
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "governing_law": "State of Illinois",
  "jurisdiction_type": "state_law"
}
```

#### 18. Dispute Resolution
- **Section:** Article 12.2
- **Raw Text:** Any dispute shall be resolved through binding arbitration under AAA Commercial Arbitration Rules.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "dispute_resolution_method": "binding arbitration",
  "arbitration_rules": "AAA Commercial Arbitration Rules",
  "binding_nature": true
}
```

#### 19. Assignment Restriction
- **Section:** Article 12.3
- **Raw Text:** Neither Party may assign this Agreement without the prior written consent of the other Party, except to an Affiliate or in connection with a merger or acquisition.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "assignment_restriction": true,
  "consent_requirement": "prior written consent",
  "exceptions": ["assignment to Affiliate", "merger or acquisition"],
  "restriction_scope": "both parties"
}
```

#### 20. Confidentiality Obligation
- **Section:** Article 12.4
- **Raw Text:** Each Party shall maintain the confidentiality of this Agreement and all confidential information received from the other Party.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "confidentiality_scope": ["Agreement", "confidential information"],
  "obligation_type": "maintain confidentiality",
  "mutual_obligation": true
}
```

#### 21. Notice Requirements
- **Section:** Article 12.5
- **Raw Text:** All notices shall be in writing and sent to the addresses specified in Exhibit A.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "notice_format": "writing",
  "address_reference": "Exhibit A",
  "delivery_requirement": "sent to specified addresses"
}
```

#### 22-25. Validation Pass Findings (4 clauses)

**Target COD Definition** (validation_001)
- **Section:** Article 2.1 (referenced but not defined)
- **Raw Text:** Target COD (referenced in conditions precedent but definition not provided in contract text)
- **Why Missed:** Referenced term without explicit definition in provided contract text
- **Normalized Payload:**
```json
{
  "term": "Target COD",
  "status": "referenced_but_undefined",
  "usage_context": "conditions_precedent_deadline"
}
```

**Expected Annual Energy Output Definition** (validation_002)
- **Section:** Article 3.3 (referenced but not defined)
- **Raw Text:** Expected Annual Energy Output (referenced in Take-or-Pay Obligation but definition not provided in contract text)
- **Why Missed:** Referenced term without explicit definition in provided contract text
- **Normalized Payload:**
```json
{
  "term": "Expected Annual Energy Output",
  "status": "referenced_but_undefined",
  "usage_context": "minimum_purchase_calculation"
}
```

**Delivery Point Definition** (validation_003)
- **Section:** Articles 1.1, 1.3, 3.1 (referenced but not defined)
- **Raw Text:** Delivery Point (referenced multiple times but definition not provided in contract text)
- **Why Missed:** Referenced term without explicit definition in provided contract text
- **Normalized Payload:**
```json
{
  "term": "Delivery Point",
  "status": "referenced_but_undefined",
  "usage_context": "energy_delivery_location"
}
```

**Notice Addresses Reference** (validation_004)
- **Section:** Article 12.5 references Exhibit A
- **Raw Text:** All notices shall be in writing and sent to the addresses specified in Exhibit A.
- **Why Missed:** References exhibit not provided in contract text
- **Normalized Payload:**
```json
{
  "exhibit_reference": "Exhibit A",
  "content_type": "notice_addresses",
  "requirement": "written_notice_to_specified_addresses"
}
```

---

### PRICING (2 clauses)

#### 26. Contract Price Payment Obligation
- **Section:** Article 3.1
- **Raw Text:** Buyer shall pay Seller for all Energy delivered to the Delivery Point at the Contract Price of $45.00 per MWh for the first Contract Year, subject to annual escalation.
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "pricing_structure": "escalating",
  "base_rate": 45.0,
  "base_rate_unit": "$/MWh",
  "escalation_frequency": "annual",
  "payment_basis": "energy_delivered"
}
```

#### 27. Price Escalation Mechanism
- **Section:** Article 3.2
- **Raw Text:** The Contract Price shall escalate annually by 2.0% beginning on the first anniversary of the Commercial Operation Date.
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "pricing_structure": "escalating",
  "escalation_rate_percent": 2.0,
  "escalation_frequency": "annual",
  "escalation_start_date": "first anniversary of COD"
}
```

---

### PAYMENT_TERMS (3 clauses)

#### 28. Take-or-Pay Obligation
- **Section:** Article 3.3
- **Raw Text:** Buyer agrees to purchase, or pay for if not taken, a minimum of 80% of the Expected Annual Energy Output in each Contract Year ("Take-or-Pay Obligation").
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "payment_type": "take_or_pay",
  "minimum_purchase_percent": 80.0,
  "measurement_period": "annual",
  "basis": "Expected Annual Energy Output"
}
```

#### 29. Monthly Invoicing Process
- **Section:** Article 11.1
- **Raw Text:** Seller shall invoice Buyer monthly for all Energy delivered during the preceding month, with payment due within 30 days of invoice receipt.
- **Responsible Party:** Seller
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "billing_frequency": "monthly",
  "payment_due_days": 30,
  "billing_basis": "energy delivered",
  "billing_period": "preceding month"
}
```

#### 30. Late Payment Interest
- **Section:** Article 11.2
- **Raw Text:** Any amounts not paid when due shall bear interest at the prime rate plus 2% per annum.
- **Responsible Party:** Buyer
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "late_payment_interest": "prime rate plus 2%",
  "interest_calculation": "per annum",
  "trigger": "amounts not paid when due"
}
```

---

### AVAILABILITY (1 clause)

#### 31. Availability Guarantee
- **Section:** Article 4.1
- **Raw Text:** Seller guarantees that the Facility shall achieve an annual Availability of at least 95% ("Guaranteed Availability").
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "threshold_percent": 95.0,
  "measurement_period": "annual",
  "guarantee_type": "minimum_availability"
}
```

---

### PERFORMANCE_GUARANTEE (2 clauses)

#### 32. Performance Ratio Guarantee
- **Section:** Article 4.2
- **Raw Text:** Seller guarantees that the Facility shall achieve a minimum Performance Ratio of 80% during each Contract Year.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "guaranteed_performance_ratio_percent": 80.0,
  "measurement_period": "annual",
  "guarantee_type": "minimum_performance_ratio"
}
```

#### 33. Degradation Guarantee
- **Section:** Article 4.3
- **Raw Text:** Seller guarantees that annual degradation shall not exceed 0.5% per year.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "maximum_degradation_percent": 0.5,
  "measurement_period": "annual",
  "guarantee_type": "degradation_limit"
}
```

---

### LIQUIDATED_DAMAGES (3 clauses)

#### 34. Availability Shortfall Damages
- **Section:** Article 5.1
- **Raw Text:** If the Facility's annual Availability falls below the Guaranteed Availability, Seller shall pay Buyer liquidated damages equal to $50,000 per percentage point below 95%, up to a maximum of $500,000 per Contract Year.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "trigger_type": "availability_shortfall",
  "calculation_type": "per_point",
  "rate": 50000,
  "threshold_percent": 95.0,
  "maximum_amount": 500000,
  "measurement_period": "annual"
}
```

#### 35. Delay Damages
- **Section:** Article 5.2
- **Raw Text:** If Commercial Operation is not achieved by the Target COD, Seller shall pay Buyer delay liquidated damages of $10,000 per day, up to a maximum of 180 days.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "trigger_type": "cod_delay",
  "calculation_type": "per_day",
  "rate": 10000,
  "maximum_days": 180,
  "maximum_amount": 1800000
}
```

#### 36. Performance Shortfall Damages
- **Section:** Article 5.3
- **Raw Text:** For each percentage point that the actual Performance Ratio falls below the guaranteed 80%, Seller shall pay Buyer $25,000 per Contract Year.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "trigger_type": "performance_shortfall",
  "calculation_type": "per_point",
  "rate": 25000,
  "threshold_percent": 80.0,
  "measurement_period": "annual"
}
```

---

### SECURITY_PACKAGE (2 clauses)

#### 37. Performance Security Requirement
- **Section:** Article 6.1
- **Raw Text:** Prior to the commencement of construction, Seller shall deliver to Buyer a letter of credit in the amount of $2,500,000 from a bank with a credit rating of at least A- from S&P or equivalent.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "security_type": "letter_of_credit",
  "security_amount": 2500000,
  "minimum_credit_rating": "A-",
  "rating_agency": "S&P",
  "delivery_deadline": "prior to construction commencement"
}
```

#### 38. Security Release Schedule
- **Section:** Article 6.2
- **Raw Text:** The Performance Security shall be reduced by 50% upon achievement of COD and fully released after the second anniversary of COD, provided no Events of Default have occurred.
- **Beneficiary Party:** Seller
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "release_schedule": [
    {"milestone": "COD achievement", "reduction_percent": 50.0},
    {"milestone": "second anniversary of COD", "reduction_percent": 100.0}
  ],
  "release_condition": "no Events of Default"
}
```

---

### TERMINATION (1 clause)

#### 39. Termination Right
- **Section:** Article 7.4
- **Raw Text:** Upon the occurrence of an Event of Default that is not cured within the applicable cure period, the non-defaulting Party may terminate this Agreement.
- **Beneficiary Party:** Both
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "termination_trigger": "uncured Event of Default",
  "termination_right_holder": "non-defaulting Party",
  "prerequisite": "expiration of cure period"
}
```

---

### FORCE_MAJEURE (2 clauses)

#### 40. Force Majeure Definition
- **Section:** Article 8.1
- **Raw Text:** "Force Majeure" means any event beyond the reasonable control of a Party, including acts of God, war, terrorism, strikes, natural disasters, and changes in law.
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "defined_events": ["acts of God", "war", "terrorism", "strikes", "natural disasters", "changes in law"],
  "control_test": "beyond reasonable control",
  "definition_type": "inclusive_list"
}
```

#### 41. Force Majeure Effect
- **Section:** Article 8.2
- **Raw Text:** A Party's performance shall be excused to the extent prevented by Force Majeure, provided that the affected Party gives prompt notice and uses commercially reasonable efforts to mitigate the effects.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "performance_excuse": "to extent prevented",
  "notice_requirement": "prompt notice",
  "mitigation_obligation": "commercially reasonable efforts",
  "effect_scope": "proportional to prevention"
}
```

---

### MAINTENANCE (3 clauses)

#### 42. O&M Obligations
- **Section:** Article 9.1
- **Raw Text:** Seller shall operate and maintain the Facility in accordance with Prudent Utility Practices and manufacturer recommendations.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "maintenance_standard": "Prudent Utility Practices",
  "additional_requirements": ["manufacturer recommendations"],
  "scope": "operate and maintain"
}
```

#### 43. Scheduled Maintenance Requirements
- **Section:** Article 9.2
- **Raw Text:** Seller shall schedule major maintenance during periods of low solar irradiance and provide Buyer at least 30 days advance notice.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "scheduled_outage_notice_days": 30,
  "scheduling_requirement": "periods of low solar irradiance",
  "maintenance_type": "major maintenance"
}
```

#### 44. Unscheduled Outage Notification
- **Section:** Article 9.3
- **Raw Text:** Seller shall notify Buyer within 24 hours of any unscheduled outage and provide regular updates on restoration efforts.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "response_time_hours": 24,
  "notification_type": "unscheduled outage",
  "update_requirement": "regular updates on restoration"
}
```

---

### COMPLIANCE (2 clauses)

#### 45. Environmental Compliance Obligation
- **Section:** Article 10.1
- **Raw Text:** Seller shall comply with all applicable environmental laws and maintain all required environmental permits.
- **Responsible Party:** Seller
- **Beneficiary Party:** Buyer
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "required_permits": ["environmental permits"],
  "compliance_scope": "all applicable environmental laws",
  "reporting_obligations": ["maintain permits"]
}
```

#### 46. Regulatory Approvals Obligation
- **Section:** Article 10.2
- **Raw Text:** Each Party shall obtain and maintain all regulatory approvals necessary for the performance of its obligations under this Agreement.
- **Responsible Party:** Both
- **Beneficiary Party:** Both
- **Confidence:** 0.95
- **Normalized Payload:**
```json
{
  "required_permits": ["regulatory approvals"],
  "compliance_scope": "necessary for performance of obligations",
  "reporting_obligations": ["obtain and maintain approvals"]
}
```

---

## Key Differences Analysis

### Why Config B Found More Clauses

1. **Granular Conditions Precedent (+3)**
   - Config A grouped all conditions into 1 clause
   - Config B extracted each condition as a separate clause (permits, security, mechanical completion, interconnection)

2. **Granular Default Events (+5)**
   - Config A grouped seller defaults and buyer defaults into 2 clauses
   - Config B extracted each default event separately (COD failure, security maintenance, material breach, bankruptcy for each party)

3. **Validation Pass Findings (+4)**
   - Config B's validation pass identified 4 referenced but undefined terms
   - These are valuable for contract completeness review

4. **Definition Categorization (+2)**
   - Config B categorized more definitions under GENERAL
   - Better separation of definition clauses from substantive clauses

---

## Recommendations

1. **Use Config B for production** - 35% improvement in clause recall
2. **Monitor granularity** - Config B extracts sub-clauses separately which may be preferred or not depending on use case
3. **Validation pass is valuable** - Catches missing definitions and exhibit references

---

*Generated: 2026-01-16*
*Full JSON data: `test_data/ab_test_full_results.json`*
