"""
Price Index ingestion service.

Orchestrates fetching from BLS API and upserting into the price_index table.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from db.database import get_db_connection
from services.price_index.bls_client import BLSClient, BLSAPIError

logger = logging.getLogger(__name__)


class PriceIndexService:

    def __init__(self):
        self._bls_client = BLSClient()

    def fetch_and_upsert(
        self,
        organization_id: int,
        series_ids: Optional[List[str]] = None,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Fetch price index data from BLS and upsert into the database.

        Returns:
            dict with keys: success, series_fetched, inserted, updated, errors
        """
        if series_ids is None:
            series_ids = [BLSClient.DEFAULT_SERIES]

        errors: List[Dict[str, Any]] = []
        all_records: List[Dict[str, Any]] = []

        try:
            records = self._bls_client.fetch_series(
                series_ids=series_ids,
                start_year=start_year,
                end_year=end_year,
            )
            all_records.extend(records)
        except BLSAPIError as e:
            logger.error(f"BLS API error: {e}")
            errors.append({"source": "bls_api", "error": str(e)})
            return {
                "success": False,
                "series_fetched": [],
                "inserted": 0,
                "updated": 0,
                "errors": errors,
            }

        if not all_records:
            return {
                "success": True,
                "series_fetched": series_ids,
                "inserted": 0,
                "updated": 0,
                "errors": None,
            }

        inserted = 0
        updated = 0

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                for record in all_records:
                    try:
                        cursor.execute(
                            """
                            INSERT INTO price_index
                                (organization_id, index_code, index_name,
                                 reference_date, index_value, source, source_metadata)
                            VALUES (%s, %s, %s, %s, %s, 'bls.gov', %s)
                            ON CONFLICT (organization_id, index_code, reference_date)
                            DO UPDATE SET
                                index_value = EXCLUDED.index_value,
                                index_name = EXCLUDED.index_name,
                                source = EXCLUDED.source,
                                source_metadata = EXCLUDED.source_metadata
                            RETURNING (xmax = 0) AS is_insert
                            """,
                            (
                                organization_id,
                                record["series_id"],
                                record["index_name"],
                                record["reference_date"],
                                float(record["index_value"]),
                                json.dumps(record["source_metadata"]),
                            ),
                        )
                        row = cursor.fetchone()
                        if row and row.get("is_insert", row.get(0)):
                            inserted += 1
                        else:
                            updated += 1
                    except Exception as e:
                        logger.warning(
                            f"Failed to upsert price_index record "
                            f"{record['series_id']} {record['reference_date']}: {e}"
                        )
                        errors.append({
                            "series_id": record["series_id"],
                            "reference_date": str(record["reference_date"]),
                            "error": str(e),
                        })

                conn.commit()

        logger.info(
            f"Price index upsert complete: "
            f"{inserted} inserted, {updated} updated, {len(errors)} errors"
        )

        return {
            "success": len(errors) == 0,
            "series_fetched": list(set(r["series_id"] for r in all_records)),
            "inserted": inserted,
            "updated": updated,
            "errors": errors if errors else None,
        }
