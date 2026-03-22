"""
Fix MB01 clause_tariff 56:
1. Populate missing fields (valid_to, organization_id, tariff_group_key)
2. Extend tariff_rate schedule from 3 years to full 20 years (1% annual escalation)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from dateutil.relativedelta import relativedelta
from db.database import init_connection_pool, close_connection_pool, get_db_connection

CLAUSE_TARIFF_ID = 56
CONTRACT_ID = 23
BASE_RATE = Decimal("0.0654")
ESCALATION_RATE = Decimal("0.01")  # 1% per year
COD_DATE = date(2025, 1, 1)
TERM_YEARS = 20


def main():
    init_connection_pool(min_connections=1, max_connections=3)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # 1. Fix clause_tariff missing fields
            valid_to = COD_DATE + relativedelta(years=TERM_YEARS)
            cur.execute("""
                UPDATE clause_tariff
                SET valid_to = %s,
                    organization_id = 1,
                    tariff_group_key = 'CONKEN00-2023-00009_KE-MB01_Main_Tariff',
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, valid_from, valid_to, organization_id, tariff_group_key
            """, (valid_to, CLAUSE_TARIFF_ID))
            row = cur.fetchone()
            print(f"Updated clause_tariff {row['id']}:")
            print(f"  valid_to: {row['valid_to']}")
            print(f"  organization_id: {row['organization_id']}")
            print(f"  tariff_group_key: {row['tariff_group_key']}")

            # 2. Check existing tariff_rate rows
            cur.execute("""
                SELECT operating_year FROM tariff_rate
                WHERE clause_tariff_id = %s
                ORDER BY operating_year
            """, (CLAUSE_TARIFF_ID,))
            existing_years = {r['operating_year'] for r in cur.fetchall()}
            print(f"\nExisting tariff_rate years: {sorted(existing_years)}")

            # 3. Generate missing years (4-20)
            inserted = 0
            for year in range(1, TERM_YEARS + 1):
                if year in existing_years:
                    continue

                # Rate = base_rate * (1 + escalation)^(year-1)
                rate = BASE_RATE * (1 + ESCALATION_RATE) ** (year - 1)
                rate = rate.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

                period_start = COD_DATE + relativedelta(years=year - 1)
                period_end = COD_DATE + relativedelta(years=year) - relativedelta(days=1)

                cur.execute("""
                    INSERT INTO tariff_rate (
                        clause_tariff_id, operating_year, rate_granularity,
                        period_start, period_end,
                        hard_currency_id, local_currency_id, billing_currency_id,
                        effective_rate_contract_ccy, effective_rate_hard_ccy,
                        effective_rate_local_ccy, effective_rate_billing_ccy,
                        effective_rate_contract_role,
                        calculation_basis, calc_status, is_current
                    ) VALUES (
                        %s, %s, 'annual',
                        %s, %s,
                        1, 1, 1,
                        %s, %s, %s, %s,
                        'hard',
                        %s, 'computed', false
                    )
                    RETURNING id, operating_year
                """, (
                    CLAUSE_TARIFF_ID, year,
                    period_start, period_end,
                    rate, rate, rate, rate,
                    f"Year {year}: {BASE_RATE} × (1 + {ESCALATION_RATE})^{year-1}"
                ))
                r = cur.fetchone()
                inserted += 1
                if year <= 5 or year >= 19:
                    print(f"  Year {r['operating_year']}: {rate} USD/kWh")
                elif year == 6:
                    print(f"  ... (years 6-18)")

            conn.commit()
            print(f"\nInserted {inserted} new tariff_rate rows")
            print(f"Total: {len(existing_years) + inserted} years")


if __name__ == "__main__":
    main()
