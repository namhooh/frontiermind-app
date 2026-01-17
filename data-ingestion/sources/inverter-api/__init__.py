"""
FrontierMind Fetcher Workers

This package contains fetcher workers for pulling meter data from
inverter manufacturer APIs (SolarEdge, GoodWe, Enphase, SMA).

Each fetcher:
1. Retrieves credentials from Supabase
2. Fetches data from manufacturer API
3. Transforms to canonical JSON format
4. Uploads to S3 raw/ folder for Lambda processing
"""

from .base_fetcher import BaseFetcher
from .config import Config
from .enphase.fetcher import EnphaseFetcher
from .goodwe.fetcher import GoodWeFetcher
from .sma.fetcher import SMAFetcher
from .solaredge.fetcher import SolarEdgeFetcher

__all__ = [
    "BaseFetcher",
    "Config",
    "SolarEdgeFetcher",
    "GoodWeFetcher",
    "EnphaseFetcher",
    "SMAFetcher",
]
