"""
SolarEdge Fetcher

Fetches meter data from SolarEdge Monitoring API.
https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf
"""

import logging
from datetime import datetime
from typing import Any, Dict, List

import requests

from ..base_fetcher import BaseFetcher
from ..config import Config

logger = logging.getLogger(__name__)


class SolarEdgeFetcher(BaseFetcher):
    """Fetcher for SolarEdge Monitoring API."""

    SOURCE_TYPE = "solaredge"

    def __init__(self, config: Config = None, dry_run: bool = False):
        super().__init__(config, dry_run)
        self.api_base = self.config.solaredge_api_base

    def fetch_sites_list(self, api_key: str) -> List[Dict[str, Any]]:
        """
        Fetch list of sites available for this API key.

        Args:
            api_key: SolarEdge API key.

        Returns:
            List of site info dictionaries.
        """
        url = f"{self.api_base}/sites/list"
        params = {"api_key": api_key}

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        sites = data.get("sites", {}).get("site", [])

        return [
            {
                "site_id": str(site["id"]),
                "name": site.get("name"),
                "status": site.get("status"),
                "peak_power": site.get("peakPower"),
                "installation_date": site.get("installationDate"),
                "location": {
                    "address": site.get("location", {}).get("address"),
                    "city": site.get("location", {}).get("city"),
                    "country": site.get("location", {}).get("country"),
                    "timezone": site.get("location", {}).get("timeZone"),
                },
            }
            for site in sites
        ]

    def fetch_site_data(
        self,
        api_key: str,
        site_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        """
        Fetch energy data for a single site.

        Args:
            api_key: SolarEdge API key.
            site_id: SolarEdge site ID.
            start_time: Start of time range.
            end_time: End of time range.

        Returns:
            Data in canonical format ready for S3 upload.
        """
        # Fetch energy details (15-minute intervals)
        energy_data = self._fetch_energy_details(api_key, site_id, start_time, end_time)

        # Fetch power data (real-time)
        power_data = self._fetch_power_details(api_key, site_id, start_time, end_time)

        # Fetch site overview
        overview = self._fetch_site_overview(api_key, site_id)

        # Transform to canonical format
        readings = self._transform_to_canonical(energy_data, power_data)

        return {
            "source": "solaredge",
            "site_id": site_id,
            "fetch_time": datetime.utcnow().isoformat(),
            "time_range": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
            },
            "overview": overview,
            "readings": readings,
            "raw_energy": energy_data,
            "raw_power": power_data,
        }

    def _fetch_energy_details(
        self,
        api_key: str,
        site_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        """Fetch energy production details (15-min intervals)."""
        url = f"{self.api_base}/site/{site_id}/energy"
        params = {
            "api_key": api_key,
            "timeUnit": "QUARTER_OF_AN_HOUR",
            "startDate": start_time.strftime("%Y-%m-%d"),
            "endDate": end_time.strftime("%Y-%m-%d"),
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        return response.json().get("energy", {})

    def _fetch_power_details(
        self,
        api_key: str,
        site_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        """Fetch power production details (high resolution)."""
        url = f"{self.api_base}/site/{site_id}/power"
        params = {
            "api_key": api_key,
            "startTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "endTime": end_time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        return response.json().get("power", {})

    def _fetch_site_overview(self, api_key: str, site_id: str) -> Dict[str, Any]:
        """Fetch site overview with current status."""
        url = f"{self.api_base}/site/{site_id}/overview"
        params = {"api_key": api_key}

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        overview = response.json().get("overview", {})

        return {
            "last_update_time": overview.get("lastUpdateTime"),
            "lifetime_energy_wh": overview.get("lifeTimeData", {}).get("energy"),
            "last_year_energy_wh": overview.get("lastYearData", {}).get("energy"),
            "last_month_energy_wh": overview.get("lastMonthData", {}).get("energy"),
            "last_day_energy_wh": overview.get("lastDayData", {}).get("energy"),
            "current_power_w": overview.get("currentPower", {}).get("power"),
        }

    def _transform_to_canonical(
        self,
        energy_data: Dict[str, Any],
        power_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Transform SolarEdge data to canonical format.

        Canonical format:
        {
            "timestamp": "2024-01-15T10:00:00Z",
            "energy_wh": 1500.0,
            "power_w": 6000.0,
            "interval_minutes": 15
        }
        """
        readings = []

        # Process energy data (preferred - more accurate)
        energy_values = energy_data.get("values", [])
        for value in energy_values:
            if value.get("value") is not None:
                readings.append({
                    "timestamp": value.get("date"),
                    "energy_wh": value.get("value"),
                    "power_w": None,
                    "interval_minutes": 15,
                    "data_type": "energy",
                })

        # Process power data (for real-time monitoring)
        power_values = power_data.get("values", [])
        for value in power_values:
            if value.get("value") is not None:
                # Find matching energy reading or create new
                timestamp = value.get("date")
                existing = next(
                    (r for r in readings if r["timestamp"] == timestamp),
                    None,
                )
                if existing:
                    existing["power_w"] = value.get("value")
                else:
                    readings.append({
                        "timestamp": timestamp,
                        "energy_wh": None,
                        "power_w": value.get("value"),
                        "interval_minutes": None,
                        "data_type": "power",
                    })

        # Sort by timestamp
        readings.sort(key=lambda x: x.get("timestamp", ""))

        return readings


def main():
    """CLI entry point for testing."""
    import argparse

    parser = argparse.ArgumentParser(description="SolarEdge Data Fetcher")
    parser.add_argument("--dry-run", action="store_true", help="Don't upload to S3")
    parser.add_argument("--lookback", type=int, default=2, help="Hours to look back")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    fetcher = SolarEdgeFetcher(dry_run=args.dry_run)
    results = fetcher.run(lookback_hours=args.lookback)

    print(f"\nResults: {results}")


if __name__ == "__main__":
    main()
