"""
Enphase Fetcher

Fetches meter data from Enphase API v4 using OAuth 2.0 authentication.
https://developer-v4.enphase.com/
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from ..base_fetcher import BaseFetcher
from ..config import Config

logger = logging.getLogger(__name__)


class EnphaseFetcher(BaseFetcher):
    """Fetcher for Enphase API v4."""

    SOURCE_TYPE = "enphase"

    # Rate limit: 10 requests per minute per user
    RATE_LIMIT_REQUESTS = 10
    RATE_LIMIT_WINDOW_SECONDS = 60

    def __init__(self, config: Config = None, dry_run: bool = False):
        super().__init__(config, dry_run)
        self.api_base = self.config.enphase_api_base
        self._request_timestamps: List[float] = []

    def _rate_limit_wait(self) -> None:
        """Implement rate limiting (10 requests/minute)."""
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
        }

    def fetch_sites_list(self, api_key: str) -> List[Dict[str, Any]]:
        """
        Fetch list of systems available for this OAuth credential.

        Args:
            api_key: OAuth access token.

        Returns:
            List of system info dictionaries.
        """
        self._rate_limit_wait()

        url = f"{self.api_base}/systems"
        headers = self._get_headers(api_key)

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        systems = data.get("systems", [])

        return [
            {
                "site_id": str(system["system_id"]),
                "name": system.get("name"),
                "status": system.get("status"),
                "system_size_w": system.get("system_size"),
                "installation_date": system.get("operational_at"),
                "location": {
                    "address": system.get("address", {}).get("address"),
                    "city": system.get("address", {}).get("city"),
                    "country": system.get("address", {}).get("country"),
                    "timezone": system.get("timezone"),
                },
                "connection_type": system.get("connection_type"),
            }
            for system in systems
        ]

    def fetch_site_data(
        self,
        api_key: str,
        site_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        """
        Fetch energy data for a single system.

        Args:
            api_key: OAuth access token.
            site_id: Enphase system ID.
            start_time: Start of time range.
            end_time: End of time range.

        Returns:
            Data in canonical format ready for S3 upload.
        """
        # Fetch system summary
        summary = self._fetch_system_summary(api_key, site_id)

        # Fetch production telemetry
        production_data = self._fetch_production_telemetry(
            api_key, site_id, start_time, end_time
        )

        # Fetch energy lifetime data
        energy_data = self._fetch_energy_lifetime(api_key, site_id)

        # Transform to canonical format
        readings = self._transform_to_canonical(production_data)

        return {
            "source": "enphase",
            "site_id": site_id,
            "fetch_time": datetime.now(timezone.utc).isoformat(),
            "time_range": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
            },
            "overview": {
                "last_report_at": summary.get("last_report_at"),
                "system_size_w": summary.get("size_w"),
                "current_power_w": summary.get("current_power", {}).get("power"),
                "energy_today_wh": summary.get("energy_today"),
                "energy_lifetime_wh": energy_data.get("production", [{}])[-1].get("production") if energy_data.get("production") else None,
                "status": summary.get("status"),
            },
            "readings": readings,
            "raw_production": production_data,
            "raw_summary": summary,
        }

    def _fetch_system_summary(self, access_token: str, system_id: str) -> Dict[str, Any]:
        """Fetch system summary with current status."""
        self._rate_limit_wait()

        url = f"{self.api_base}/systems/{system_id}/summary"
        headers = self._get_headers(access_token)

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        return response.json()

    def _fetch_production_telemetry(
        self,
        access_token: str,
        system_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        """
        Fetch production telemetry data (5-minute intervals).

        Note: Enphase API uses Unix timestamps.
        """
        self._rate_limit_wait()

        url = f"{self.api_base}/systems/{system_id}/telemetry/production_micro"
        headers = self._get_headers(access_token)

        # Convert to Unix timestamps
        start_at = int(start_time.timestamp())
        end_at = int(end_time.timestamp())

        params = {
            "start_at": start_at,
            "granularity": "day",  # Options: day, week, month, lifetime
        }

        response = requests.get(url, headers=headers, params=params, timeout=30)

        # Handle case where no data is available
        if response.status_code == 404:
            logger.warning(f"No production data for system {system_id}")
            return {"intervals": []}

        response.raise_for_status()

        return response.json()

    def _fetch_energy_lifetime(self, access_token: str, system_id: str) -> Dict[str, Any]:
        """Fetch lifetime energy production data."""
        self._rate_limit_wait()

        url = f"{self.api_base}/systems/{system_id}/energy_lifetime"
        headers = self._get_headers(access_token)

        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 404:
            return {"production": []}

        response.raise_for_status()

        return response.json()

    def _transform_to_canonical(
        self,
        production_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Transform Enphase data to canonical format.

        Canonical format:
        {
            "timestamp": "2024-01-15T10:00:00Z",
            "energy_wh": 1500.0,
            "power_w": 6000.0,
            "interval_minutes": 5
        }
        """
        readings = []

        # Process telemetry intervals
        intervals = production_data.get("intervals", [])
        for interval in intervals:
            end_at = interval.get("end_at")
            if end_at:
                # Convert Unix timestamp to ISO format
                timestamp = datetime.fromtimestamp(end_at, tz=timezone.utc).isoformat()

                # Enphase provides energy in Wh per interval
                energy_wh = interval.get("enwh", 0)

                # Calculate average power from energy and interval
                # Default 5-minute intervals
                interval_minutes = 5
                power_w = (energy_wh / interval_minutes) * 60 if energy_wh else None

                readings.append({
                    "timestamp": timestamp,
                    "energy_wh": energy_wh,
                    "power_w": power_w,
                    "interval_minutes": interval_minutes,
                    "data_type": "production",
                    "devices_reporting": interval.get("devices_reporting"),
                })

        # Sort by timestamp
        readings.sort(key=lambda x: x.get("timestamp", ""))

        return readings

    def run(self, lookback_hours: Optional[int] = None) -> Dict[str, Any]:
        """
        Run the fetcher for all active Enphase credentials.

        Overrides base run() to use OAuth token refresh.

        Args:
            lookback_hours: Hours to look back for data. Defaults to config value.

        Returns:
            Summary of fetch results.
        """
        from datetime import timedelta

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
                provider="enphase",
                client_id=self.config.enphase_client_id,
                client_secret=self.config.enphase_client_secret,
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

                        # Fetch data from Enphase API
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

    parser = argparse.ArgumentParser(description="Enphase Data Fetcher")
    parser.add_argument("--dry-run", action="store_true", help="Don't upload to S3")
    parser.add_argument("--lookback", type=int, default=2, help="Hours to look back")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    fetcher = EnphaseFetcher(dry_run=args.dry_run)
    results = fetcher.run(lookback_hours=args.lookback)

    print(f"\nResults: {results}")


if __name__ == "__main__":
    main()
