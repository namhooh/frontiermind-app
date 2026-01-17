"""
SMA Fetcher

Fetches meter data from SMA Sunny Portal API using OAuth 2.0 authentication.
https://developer.sma.de/
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from ..base_fetcher import BaseFetcher
from ..config import Config

logger = logging.getLogger(__name__)


class SMAFetcher(BaseFetcher):
    """Fetcher for SMA Sunny Portal API."""

    SOURCE_TYPE = "sma"

    # Rate limit: 60 requests per minute
    RATE_LIMIT_REQUESTS = 60
    RATE_LIMIT_WINDOW_SECONDS = 60

    def __init__(self, config: Config = None, dry_run: bool = False):
        super().__init__(config, dry_run)
        self.api_base = self.config.sma_api_base
        self._request_timestamps: List[float] = []

    def _rate_limit_wait(self) -> None:
        """Implement rate limiting."""
        now = time.time()
        # Remove timestamps older than the rate limit window
        self._request_timestamps = [
            ts for ts in self._request_timestamps
            if now - ts < self.RATE_LIMIT_WINDOW_SECONDS
        ]

        if len(self._request_timestamps) >= self.RATE_LIMIT_REQUESTS:
            # Wait until the oldest request falls outside the window
            sleep_time = self.RATE_LIMIT_WINDOW_SECONDS - (now - self._request_timestamps[0])
            if sleep_time > 0:
                logger.info(f"Rate limit reached, waiting {sleep_time:.1f}s")
                time.sleep(sleep_time)

        self._request_timestamps.append(time.time())

    def _get_headers(self, access_token: str) -> Dict[str, str]:
        """Get request headers with OAuth token."""
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def fetch_sites_list(self, api_key: str) -> List[Dict[str, Any]]:
        """
        Fetch list of plants available for this OAuth credential.

        Args:
            api_key: OAuth access token.

        Returns:
            List of plant info dictionaries.
        """
        self._rate_limit_wait()

        url = f"{self.api_base}/plants"
        headers = self._get_headers(api_key)

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        plants = data.get("plants", [])

        return [
            {
                "site_id": plant.get("plantId"),
                "name": plant.get("name"),
                "status": self._map_status(plant.get("status")),
                "peak_power_wp": plant.get("peakPower"),
                "installation_date": plant.get("installationDate"),
                "location": {
                    "address": plant.get("address", {}).get("street"),
                    "city": plant.get("address", {}).get("city"),
                    "country": plant.get("address", {}).get("country"),
                    "timezone": plant.get("timezone"),
                    "latitude": plant.get("address", {}).get("latitude"),
                    "longitude": plant.get("address", {}).get("longitude"),
                },
                "device_count": plant.get("deviceCount"),
            }
            for plant in plants
        ]

    def _map_status(self, sma_status: Optional[str]) -> str:
        """Map SMA status codes to standard status strings."""
        status_map = {
            "Ok": "active",
            "Warning": "warning",
            "Error": "error",
            "Unknown": "unknown",
        }
        return status_map.get(sma_status, "unknown")

    def fetch_site_data(
        self,
        api_key: str,
        site_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        """
        Fetch energy data for a single plant.

        Args:
            api_key: OAuth access token.
            site_id: SMA plant ID.
            start_time: Start of time range.
            end_time: End of time range.

        Returns:
            Data in canonical format ready for S3 upload.
        """
        # Fetch plant details
        plant_details = self._fetch_plant_details(api_key, site_id)

        # Fetch measurements
        measurements = self._fetch_measurements(api_key, site_id, start_time, end_time)

        # Fetch live data
        live_data = self._fetch_live_data(api_key, site_id)

        # Transform to canonical format
        readings = self._transform_to_canonical(measurements)

        return {
            "source": "sma",
            "site_id": site_id,
            "fetch_time": datetime.now(timezone.utc).isoformat(),
            "time_range": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
            },
            "overview": {
                "plant_name": plant_details.get("name"),
                "peak_power_wp": plant_details.get("peakPower"),
                "current_power_w": live_data.get("PvGeneration", {}).get("value"),
                "energy_today_wh": live_data.get("TotalYield", {}).get("today"),
                "energy_total_wh": live_data.get("TotalYield", {}).get("total"),
                "status": self._map_status(plant_details.get("status")),
                "last_update_time": live_data.get("timestamp"),
            },
            "readings": readings,
            "raw_measurements": measurements,
            "raw_live": live_data,
        }

    def _fetch_plant_details(self, access_token: str, plant_id: str) -> Dict[str, Any]:
        """Fetch plant details."""
        self._rate_limit_wait()

        url = f"{self.api_base}/plants/{plant_id}"
        headers = self._get_headers(access_token)

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        return response.json()

    def _fetch_measurements(
        self,
        access_token: str,
        plant_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        """
        Fetch measurement data for a plant.

        SMA API returns data in various resolutions based on time range.
        """
        self._rate_limit_wait()

        url = f"{self.api_base}/plants/{plant_id}/measurements"
        headers = self._get_headers(access_token)

        # SMA uses ISO format timestamps
        params = {
            "start": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "setType": "EnergyAndPower",  # Request both energy and power measurements
        }

        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code == 404:
            logger.warning(f"No measurements found for plant {plant_id}")
            return {"sets": []}

        response.raise_for_status()

        return response.json()

    def _fetch_live_data(self, access_token: str, plant_id: str) -> Dict[str, Any]:
        """Fetch current live data for a plant."""
        self._rate_limit_wait()

        url = f"{self.api_base}/plants/{plant_id}/liveData"
        headers = self._get_headers(access_token)

        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 404:
            return {}

        response.raise_for_status()

        return response.json()

    def _transform_to_canonical(
        self,
        measurements: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Transform SMA data to canonical format.

        Canonical format:
        {
            "timestamp": "2024-01-15T10:00:00Z",
            "energy_wh": 1500.0,
            "power_w": 6000.0,
            "interval_minutes": 15
        }
        """
        readings = []

        # Process measurement sets
        sets = measurements.get("sets", [])
        for measurement_set in sets:
            set_type = measurement_set.get("type")
            values = measurement_set.get("values", [])

            for value in values:
                timestamp = value.get("timestamp")
                if not timestamp:
                    continue

                # SMA provides energy in Wh and power in W
                if set_type == "Energy":
                    readings.append({
                        "timestamp": timestamp,
                        "energy_wh": value.get("value"),
                        "power_w": None,
                        "interval_minutes": 15,  # SMA typically uses 15-min intervals
                        "data_type": "energy",
                    })
                elif set_type == "Power":
                    # Check if we already have an entry for this timestamp
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
                elif set_type == "EnergyAndPower":
                    # Combined data
                    readings.append({
                        "timestamp": timestamp,
                        "energy_wh": value.get("energy"),
                        "power_w": value.get("power"),
                        "interval_minutes": 15,
                        "data_type": "combined",
                    })

        # Sort by timestamp
        readings.sort(key=lambda x: x.get("timestamp", ""))

        return readings

    def run(self, lookback_hours: Optional[int] = None) -> Dict[str, Any]:
        """
        Run the fetcher for all active SMA credentials.

        Overrides base run() to use OAuth token refresh.

        Args:
            lookback_hours: Hours to look back for data. Defaults to config value.

        Returns:
            Summary of fetch results.
        """
        lookback_hours = lookback_hours or self.config.default_lookback_hours
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=lookback_hours)

        results = {
            "source_type": self.SOURCE_TYPE,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "credentials_processed": 0,
            "sites_processed": 0,
            "files_uploaded": 0,
            "errors": [],
        }

        # Get credentials with OAuth token refresh
        try:
            credentials = self.get_credentials_with_refresh(
                provider="sma",
                client_id=self.config.sma_client_id,
                client_secret=self.config.sma_client_secret,
            )
        except Exception as e:
            logger.error(f"Failed to fetch credentials: {e}")
            results["errors"].append(f"Failed to fetch credentials: {e}")
            return results

        for cred in credentials:
            if not cred.get("decrypted"):
                continue

            results["credentials_processed"] += 1
            access_token = self.get_access_token(cred)

            if not access_token:
                logger.warning(f"No access token found for credential {cred['id']}")
                continue

            try:
                sites = self.get_sites_for_credential(cred["id"])

                for site in sites:
                    try:
                        results["sites_processed"] += 1
                        external_site_id = site["external_site_id"]

                        # Fetch data from SMA API
                        data = self.fetch_site_data(
                            api_key=access_token,
                            site_id=external_site_id,
                            start_time=start_time,
                            end_time=end_time,
                        )

                        # Upload to S3
                        self.upload_to_s3(
                            data=data,
                            organization_id=site["organization_id"],
                            site_id=external_site_id,
                        )
                        results["files_uploaded"] += 1

                        # Update sync status
                        records_count = len(data.get("readings", []))
                        self.update_site_sync_status(
                            site_id=site["id"],
                            status="success",
                            records_count=records_count,
                        )

                    except Exception as e:
                        error_msg = f"Error fetching site {site.get('external_site_id')}: {e}"
                        logger.error(error_msg)
                        results["errors"].append(error_msg)
                        self.update_site_sync_status(
                            site_id=site["id"],
                            status="error",
                            error=str(e),
                        )

                self.record_credential_success(cred["id"])

            except Exception as e:
                error_msg = f"Error with credential {cred['id']}: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
                self.record_credential_error(cred["id"], str(e))

        logger.info(
            f"Fetch complete: {results['files_uploaded']} files uploaded, "
            f"{len(results['errors'])} errors"
        )

        return results


def main():
    """CLI entry point for testing."""
    import argparse

    parser = argparse.ArgumentParser(description="SMA Data Fetcher")
    parser.add_argument("--dry-run", action="store_true", help="Don't upload to S3")
    parser.add_argument("--lookback", type=int, default=2, help="Hours to look back")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    fetcher = SMAFetcher(dry_run=args.dry_run)
    results = fetcher.run(lookback_hours=args.lookback)

    print(f"\nResults: {results}")


if __name__ == "__main__":
    main()
