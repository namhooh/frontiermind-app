"""
API endpoints for ontology management.

Provides REST interface for:
- Querying obligations
- Managing clause relationships
- Detecting relationships
- Relationship graph queries
"""

from typing import Optional, List
import logging

from fastapi import APIRouter, Query, HTTPException, Path
from pydantic import BaseModel, Field

from services.ontology import RelationshipDetector
from db.ontology_repository import OntologyRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ontology", tags=["Ontology"])


# ==================================================
# Request/Response Models
# ==================================================

class RelationshipCreate(BaseModel):
    """Request body for creating a relationship."""
    source_clause_id: int = Field(..., description="Source clause ID")
    target_clause_id: int = Field(..., description="Target clause ID")
    relationship_type: str = Field(
        ...,
        description="Type: TRIGGERS, EXCUSES, GOVERNS, or INPUTS"
    )
    is_cross_contract: bool = Field(
        default=False,
        description="Whether relationship spans contracts"
    )
    parameters: Optional[dict] = Field(
        default=None,
        description="Optional relationship-specific parameters"
    )


class RelationshipResponse(BaseModel):
    """Response model for a relationship."""
    id: int
    source_clause_id: int
    target_clause_id: int
    relationship_type: str
    is_cross_contract: bool
    parameters: dict
    is_inferred: bool
    confidence: Optional[float]
    source_clause_name: Optional[str]
    source_category_code: Optional[str]
    target_clause_name: Optional[str]
    target_category_code: Optional[str]


class ObligationResponse(BaseModel):
    """Response model for an obligation."""
    clause_id: int
    contract_id: int
    contract_name: str
    category_code: str
    category_name: str
    clause_name: str
    section_ref: Optional[str]
    metric: str
    threshold_value: Optional[float]
    comparison_operator: str
    evaluation_period: str
    responsible_party_name: Optional[str]
    beneficiary_party: Optional[str]
    ld_per_point: Optional[float]
    ld_cap_annual: Optional[float]
    ld_currency: Optional[str]
    confidence_score: Optional[float]


class DetectRelationshipsRequest(BaseModel):
    """Request body for relationship detection."""
    include_cross_contract: bool = Field(
        default=True,
        description="Whether to detect cross-contract relationships"
    )


class DetectRelationshipsResponse(BaseModel):
    """Response model for relationship detection."""
    detected_count: int
    created_count: int
    skipped_count: int
    patterns_matched: List[str]


# ==================================================
# Obligation Endpoints
# ==================================================

@router.get("/contracts/{contract_id}/obligations", response_model=List[ObligationResponse])
async def get_contract_obligations(
    contract_id: int = Path(..., description="Contract ID")
):
    """
    Get all obligations for a contract.

    Returns obligations extracted from clause table with:
    - Metric being measured (availability_percent, etc.)
    - Threshold value
    - Evaluation period
    - Responsible and beneficiary parties
    - LD parameters

    **Note:** This queries the obligation_view which only includes
    obligation-type categories (AVAILABILITY, PERFORMANCE_GUARANTEE, etc.)
    """
    try:
        repository = OntologyRepository()
        obligations = repository.get_obligations(contract_id=contract_id)

        if not obligations:
            return []

        return obligations

    except Exception as e:
        logger.error(f"Failed to get obligations for contract {contract_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get obligations: {str(e)}"
        )


@router.get("/clauses/{clause_id}/obligation", response_model=dict)
async def get_obligation_details(
    clause_id: int = Path(..., description="Clause ID")
):
    """
    Get full obligation details including all relationships.

    Returns:
    - Obligation metrics and thresholds
    - List of excuse clauses (EXCUSES relationships)
    - List of triggered clauses (TRIGGERS relationships)
    - List of governing clauses (GOVERNS relationships)
    - List of input clauses (INPUTS relationships)
    """
    try:
        repository = OntologyRepository()
        details = repository.get_obligation_details(clause_id)

        if not details:
            raise HTTPException(
                status_code=404,
                detail=f"Obligation not found for clause {clause_id}"
            )

        return details

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get obligation details for clause {clause_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get obligation details: {str(e)}"
        )


# ==================================================
# Relationship Endpoints
# ==================================================

@router.get("/clauses/{clause_id}/relationships", response_model=List[RelationshipResponse])
async def get_clause_relationships(
    clause_id: int = Path(..., description="Clause ID"),
    relationship_type: Optional[str] = Query(
        None,
        description="Filter by type: TRIGGERS, EXCUSES, GOVERNS, INPUTS"
    ),
    direction: str = Query(
        "both",
        description="Direction: source (outgoing), target (incoming), both"
    )
):
    """
    Get all relationships for a clause.

    Args:
        clause_id: Clause ID
        relationship_type: Optional filter
        direction: Which relationships to include
    """
    try:
        repository = OntologyRepository()
        relationships = repository.get_relationships_for_clause(
            clause_id,
            relationship_type=relationship_type,
            direction=direction
        )
        return relationships

    except Exception as e:
        logger.error(f"Failed to get relationships for clause {clause_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get relationships: {str(e)}"
        )


@router.get("/clauses/{clause_id}/triggers", response_model=List[RelationshipResponse])
async def get_clause_triggers(
    clause_id: int = Path(..., description="Clause ID")
):
    """
    Get consequences triggered by breach of this clause.

    Returns clauses/consequences that would be activated if this
    obligation is breached (e.g., availability breach -> LD clause).
    """
    try:
        repository = OntologyRepository()
        triggers = repository.get_triggers_for_clause(clause_id)
        return triggers

    except Exception as e:
        logger.error(f"Failed to get triggers for clause {clause_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get triggers: {str(e)}"
        )


@router.get("/clauses/{clause_id}/excuses", response_model=List[RelationshipResponse])
async def get_clause_excuses(
    clause_id: int = Path(..., description="Clause ID")
):
    """
    Get clauses/events that can excuse this obligation.

    Returns clauses that define excuse conditions for this obligation
    (e.g., force majeure -> excuses availability).
    """
    try:
        repository = OntologyRepository()
        excuses = repository.get_excuses_for_clause(clause_id)
        return excuses

    except Exception as e:
        logger.error(f"Failed to get excuses for clause {clause_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get excuses: {str(e)}"
        )


@router.post("/relationships", response_model=dict)
async def create_relationship(
    request: RelationshipCreate
):
    """
    Create an explicit relationship between clauses.

    This is for manually-defined relationships (not auto-detected).
    Relationship types:
    - TRIGGERS: Source breach triggers target consequence
    - EXCUSES: Source condition excuses target obligation
    - GOVERNS: Source sets context for target
    - INPUTS: Source provides data to target
    """
    try:
        # Validate relationship type
        valid_types = ['TRIGGERS', 'EXCUSES', 'GOVERNS', 'INPUTS']
        if request.relationship_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid relationship_type. Must be one of: {valid_types}"
            )

        repository = OntologyRepository()
        relationship_id = repository.create_relationship(
            source_clause_id=request.source_clause_id,
            target_clause_id=request.target_clause_id,
            relationship_type=request.relationship_type,
            is_cross_contract=request.is_cross_contract,
            parameters=request.parameters,
            is_inferred=False  # Explicit relationship
        )

        if not relationship_id:
            raise HTTPException(
                status_code=409,
                detail="Relationship already exists"
            )

        return {
            "success": True,
            "relationship_id": relationship_id,
            "message": f"Created {request.relationship_type} relationship"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create relationship: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create relationship: {str(e)}"
        )


@router.delete("/relationships/{relationship_id}")
async def delete_relationship(
    relationship_id: int = Path(..., description="Relationship ID")
):
    """Delete a relationship by ID."""
    try:
        repository = OntologyRepository()
        success = repository.delete_relationship(relationship_id)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Relationship {relationship_id} not found"
            )

        return {
            "success": True,
            "message": f"Deleted relationship {relationship_id}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete relationship {relationship_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete relationship: {str(e)}"
        )


# ==================================================
# Relationship Detection Endpoints
# ==================================================

@router.post(
    "/contracts/{contract_id}/detect-relationships",
    response_model=DetectRelationshipsResponse
)
async def detect_relationships(
    contract_id: int = Path(..., description="Contract ID"),
    request: Optional[DetectRelationshipsRequest] = None
):
    """
    Auto-detect relationships for a contract based on clause categories.

    Uses pattern matching from relationship_patterns.yaml to identify
    likely relationships between clauses. For example:
    - AVAILABILITY clause → TRIGGERS → LIQUIDATED_DAMAGES clause
    - FORCE_MAJEURE clause → EXCUSES → AVAILABILITY clause

    Detected relationships are stored with is_inferred=True and include
    a confidence score based on the pattern definition.

    **Note:** This will skip any relationships that already exist.
    """
    try:
        include_cross = request.include_cross_contract if request else True

        detector = RelationshipDetector()
        result = detector.detect_and_store(
            contract_id,
            include_cross_contract=include_cross
        )

        return DetectRelationshipsResponse(**result)

    except Exception as e:
        logger.error(
            f"Failed to detect relationships for contract {contract_id}: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Relationship detection failed: {str(e)}"
        )


@router.delete("/contracts/{contract_id}/inferred-relationships")
async def delete_inferred_relationships(
    contract_id: int = Path(..., description="Contract ID"),
    inferred_by: Optional[str] = Query(
        None,
        description="Filter by inference source (pattern_matcher, claude_extraction)"
    )
):
    """
    Delete all inferred relationships for a contract.

    Useful for re-running detection with updated patterns.
    Explicit (manually-created) relationships are not affected.
    """
    try:
        repository = OntologyRepository()
        deleted = repository.delete_inferred_relationships(contract_id, inferred_by)

        return {
            "success": True,
            "deleted_count": deleted,
            "message": f"Deleted {deleted} inferred relationships for contract {contract_id}"
        }

    except Exception as e:
        logger.error(
            f"Failed to delete inferred relationships for contract {contract_id}: {e}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete relationships: {str(e)}"
        )


# ==================================================
# Graph Endpoints
# ==================================================

@router.get("/contracts/{contract_id}/relationship-graph")
async def get_relationship_graph(
    contract_id: int = Path(..., description="Contract ID")
):
    """
    Get the full relationship graph for a contract.

    Returns all relationships involving clauses in this contract,
    including cross-contract relationships if any exist.

    Useful for visualizing how clauses relate to each other.
    """
    try:
        repository = OntologyRepository()
        graph = repository.get_contract_relationship_graph(contract_id)

        return {
            "contract_id": contract_id,
            "relationship_count": len(graph),
            "relationships": graph
        }

    except Exception as e:
        logger.error(
            f"Failed to get relationship graph for contract {contract_id}: {e}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get relationship graph: {str(e)}"
        )


# ==================================================
# Event Type Endpoints
# ==================================================

@router.get("/event-types")
async def get_event_types():
    """
    Get all event types.

    Event types are used to categorize operational events that may
    excuse obligations (force majeure, scheduled maintenance, etc.)
    """
    try:
        repository = OntologyRepository()
        event_types = repository.get_event_types()
        return event_types

    except Exception as e:
        logger.error(f"Failed to get event types: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get event types: {str(e)}"
        )


@router.get("/clauses/{clause_id}/excuse-events")
async def get_excuse_events(
    clause_id: int = Path(..., description="Clause ID"),
    period_start: Optional[str] = Query(
        None,
        description="Period start (ISO 8601)"
    ),
    period_end: Optional[str] = Query(
        None,
        description="Period end (ISO 8601)"
    )
):
    """
    Get events that could excuse the given clause.

    Based on EXCUSES relationships, returns actual events from the
    event table that match excuse categories (force majeure, maintenance, etc.)

    Useful for rules engine to calculate excused hours.
    """
    try:
        from datetime import datetime

        # Parse dates if provided
        start = datetime.fromisoformat(period_start) if period_start else None
        end = datetime.fromisoformat(period_end) if period_end else None

        repository = OntologyRepository()
        events = repository.get_excuse_events_for_clause(
            clause_id,
            period_start=start,
            period_end=end
        )

        return {
            "clause_id": clause_id,
            "event_count": len(events),
            "events": events
        }

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format: {e}"
        )
    except Exception as e:
        logger.error(f"Failed to get excuse events for clause {clause_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get excuse events: {str(e)}"
        )
