"""
Billing Resolver — FK resolution for billing aggregate ingestion.

Resolves tariff_group_key → clause_tariff_id and bill_date → billing_period_id.

Strategy: Load with NULLs + warn.
Unresolved FKs are set to NULL and a warning is logged.
Rows load successfully regardless and can be reconciled later.
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from db.database import get_db_connection

logger = logging.getLogger(__name__)


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
                    return row[0]
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
                    return row[0]
        logger.warning("Unresolved billing_period for bill_date=%s", bill_date)
        return None

    def resolve_batch(
        self,
        records: List[Dict[str, Any]],
        organization_id: int,
    ) -> List[Dict[str, Any]]:
        """Bulk resolve FKs for a batch of canonical billing records.

        Collects unique (tariff_group_key, bill_date) pairs and bill_dates,
        runs bulk queries, then populates resolved IDs on each record.
        NULLs where unresolved.

        Records are expected to have 'tariff_group_key' and 'bill_date' fields.
        Tariff resolution uses valid_from/valid_to date filtering when bill_date
        is available.
        """
        # Collect unique (tariff_group_key, bill_date) pairs for date-aware resolution
        tariff_date_pairs: set = set()
        for r in records:
            tgk = r.get("tariff_group_key")
            bd = r.get("bill_date")
            if tgk:
                tariff_date_pairs.add((tgk, str(bd) if bd else None))

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

        # Apply to records
        tariff_resolved = 0
        period_resolved = 0
        for record in records:
            tgk = record.get("tariff_group_key")
            bd = record.get("bill_date")
            lookup_key = (tgk, str(bd) if bd else None) if tgk else None
            if lookup_key and lookup_key in tariff_map:
                record["clause_tariff_id"] = tariff_map[lookup_key]
                tariff_resolved += 1
            else:
                record["clause_tariff_id"] = None

            if bd and str(bd) in period_map:
                record["billing_period_id"] = period_map[str(bd)]
                period_resolved += 1
            else:
                record["billing_period_id"] = None

        total = len(records)
        logger.info(
            "FK resolution: tariffs %d/%d, billing periods %d/%d",
            tariff_resolved, total, period_resolved, total,
        )

        return records

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
                    key = row[0]
                    if key not in rows_by_key:
                        rows_by_key[key] = []
                    rows_by_key[key].append({
                        "id": row[1],
                        "valid_from": row[2],
                        "valid_to": row[3],
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

    def _bulk_resolve_periods(
        self,
        bill_dates: List[Any],
    ) -> Dict[str, int]:
        """Single query to resolve all bill_dates to billing_period_ids."""
        result: Dict[str, int] = {}
        date_strings = [str(d) for d in bill_dates]
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
                    result[row[0]] = row[1]

        unresolved = set(date_strings) - set(result.keys())
        if unresolved:
            logger.warning(
                "Unresolved billing periods (%d): %s",
                len(unresolved),
                list(unresolved)[:5],
            )
        return result
