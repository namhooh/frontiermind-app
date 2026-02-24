"""
Available Energy Calculator

Implements the contractual Available Energy formula:

  E_Available(x) = (E_hist / Irr_hist) × (1 / Intervals) × Irr(x)

Where:
  - E_hist = Energy from billing meter for previous month during Normal Operation (irr > 100 W/m²)
  - Irr_hist = Average in-plane irradiance for previous month during Normal Operation (irr > 100 W/m²)
  - Intervals = Number of 15-min intervals under Normal Operation with irr > 100 W/m²
  - Irr(x) = In-plane irradiance for the current 15-minute interval

Monthly Available Energy per meter = SUM of E_Available(x) across all curtailed intervals.
Total Available Energy = SUM of available_energy_kwh across all meters.

Manual values always take precedence over auto-calculation.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Minimum irradiance threshold (W/m²) for Normal Operation intervals
IRRADIANCE_THRESHOLD = 100.0


def compute_available_energy_for_meter(
    cur: Any,
    meter_id: int,
    billing_month: date,
) -> Optional[float]:
    """Compute Available Energy for a single meter for a given month.

    Uses 15-minute meter_reading data from the current and previous month.

    Args:
        cur: Database cursor (RealDictCursor)
        meter_id: The billing meter ID
        billing_month: First day of the billing month (e.g. 2025-12-01)

    Returns:
        Available energy in kWh, or None if insufficient data.
    """
    # Previous month for historical reference values
    if billing_month.month == 1:
        prev_month = date(billing_month.year - 1, 12, 1)
    else:
        prev_month = date(billing_month.year, billing_month.month - 1, 1)

    # End of previous month
    prev_month_end = billing_month - timedelta(days=1)

    # End of current month
    if billing_month.month == 12:
        curr_month_end = date(billing_month.year + 1, 1, 1)
    else:
        curr_month_end = date(billing_month.year, billing_month.month + 1, 1)

    # 1. Get previous month historical data (Normal Operation, irr > threshold)
    cur.execute("""
        SELECT
            COALESCE(SUM(energy_wh), 0) / 1000.0 AS e_hist_kwh,
            AVG(irradiance_wm2) AS irr_hist,
            COUNT(*) AS intervals
        FROM meter_reading
        WHERE meter_id = %(meter_id)s
          AND reading_timestamp >= %(prev_start)s
          AND reading_timestamp < %(prev_end)s
          AND irradiance_wm2 IS NOT NULL
          AND irradiance_wm2 > %(threshold)s
          AND COALESCE(is_curtailed, false) = false
    """, {
        "meter_id": meter_id,
        "prev_start": prev_month,
        "prev_end": billing_month,
        "threshold": IRRADIANCE_THRESHOLD,
    })
    hist = cur.fetchone()

    if not hist or hist["intervals"] == 0 or not hist["irr_hist"]:
        logger.debug(
            "Insufficient historical data for meter %d month %s",
            meter_id, billing_month,
        )
        return None

    e_hist = float(hist["e_hist_kwh"])
    irr_hist = float(hist["irr_hist"])
    intervals = int(hist["intervals"])

    if irr_hist == 0 or intervals == 0:
        return None

    # Ratio: energy per unit irradiance per interval
    ratio = e_hist / irr_hist / intervals

    # 2. Get current month curtailed intervals
    cur.execute("""
        SELECT
            COALESCE(SUM(irradiance_wm2), 0) AS sum_irr_curtailed
        FROM meter_reading
        WHERE meter_id = %(meter_id)s
          AND reading_timestamp >= %(curr_start)s
          AND reading_timestamp < %(curr_end)s
          AND irradiance_wm2 IS NOT NULL
          AND irradiance_wm2 > %(threshold)s
          AND is_curtailed = true
    """, {
        "meter_id": meter_id,
        "curr_start": billing_month,
        "curr_end": curr_month_end,
        "threshold": IRRADIANCE_THRESHOLD,
    })
    curtailed = cur.fetchone()

    if not curtailed or curtailed["sum_irr_curtailed"] == 0:
        return 0.0

    available_kwh = ratio * float(curtailed["sum_irr_curtailed"])
    return round(available_kwh, 3)


def get_available_energy(
    cur: Any,
    meter_id: int,
    billing_month: date,
) -> Optional[float]:
    """Get Available Energy for a meter/month, preferring stored manual values.

    Precedence:
      1. Stored value in meter_aggregate.available_energy_kwh (manual/import)
      2. Auto-calculated from 15-min meter_reading data (if available)
      3. None (no data)
    """
    # Check for stored manual value
    cur.execute("""
        SELECT available_energy_kwh
        FROM meter_aggregate
        WHERE meter_id = %(meter_id)s
          AND date_trunc('month', period_start) = %(bm)s
          AND available_energy_kwh IS NOT NULL
        LIMIT 1
    """, {"meter_id": meter_id, "bm": billing_month})
    row = cur.fetchone()
    if row and row["available_energy_kwh"] is not None:
        return float(row["available_energy_kwh"])

    # Attempt auto-calculation from 15-min data
    return compute_available_energy_for_meter(cur, meter_id, billing_month)
