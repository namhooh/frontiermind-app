"""
Billing Resolver — FK resolution for billing aggregate ingestion.

Resolves:
  - tariff_group_key → clause_tariff_id
  - bill_date → billing_period_id
  - tariff_group_key → contract_line_id + meter_id (via external_line_id)

Strategy: Quarantine + fail visibly.
Rows with unresolved FKs are separated into an unresolved list with diagnostic
info. Only fully resolved rows proceed to meter_aggregate; unresolved rows go
to meter_aggregate_staging for manual reconciliation.
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from db.database import get_db_connection

logger = logging.getLogger(__name__)

# Required FKs that must be non-NULL for a row to be considered resolved.
# meter_id is optional — contract_line already identifies the project/product.
# meter_id is populated opportunistically when contract_line has one linked.
REQUIRED_FKS = {'billing_period_id', 'contract_line_id'}


class BillingResolver:
    """Resolves billing aggregate foreign keys in bulk."""

    def resolve_tariff(
        self,
        tariff_group_key: str,
        organization_id: int,
        bill_date: Optional[date] = None,
    ) -> Optional[int]:
        """Resolve a tariff_group_key to clause_tariff_id.

        When bill_date is provided, picks the tariff row whose valid_from/valid_to
        window contains that date. Falls back to latest active row if no validity
        window matches or if dates are NULL.

        Returns None + logs warning if unresolved.
        """
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if bill_date:
                    # Try validity-window match first
                    cur.execute(
                        """
                        SELECT id FROM clause_tariff
                        WHERE tariff_group_key = %s
                          AND organization_id = %s
                          AND is_active = true
                          AND (valid_from IS NULL OR valid_from <= %s)
                          AND (valid_to IS NULL OR valid_to >= %s)
                        ORDER BY valid_from DESC NULLS LAST, id DESC
                        LIMIT 1
                        """,
                        (tariff_group_key, organization_id, bill_date, bill_date),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id FROM clause_tariff
                        WHERE tariff_group_key = %s
                          AND organization_id = %s
                          AND is_active = true
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (tariff_group_key, organization_id),
                    )
                row = cur.fetchone()
                if row:
                    return row['id']
        logger.warning(
            "Unresolved tariff_group_key=%s for org=%d (bill_date=%s)",
            tariff_group_key, organization_id, bill_date,
        )
        return None

    def resolve_billing_period(self, bill_date: date) -> Optional[int]:
        """Resolve a bill_date to billing_period_id.

        Matches billing_period where end_date = bill_date.
        Returns None + logs warning if no match.
        """
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM billing_period
                    WHERE end_date = %s::date
                    LIMIT 1
                    """,
                    (str(bill_date),),
                )
                row = cur.fetchone()
                if row:
                    return row['id']
        logger.warning("Unresolved billing_period for bill_date=%s", bill_date)
        return None

    def resolve_batch(
        self,
        records: List[Dict[str, Any]],
        organization_id: int,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Bulk resolve FKs for a batch of canonical billing records.

        Returns:
            Tuple of (resolved, unresolved) record lists.
            Resolved records have all required FKs populated.
            Unresolved records include '_unresolved_fks' diagnostic info.
        """
        # Collect unique (tariff_group_key, bill_date) pairs for date-aware resolution
        # Normalize date strings: CBE sends '2025/01/31', resolver needs '2025-01-31'
        tariff_date_pairs: set = set()
        for r in records:
            tgk = r.get("tariff_group_key")
            bd = r.get("bill_date")
            if tgk:
                bd_norm = str(bd).replace('/', '-') if bd else None
                tariff_date_pairs.add((tgk, bd_norm))

        bill_dates = {
            r["bill_date"]
            for r in records
            if r.get("bill_date")
        }

        # Bulk resolve tariffs with date-aware validity filtering
        tariff_map: Dict[Tuple[str, Optional[str]], int] = {}
        if tariff_date_pairs:
            tariff_map = self._bulk_resolve_tariffs(
                tariff_date_pairs, organization_id
            )

        # Bulk resolve billing periods
        period_map: Dict[str, int] = {}
        if bill_dates:
            period_map = self._bulk_resolve_periods(list(bill_dates))

        # Bulk resolve contract lines (external_line_id = tariff_group_key)
        external_line_ids = {
            r["tariff_group_key"]
            for r in records
            if r.get("tariff_group_key")
        }
        contract_line_map: Dict[str, dict] = {}
        if external_line_ids:
            contract_line_map = self._bulk_resolve_contract_lines(
                list(external_line_ids), organization_id
            )

        # Apply to records and separate resolved/unresolved
        resolved: List[Dict[str, Any]] = []
        unresolved: List[Dict[str, Any]] = []
        tariff_resolved = 0
        period_resolved = 0
        line_resolved = 0

        for record in records:
            tgk = record.get("tariff_group_key")
            bd = record.get("bill_date")
            bd_norm = str(bd).replace('/', '-') if bd else None
            lookup_key = (tgk, bd_norm) if tgk else None
            unresolved_fks: List[str] = []

            if lookup_key and lookup_key in tariff_map:
                record["clause_tariff_id"] = tariff_map[lookup_key]
                tariff_resolved += 1
            else:
                record["clause_tariff_id"] = None

            bd_normalized = str(bd).replace('/', '-') if bd else None
            if bd_normalized and bd_normalized in period_map:
                record["billing_period_id"] = period_map[bd_normalized]
                period_resolved += 1
            else:
                record["billing_period_id"] = None
                unresolved_fks.append(f"billing_period_id (bill_date={bd})")

            # Resolve contract_line_id and meter_id from external_line_id
            if tgk and tgk in contract_line_map:
                cl = contract_line_map[tgk]
                record["contract_line_id"] = cl["id"]
                # Populate meter_id from contract_line if not already set
                if record.get("meter_id") is None and cl.get("meter_id"):
                    record["meter_id"] = cl["meter_id"]
                line_resolved += 1
            else:
                if record.get("contract_line_id") is None:
                    record["contract_line_id"] = None
                    unresolved_fks.append(f"contract_line_id (external_line_id={tgk})")

            # Check meter_id
            if record.get("meter_id") is None:
                unresolved_fks.append(f"meter_id (tariff_group_key={tgk})")

            # Classify: all required FKs must be non-NULL
            missing = [fk for fk in REQUIRED_FKS if record.get(fk) is None]
            if missing:
                record["_unresolved_fks"] = unresolved_fks or [f"missing: {', '.join(missing)}"]
                unresolved.append(record)
            else:
                resolved.append(record)

        total = len(records)
        logger.info(
            "FK resolution: tariffs %d/%d, billing periods %d/%d, contract lines %d/%d | resolved %d, unresolved %d",
            tariff_resolved, total, period_resolved, total, line_resolved, total,
            len(resolved), len(unresolved),
        )

        return resolved, unresolved

    def _bulk_resolve_tariffs(
        self,
        tariff_date_pairs: set,
        organization_id: int,
    ) -> Dict[Tuple[str, Optional[str]], int]:
        """Resolve (tariff_group_key, bill_date) pairs to clause_tariff IDs.

        For each unique tariff_group_key, fetches all active rows with their
        validity windows, then matches per bill_date. Falls back to latest row
        when no validity window matches or dates are NULL.
        """
        unique_keys = list({pair[0] for pair in tariff_date_pairs})
        if not unique_keys:
            return {}

        # Fetch all active tariff rows for these keys
        rows_by_key: Dict[str, List[dict]] = {}
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT tariff_group_key, id, valid_from, valid_to
                    FROM clause_tariff
                    WHERE tariff_group_key = ANY(%s)
                      AND organization_id = %s
                      AND is_active = true
                    ORDER BY tariff_group_key, valid_from DESC NULLS LAST, id DESC
                    """,
                    (unique_keys, organization_id),
                )
                for row in cur.fetchall():
                    key = row['tariff_group_key']
                    if key not in rows_by_key:
                        rows_by_key[key] = []
                    rows_by_key[key].append({
                        "id": row['id'],
                        "valid_from": row['valid_from'],
                        "valid_to": row['valid_to'],
                    })

        # Match each (tariff_group_key, bill_date) pair
        result: Dict[Tuple[str, Optional[str]], int] = {}
        unresolved_keys = set()
        for tgk, bd_str in tariff_date_pairs:
            candidates = rows_by_key.get(tgk, [])
            if not candidates:
                unresolved_keys.add(tgk)
                continue

            # Try date-aware match
            matched_id = None
            if bd_str:
                try:
                    bd = date.fromisoformat(bd_str)
                    for c in candidates:
                        vf = c["valid_from"]
                        vt = c["valid_to"]
                        if (vf is None or vf <= bd) and (vt is None or vt >= bd):
                            matched_id = c["id"]
                            break
                except ValueError:
                    pass

            # Fall back to latest row (first in our DESC-sorted list)
            if matched_id is None:
                matched_id = candidates[0]["id"]

            result[(tgk, bd_str)] = matched_id

        if unresolved_keys:
            logger.warning(
                "Unresolved tariff_group_keys (%d): %s",
                len(unresolved_keys),
                list(unresolved_keys)[:5],
            )
        return result

    def _bulk_resolve_contract_lines(
        self,
        external_line_ids: List[str],
        organization_id: int,
    ) -> Dict[str, dict]:
        """Resolve external_line_ids to contract_line rows.

        CBE CONTRACT_LINE_UNIQUE_ID is stored as external_line_id on contract_line
        and as tariff_group_key on clause_tariff — same value is used for both lookups.

        Two-pass resolution:
        1. Direct match: external_line_id on contract_line (1-to-1)
        2. Parent-child fallback: For mother lines (meter_id IS NULL), query
           children via parent_contract_line_id to find a child with a valid meter.

        Returns dict mapping external_line_id → {id, meter_id, energy_category}.
        """
        result: Dict[str, dict] = {}
        if not external_line_ids:
            return result

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Pass 1: Direct external_line_id match
                cur.execute(
                    """
                    SELECT external_line_id, id, meter_id, energy_category::text
                    FROM contract_line
                    WHERE external_line_id = ANY(%s)
                      AND organization_id = %s
                      AND is_active = true
                    """,
                    (external_line_ids, organization_id),
                )
                for row in cur.fetchall():
                    result[row['external_line_id']] = {
                        "id": row['id'],
                        "meter_id": row['meter_id'],
                        "energy_category": row['energy_category'],
                    }

                # Pass 2: For mother lines (meter_id IS NULL), resolve via
                # first active child with a meter
                mother_ids = {
                    ext_id: info
                    for ext_id, info in result.items()
                    if info.get("meter_id") is None
                }
                if mother_ids:
                    mother_db_ids = [info["id"] for info in mother_ids.values()]
                    cur.execute(
                        """
                        SELECT DISTINCT ON (cl.parent_contract_line_id)
                            cl.parent_contract_line_id,
                            cl.id, cl.meter_id, cl.energy_category::text
                        FROM contract_line cl
                        WHERE cl.parent_contract_line_id = ANY(%s)
                          AND cl.is_active = true
                          AND cl.meter_id IS NOT NULL
                        ORDER BY cl.parent_contract_line_id, cl.id
                        """,
                        (mother_db_ids,),
                    )
                    # Build reverse map: mother DB id → external_line_id
                    mother_db_to_ext = {
                        info["id"]: ext_id for ext_id, info in mother_ids.items()
                    }
                    for row in cur.fetchall():
                        parent_id = row['parent_contract_line_id']
                        ext_id = mother_db_to_ext.get(parent_id)
                        if ext_id:
                            result[ext_id] = {
                                "id": row['id'],
                                "meter_id": row['meter_id'],
                                "energy_category": row['energy_category'],
                            }
                    resolved_mothers = sum(
                        1 for ext_id in mother_ids
                        if result.get(ext_id, {}).get("meter_id") is not None
                    )
                    if resolved_mothers:
                        logger.info(
                            "Resolved %d mother line(s) via parent-child fallback",
                            resolved_mothers,
                        )
                    unresolved_mothers = [
                        ext_id for ext_id in mother_ids
                        if result.get(ext_id, {}).get("meter_id") is None
                    ]
                    if unresolved_mothers:
                        logger.warning(
                            "Mother line(s) with meter_id=NULL had no children: %s",
                            unresolved_mothers[:5],
                        )

        unresolved = set(external_line_ids) - set(result.keys())
        if unresolved:
            logger.warning(
                "Unresolved contract_line external_line_ids (%d): %s",
                len(unresolved),
                list(unresolved)[:5],
            )
        return result

    def _bulk_resolve_periods(
        self,
        bill_dates: List[Any],
    ) -> Dict[str, int]:
        """Single query to resolve all bill_dates to billing_period_ids."""
        result: Dict[str, int] = {}
        # Normalize date strings: CBE sends '2025/01/31', DB stores '2025-01-31'
        date_strings = [str(d).replace('/', '-') for d in bill_dates]
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT end_date::text, id
                    FROM billing_period
                    WHERE end_date::text = ANY(%s)
                    """,
                    (date_strings,),
                )
                for row in cur.fetchall():
                    result[row['end_date']] = row['id']

        unresolved = set(date_strings) - set(result.keys())
        if unresolved:
            logger.warning(
                "Unresolved billing periods (%d): %s",
                len(unresolved),
                list(unresolved)[:5],
            )
        return result
