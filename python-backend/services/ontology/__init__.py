"""
Ontology services for clause relationship management.

The ontology layer defines explicit relationships between clauses:
- TRIGGERS: Obligation breach causes consequence (availability -> LD)
- EXCUSES: Event type excuses obligation (force majeure -> availability)
- GOVERNS: Sets context for clauses (CP -> all obligations)
- INPUTS: Data flows between clauses (pricing -> payment)
"""

from .relationship_detector import RelationshipDetector
from .payload_validator import normalize_payload, validate_payload, ValidationResult

__all__ = ['RelationshipDetector', 'normalize_payload', 'validate_payload', 'ValidationResult']
