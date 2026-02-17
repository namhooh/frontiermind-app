"""
Calculation modules for contract compliance formulas.

Named Calculator Registry pattern — each formula variant is a separate class,
dispatched via a registry dict keyed by the formula type code stored in
clause.normalized_payload or clause_tariff.logic_parameters.
"""
