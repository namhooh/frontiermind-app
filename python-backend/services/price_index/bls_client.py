"""
BLS (Bureau of Labor Statistics) API v1 client.

Fetches Consumer Price Index and other time series data from the
BLS Public Data API. Uses API v1 (no registration key required).

Limits (v1): 25 queries/day, 10 years per query, 25 series per query.
"""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class BLSAPIError(Exception):
    """Raised when the BLS API returns an error or unexpected response."""
    pass


class BLSClient:
    BLS_API_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
    DEFAULT_SERIES = "CUUR0000SA0"  # CPI-U All Items, US City Average, NSA

    # Map BLS series IDs to human-readable names
    SERIES_NAMES = {
        "CUUR0000SA0": "US CPI-U All Items",
    }

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout

    def fetch_series(
        self,
        series_ids: Optional[List[str]] = None,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch time series data from BLS API v1.

        Args:
            series_ids: BLS series IDs to fetch (default: [CUUR0000SA0])
            start_year: Start year (default: current_year - 5)
            end_year: End year (default: current_year)

        Returns:
            List of dicts with keys: series_id, reference_date, index_value,
            index_name, source_metadata
        """
        if series_ids is None:
            series_ids = [self.DEFAULT_SERIES]

        current_year = date.today().year
        if start_year is None:
            start_year = current_year - 5
        if end_year is None:
            end_year = current_year

        # BLS v1 limits to 10 years per query
        if end_year - start_year > 9:
            logger.warning(
                f"BLS v1 API limited to 10-year range. Clamping start_year "
                f"from {start_year} to {end_year - 9}"
            )
            start_year = end_year - 9

        payload = {
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year),
        }

        logger.info(
            f"Fetching BLS data: series={series_ids}, "
            f"years={start_year}-{end_year}"
        )

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                self.BLS_API_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code != 200:
            raise BLSAPIError(
                f"BLS API returned HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        data = response.json()

        if data.get("status") != "REQUEST_SUCCEEDED":
            messages = data.get("message", [])
            raise BLSAPIError(
                f"BLS API request failed. Status: {data.get('status')}. "
                f"Messages: {messages}"
            )

        results = []
        for series in data.get("Results", {}).get("series", []):
            series_id = series.get("seriesID", "")
            index_name = self.SERIES_NAMES.get(series_id, series_id)

            for item in series.get("data", []):
                period = item.get("period", "")

                # Skip M13 (annual average) and any non-monthly periods
                if not period.startswith("M") or period == "M13":
                    continue

                try:
                    month = int(period[1:])
                    year = int(item["year"])
                    reference_date = date(year, month, 1)
                except (ValueError, KeyError) as e:
                    logger.warning(
                        f"Skipping invalid BLS data point: {item}, error: {e}"
                    )
                    continue

                try:
                    index_value = Decimal(item["value"])
                except (InvalidOperation, KeyError) as e:
                    logger.warning(
                        f"Skipping invalid value for {series_id} "
                        f"{reference_date}: {e}"
                    )
                    continue

                results.append({
                    "series_id": series_id,
                    "reference_date": reference_date,
                    "index_value": index_value,
                    "index_name": index_name,
                    "source_metadata": {
                        "year": item.get("year"),
                        "period": period,
                        "footnotes": item.get("footnotes", []),
                    },
                })

        logger.info(f"Fetched {len(results)} data points from BLS API")
        return results
