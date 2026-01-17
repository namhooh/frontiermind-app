"""
GoodWe Fetcher

Fetches meter data from GoodWe SEMS Portal API.
https://openapi.semsportal.com
"""

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from ..base_fetcher import BaseFetcher
from ..config import Config

logger = logging.getLogger(__name__)


class GoodWeFetcher(BaseFetcher):
    """Fetcher for GoodWe SEMS Portal API."""

    SOURCE_TYPE = "goodwe"

    def __init__(self, config: Config = None, dry_run: bool = False):
        super().__init__(config, dry_run)
        self.api_base = self.config.goodwe_api_base
        self._token: Optional[str] = None
        self._uid: Optional[str] = None

    def _get_auth_token(self, account: str, password: str) -> Dict[str, str]:
        """
        Get authentication token from GoodWe API.

        Args:
            account: GoodWe account (email).
            password: GoodWe password.

        Returns:
            Dict with token and uid.
        """
        url = f"{self.api_base}/v2/Common/CrossLogin"

        # GoodWe uses MD5 hash for password
        password_hash = hashlib.md5(password.encode()).hexdigest()

        payload = {
            "account": account,
            "pwd": password_hash,
        }

        headers = {
            "Content-Type": "application/json",
            "Token": '{"version":"v2.1.0","client":"ios","language":"en"}',
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise ValueError(f"GoodWe auth failed: {data.get('msg')}")

        result = data.get("data", {})
        self._token = result.get("token")
        self._uid = result.get("uid")

        return {"token": self._token, "uid": self._uid}

    def _get_headers(self) -> Dict[str, str]:
        """Get headers with authentication token."""
        if not self._token:
            raise ValueError("Not authenticated. Call _get_auth_token first.")

        return {
            "Content-Type": "application/json",
            "Token": self._token,
        }

    def fetch_sites_list(self, api_key: str) -> List[Dict[str, Any]]:
        """
        Fetch list of power stations (sites) for this account.

        Note: GoodWe uses account/password auth, not API key.
        The api_key parameter should contain JSON with account and password.

        Args:
            api_key: JSON string with {"account": "...", "password": "..."}

        Returns:
            List of site info dictionaries.
        """
        import json

        # Parse credentials (stored as JSON in api_key field)
        creds = json.loads(api_key) if isinstance(api_key, str) else api_key
        account = creds.get("account")
        password = creds.get("password")

        # Authenticate
        self._get_auth_token(account, password)

        # Fetch power stations
        url = f"{self.api_base}/v2/PowerStation/GetPowerStationList"

        payload = {
            "page_index": 1,
            "page_size": 100,
        }

        response = requests.post(
            url, json=payload, headers=self._get_headers(), timeout=30
        )
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise ValueError(f"GoodWe API error: {data.get('msg')}")

        stations = data.get("data", {}).get("list", [])

        return [
            {
                "site_id": station.get("id"),
                "name": station.get("name"),
                "status": station.get("status"),
                "capacity_kw": station.get("capacity"),
                "location": {
                    "address": station.get("address"),
                    "city": station.get("city"),
                    "country": station.get("country"),
                    "timezone": station.get("timezone"),
                },
                "inverter_count": station.get("inverter_count"),
            }
            for station in stations
        ]

    def fetch_site_data(
        self,
        api_key: str,
        site_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        """
        Fetch energy data for a single power station.

        Args:
            api_key: JSON credentials string.
            site_id: GoodWe power station ID.
            start_time: Start of time range.
            end_time: End of time range.

        Returns:
            Data in canonical format ready for S3 upload.
        """
        import json

        # Parse credentials and authenticate if needed
        if not self._token:
            creds = json.loads(api_key) if isinstance(api_key, str) else api_key
            self._get_auth_token(creds["account"], creds["password"])

        # Fetch real-time data
        realtime_data = self._fetch_realtime_data(site_id)

        # Fetch historical data for the time range
        historical_data = self._fetch_historical_data(site_id, start_time, end_time)

        # Transform to canonical format
        readings = self._transform_to_canonical(historical_data)

        return {
            "source": "goodwe",
            "site_id": site_id,
            "fetch_time": datetime.utcnow().isoformat(),
            "time_range": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
            },
            "overview": realtime_data,
            "readings": readings,
            "raw_historical": historical_data,
        }

    def _fetch_realtime_data(self, site_id: str) -> Dict[str, Any]:
        """Fetch real-time power station data."""
        url = f"{self.api_base}/v2/PowerStation/GetPowerStationDetail"

        payload = {"id": site_id}

        response = requests.post(
            url, json=payload, headers=self._get_headers(), timeout=30
        )
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise ValueError(f"GoodWe API error: {data.get('msg')}")

        detail = data.get("data", {})

        return {
            "current_power_w": detail.get("pac", 0) * 1000,  # kW to W
            "today_energy_kwh": detail.get("eday", 0),
            "total_energy_kwh": detail.get("etotal", 0),
            "status": detail.get("status"),
            "last_update_time": detail.get("updatetime"),
        }

    def _fetch_historical_data(
        self,
        site_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        """Fetch historical energy data."""
        url = f"{self.api_base}/v2/PowerStation/GetPowerStationPac"

        all_data = []
        current_date = start_time.date()

        while current_date <= end_time.date():
            payload = {
                "id": site_id,
                "date": current_date.strftime("%Y-%m-%d"),
            }

            response = requests.post(
                url, json=payload, headers=self._get_headers(), timeout=30
            )
            response.raise_for_status()

            data = response.json()
            if data.get("code") == 0:
                pac_data = data.get("data", {}).get("pac", [])
                for point in pac_data:
                    all_data.append({
                        "date": current_date.strftime("%Y-%m-%d"),
                        "time": point.get("time"),
                        "power_kw": point.get("pac", 0),
                    })

            current_date = current_date.replace(day=current_date.day + 1)

        return all_data

    def _transform_to_canonical(
        self,
        historical_data: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Transform GoodWe data to canonical format.

        Canonical format:
        {
            "timestamp": "2024-01-15T10:00:00Z",
            "energy_wh": 1500.0,
            "power_w": 6000.0,
            "interval_minutes": 5
        }
        """
        readings = []

        for point in historical_data:
            timestamp = f"{point['date']}T{point['time']}:00"
            power_w = point.get("power_kw", 0) * 1000  # kW to W

            readings.append({
                "timestamp": timestamp,
                "energy_wh": None,  # GoodWe provides power, not energy per interval
                "power_w": power_w,
                "interval_minutes": 5,  # GoodWe typically reports 5-min intervals
                "data_type": "power",
            })

        # Sort by timestamp
        readings.sort(key=lambda x: x.get("timestamp", ""))

        return readings


def main():
    """CLI entry point for testing."""
    import argparse

    parser = argparse.ArgumentParser(description="GoodWe Data Fetcher")
    parser.add_argument("--dry-run", action="store_true", help="Don't upload to S3")
    parser.add_argument("--lookback", type=int, default=2, help="Hours to look back")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    fetcher = GoodWeFetcher(dry_run=args.dry_run)
    results = fetcher.run(lookback_hours=args.lookback)

    print(f"\nResults: {results}")


if __name__ == "__main__":
    main()
