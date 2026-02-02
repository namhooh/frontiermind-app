# Import python packages
import streamlit as st
st.set_page_config(layout="wide")

import pandas as pd
import numpy as np
import time
from snowflake.snowpark.context import get_active_session
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

# Get the current credentials
session = get_active_session()
user = st.experimental_user['email']
#user= st.user.user_name
#st.write(user)
# """
# TODO: 
# - Caching for faster run-time/better handling on queries to the database
# - Refactor some of the SQL logic into DBT views for better version control and data management
# - Work in statefulness = use type 2 aspects of dataset meaning for a given month, get the pricing/meter reading data as of that point
# - Work in foreign exchange = How best to automatically get the XE mid-price?
# """

# ------------------------
# FUNCTIONS
# ------------------------

def get_current_contracts():
    query = """
                select *
                from dim_finance_contract
                where dim_current_record = 1
                    and active = 1
            """
    current_contracts = session.sql(query).to_pandas()
    return current_contracts

def apply_price_adjust_date_logic(df):
    """
    The pricing config dataset has a field called PRICE_ADJUST_DATE which represents the 
    starting date of price adjustments. 
    
    The pricing config then determines the frequency of the changes 
    from that date. 
    
    This function updates the original starting PRICE_ADJUST_DATE field to be 
    the next upcoming PRICE_ADJUST_DATE but also include the previous month.

    # TODO: edge case at the change of the year. This function doesn't yet handle the case 
    in January where we want to keep the PRICE_ADJUST_DATE for December.
    """
     # Price adjust date is the starting date of the price adjustments. Need to adjust to find the upcoming price adjustment date.
    df['PRICE_ADJUST_DATE'] = pd.to_datetime(df['PRICE_ADJUST_DATE'])
    df['PRICE_ADJUST_DATE'] = df['PRICE_ADJUST_DATE'].apply(lambda x: 
                                                            None 
                                                            if x < pd.to_datetime('2000-01-01')
                                                            else x)
    
    
    current_year = pd.Timestamp.today().year
    current_month = pd.Timestamp.today().month

    df['PRICE_ADJUST_DATE'] = (
        df.apply(lambda row:
              row['PRICE_ADJUST_DATE'].replace(year=current_year)
              if row['PRICE_ADJUST_FREQ_DESC'] == 'Year'
              else row['PRICE_ADJUST_DATE'],
            axis=1)
    )
    # For YEAR changes, the upcoming PRICE_ADJUST_DATE should also include the previous month so that it can be used for checking 
    # price changes that should have recently happened.
    
    df['PRICE_ADJUST_DATE'] = (
        df.apply(lambda row:
              row['PRICE_ADJUST_DATE'].replace(year=current_year + 1)
              if (row['PRICE_ADJUST_FREQ_DESC'] == 'Year') & (row['PRICE_ADJUST_DATE'] < (pd.Timestamp.today().replace(day=1) - pd.offsets.Day(32))) 
              else row['PRICE_ADJUST_DATE'],
            axis=1)
    )
    df['PRICE_ADJUST_DATE'] = (
        df.apply(lambda row:
              row['PRICE_ADJUST_DATE'].replace(month=current_month).replace(year=current_year)
              if row['PRICE_ADJUST_FREQ_DESC'] == 'Month'
              else row['PRICE_ADJUST_DATE'],
            axis=1)
    )
    df['PRICE_ADJUST_DATE'] = df['PRICE_ADJUST_DATE'].dt.date
    return df

def get_pricing_adjustments():
    """
    Function to get the Pricing Adjustment config and
    additional contract line information for every contract.

    Adjusts the PRICE_ADJUST_DATE to be the next pricing adjustment date given the config frequency. 
    """
    query = """
        with contract_lines as (
                select
                    e.customer_number,
                    c.contract_number,
                    c.contract_line,
                    a.dim_finance_pricing_adjust_config_id,
                    c.active_status,
                    c.effective_start_date,
                    c.effective_end_date,
                    c.price_adjust_date,
                    d.product_code,
                    c.product_desc,
                    c.updated_at,
                    c.updated_by
                from fct_finance_contract_lines_current as a
                inner join dim_finance_contract_line as c
                    on a.dim_finance_contract_line_id = c.dim_finance_contract_line_id
                inner join dim_finance_product_code as d
                    on a.dim_finance_product_code_id = d.dim_finance_product_code_id
                inner join dim_finance_contract e
                    on a.dim_finance_contract_id = e.dim_finance_contract_id
                    and c.active_status = 1
            )
            select 
                a.price_adjust_date,
                a.updated_at as last_updated_at,
                a.updated_by as last_updated_by,
                a.customer_number,
                a.contract_number,
                a.contract_line,
                a.product_code,
                a.product_desc,
                b.price_adjust_freq_desc,
                b.price_adjust_column_desc,
                b.price_adjust_direction_desc,
                b.price_adjust_type_desc,
                b.price_adjust_auto_desc,
                b.floating_price_reference_desc
            from contract_lines a
            inner join dim_finance_pricing_adjust_config b
                on a.dim_finance_pricing_adjust_config_id = b.dim_finance_pricing_adjust_config_id
            order by a.price_adjust_date ASC, customer_number, contract_number, contract_line
            """
    upcoming_adjustments = session.sql(query).to_pandas()

    # Price adjust date is the starting date of the price adjustments. Need to adjust to find the upcoming price adjustment date.
    upcoming_adjustments.drop_duplicates(keep='first',inplace=True)
    upcoming_adjustments = apply_price_adjust_date_logic(upcoming_adjustments)
    return upcoming_adjustments

def get_current_contract_pricing(contract_number):

    # TODO: Put this into a view in DBT
    query = f"""
            with pricing_logic_1 as (
                select
                    c.contract_number,
                    c.contract_line,
                    c.active_status,
                    c.effective_start_date,
                    c.effective_end_date,
                    c.price_adjust_date AS price_adjust_start_date,
                    d.product_code,
                    c.product_desc,
                    b.measure_short_name,
                    a.measure_value,
                    c.updated_at,
                    c.updated_by
                from fct_finance_contract_lines_current as a
                inner join dim_measure as b
                    on a.dim_measure_id = b.dim_measure_id
                inner join dim_finance_contract_line as c
                    on a.dim_finance_contract_line_id = c.dim_finance_contract_line_id
                inner join dim_finance_product_code as d
                    on a.dim_finance_product_code_id = d.dim_finance_product_code_id
                where b.measure_id in (
                    'GROSS_PRICE_contract_lines',
                    'DISCOUNT_1_contract_lines',
                    'DISCOUNT_2_contract_lines',
                    'DISCOUNT_3_contract_lines',
                    'CEILING_TARIFF_LOCAL_contract_lines',
                    'FLOOR_TARIFF_LOCAL_contract_lines',
                    'CEILING_TARIFF_USD_contract_lines',
                    'FLOOR_TARIFF_USD_contract_lines',
                    'NET_PRICE_contract_lines'
                    )
                    and c.active_status = 1
                    and c.contract_number = '{contract_number}'
            ),
            pricing_logic_1_pivot as (
                select
                    contract_number,
                    contract_line,
                    active_status,
                    product_code,
                    product_desc,
                    effective_start_date,
                    effective_end_date,
                    price_adjust_start_date,
                    updated_at,
                    updated_by,
                    "'Gross_price'" as gross_price,
                    "'Discount_1'" as discount_1,
                    "'Discount_2'" as discount_2,
                    "'Discount_3'" as discount_3,
                    "'Floor_tariff_local'" as floor_tariff_local,
                    "'Ceiling_tariff_local'" as ceiling_tariff_local,
                    "'Floor_tariff_usd'" as floor_tariff_usd,
                    "'Ceiling_tariff_usd'" as ceiling_tariff_usd,
                    "'Net_price'" as net_price
                from pricing_logic_1
                pivot (max(measure_value) for measure_short_name in (
                    'Gross_price',
                    'Discount_1',
                    'Discount_2',
                    'Discount_3',
                    'Floor_tariff_local',
                    'Ceiling_tariff_local',
                    'Floor_tariff_usd',
                    'Ceiling_tariff_usd',
                    'Net_price'
                    )
                )
            ),
            pricing_logic_2 as (
                select
                    *,
                    gross_price * (100.0 - (discount_1 + discount_2 + discount_3))/100.0 as discounted_gross_price
                from pricing_logic_1_pivot
            )
            select
                *
            from pricing_logic_2
            """
    current_contract_pricing = session.sql(query).to_pandas()
    return current_contract_pricing

def derive_local_and_usd_final_prices(df_pricing, exchange_rate):
    df_pricing['EXCHANGE_RATE_CBE'] = exchange_rate
    df_pricing['DISCOUNTED_GROSS_PRICE_USD'] = df_pricing['DISCOUNTED_GROSS_PRICE'] / df_pricing['EXCHANGE_RATE_CBE']
    df_pricing['FLOOR_TARIFF_LOCAL'] = df_pricing['FLOOR_TARIFF_USD'] * df_pricing['EXCHANGE_RATE_CBE']
    df_pricing['CEILING_TARIFF_LOCAL'] = df_pricing['CEILING_TARIFF_USD'] * df_pricing['EXCHANGE_RATE_CBE']

    df_pricing['FLOOR_TARIFF_USED'] = (df_pricing.apply(lambda row:
                                                row['FLOOR_TARIFF_USD']
                                                if (row['FLOOR_TARIFF_USD'] > 0) & (row['DISCOUNTED_GROSS_PRICE_USD'] < row['FLOOR_TARIFF_USD'])
                                                else None
                                                ,axis=1
                                                )
                                            )
    df_pricing['CEILING_TARIFF_USED'] = (df_pricing.apply(lambda row:
                                                row['CEILING_TARIFF_USD']
                                                if (row['CEILING_TARIFF_USD'] > 0) & (row['DISCOUNTED_GROSS_PRICE_USD'] > row['CEILING_TARIFF_USD'])
                                                else None
                                                ,axis=1
                                                )
                                            )
    df_pricing['FINAL_PRICE_USD'] = df_pricing[['FLOOR_TARIFF_USED', 'CEILING_TARIFF_USED', 'DISCOUNTED_GROSS_PRICE_USD']].bfill(axis=1).iloc[:, 0]
    df_pricing['FINAL_PRICE_LOCAL'] = (df_pricing['FINAL_PRICE_USD'] * df_pricing['EXCHANGE_RATE_CBE']).round(4)
    
    return df_pricing
  
def get_current_meter_readings(contract_number):
    query = f"""
            select
                c.contract_number,
                c.contract_line,
                b.start_date,
                b.end_date,
                b.bill_date,
                b.active_status,
                b.updated_at,
                b.updated_by,
                a.opening_reading, 
                a.closing_reading, 
                a.utilized_reading,
                a.discount_reading,
                a.sourced_energy
            from fct_finance_meter_readings_current as a
            inner join dim_finance_meter_reading as b
                on a.dim_finance_meter_reading_id = b.dim_finance_meter_reading_id
            inner join dim_finance_contract_line as c
                on a.dim_finance_contract_line_id = c.dim_finance_contract_line_id
            where c.contract_number = '{contract_number}'
                and ((b.active_status is NULL) or
                     (b.active_status = 1))
            order by c.contract_line, b.start_date
            """
    current_meter_readings = session.sql(query).to_pandas()
    return current_meter_readings

def get_recent_contract_changes(customer_number):
    query = f"""
            select
                e.customer_number,
                c.contract_number,
                c.contract_line,
                c.active_status,
                d.product_code,
                c.product_desc,
                b.measure_short_name,
                a.measure_value,
                c.updated_at,
                c.updated_by,
                case when a.fct_current_record = 1
                    then TRUE
                    else FALSE
                    end as current_value
            from fct_finance_contract_lines_full_history as a
            inner join dim_measure as b
                on a.dim_measure_id = b.dim_measure_id
            inner join dim_finance_contract_line as c
                on a.dim_finance_contract_line_id = c.dim_finance_contract_line_id
            inner join dim_finance_product_code as d
                on a.dim_finance_product_code_id = d.dim_finance_product_code_id
            inner join dim_finance_contract e
                    on a.dim_finance_contract_id = e.dim_finance_contract_id
            where e.customer_number = '{customer_number}'
                and (
                        (a.fct_end_date > dateadd(month, -3, current_date))
                        or
                        (c.dim_end_date > dateadd(month, -3, current_date))
                    )
            order by c.contract_number, c.contract_line, a.dim_measure_id
            """
    recent_contract_changes = session.sql(query).to_pandas()
    return recent_contract_changes

def list_of_end_of_months(n_months):
    today = pd.Timestamp.today()
    end_of_month_dates = [pd.Timestamp(today).normalize() - pd.offsets.MonthEnd(i) for i in range(1, n_months)]
    end_of_month_dates = [d.date() for d in end_of_month_dates]
    return end_of_month_dates

def get_specific_invoice(invoice_date, customer_number):
    query = f"""
            select c.customer_number,
                   -- SPLIT(a.invoice_detail_id, ' ')[ARRAY_SIZE(SPLIT(a.invoice_detail_id, ' ')) - 1]::integer as contract_line, 
                   d.product_code,
                   e.invoice_item_description,
                   b.invoice_number,
                   b.invoice_date,
                   a.quantity, 
                   a.unit_price_local,
                   a.net_unit_price_local,
                   a.tax_amount_local,
                   a.line_item_amount_local,
                   a.line_item_amount_local - a.tax_amount_local as line_item_local,
                   a.discount_amount_local,
                   a.unit_price_usd,
                   a.net_unit_price_usd,
                   a.tax_amount_usd,
                   a.line_item_amount_usd,
                   a.line_item_amount_usd - a.tax_amount_usd as line_item_usd,
                   a.discount_amount_usd
            from dev.dwh.fct_invoice_line_item_current a
            inner join dev.dwh.dim_invoice b
                on a.dim_invoice_id = b.dim_invoice_id
            left join dev.dwh.dim_finance_customer c
                on a.dim_finance_customer_id = c.dim_finance_customer_id
            left join dev.dwh.dim_finance_product_code d
                on a.dim_finance_product_code_id = d.dim_finance_product_code_id
            left join dev.dwh.dim_finance_line_item_desc e
                on a.dim_finance_line_item_desc_id = e.dim_finance_line_item_desc_id
            where b.invoice_date = '{invoice_date}'
                and c.customer_number = '{customer_number}'
                and b.invoice_category_description = 'Invoice'
            order by customer_number, product_code
            """
    invoice_details = session.sql(query).to_pandas()
    return invoice_details

def calculate_invoice_line_item_amounts(pricing, meterreadings):
    """
    Function to combine the contract pricing with the meter readings to calculate
    the expected invoice amount. 

    Calculates invoice amounts in 2 ways:
        1) The way CBE wants to : Adjusting the UTILIZED_READING by the SOURCED_ENERGY and/or DISCOUNT_READING
            and then multiplying that by the FINAL_PRICE derived from the pricing configuration. 
        2) The way SAGE does it : Adjusting the FINAL_PRICE by the ratio of
            (UTILIZED_READING-SOURCED_ENERGY-DISCOUNT_READING)/UTILIZED_READING to get a SAGE_ADJUSTED_PRICE
            and multiplying the UTILIZED_READING by the SAGE_ADJUSTED_PRICE.

    We are doing both to see if discrepencies arise at this level. 
        
    """
    merged = pd.merge(pricing[['CONTRACT_NUMBER','CONTRACT_LINE','FINAL_PRICE_USD','FINAL_PRICE_LOCAL',
                              'PRODUCT_CODE','PRODUCT_DESC',
                              'EFFECTIVE_START_DATE','EFFECTIVE_END_DATE']],
                     meterreadings,
                     how='left', 
                     left_on=['CONTRACT_NUMBER','CONTRACT_LINE'], 
                     right_on=['CONTRACT_NUMBER','CONTRACT_LINE'])
    merged['SITE_METER_ADJUSTED_READING'] = (merged['UTILIZED_READING'] - merged['SOURCED_ENERGY'] - merged['DISCOUNT_READING']
                                             ).round(4)

    # USD AMOUNTS
    merged['SAGE_ADJUSTED_PRICE_USD'] = (merged.apply(
                                    lambda row:  
                                        np.round((row['SITE_METER_ADJUSTED_READING'] * row['FINAL_PRICE_USD'] / row['UTILIZED_READING']),4) 
                                        if row['SOURCED_ENERGY'] + row['DISCOUNT_READING'] > 0 
                                        else row['FINAL_PRICE_USD'],
                                    axis=1
                                    ).round(4)
    )
    merged['VALIDATED_INVOICE_AMOUNT_USD'] = (merged.apply(
                                    lambda row: 
                                        row['SITE_METER_ADJUSTED_READING'] * row['FINAL_PRICE_USD']
                                        if row['PRODUCT_CODE'][:4] == 'ENER'
                                        else row['FINAL_PRICE_USD'],
                                    axis=1
                                )
    )
    merged['SAGE_INVOICE_AMOUNT_USD'] = (merged.apply(
                                    lambda row: 
                                        row['UTILIZED_READING'] * row['SAGE_ADJUSTED_PRICE_USD']
                                        if row['PRODUCT_CODE'][:4] == 'ENER'
                                        else row['FINAL_PRICE_USD'],
                                    axis=1
                                )
    )
    # LOCAL AMOUNTS
    merged['SAGE_ADJUSTED_PRICE_LOCAL'] = (merged.apply(
                                    lambda row:  
                                        np.round((row['SITE_METER_ADJUSTED_READING'] * row['FINAL_PRICE_LOCAL'] / row['UTILIZED_READING']),4) 
                                        if row['SOURCED_ENERGY'] + row['DISCOUNT_READING'] > 0 
                                        else row['FINAL_PRICE_LOCAL'],
                                    axis=1
                                    ).round(4)
    )
    merged['VALIDATED_INVOICE_AMOUNT_LOCAL'] = (merged.apply(
                                    lambda row: 
                                        row['SITE_METER_ADJUSTED_READING'] * row['FINAL_PRICE_LOCAL']
                                        if row['PRODUCT_CODE'][:4] == 'ENER'
                                        else row['FINAL_PRICE_LOCAL'],
                                    axis=1
                                )
    )
    merged['SAGE_INVOICE_AMOUNT_LOCAL'] = (merged.apply(
                                    lambda row: 
                                        row['UTILIZED_READING'] * row['SAGE_ADJUSTED_PRICE_LOCAL']
                                        if row['PRODUCT_CODE'][:4] == 'ENER'
                                        else row['FINAL_PRICE_LOCAL'],
                                    axis=1
                                )
    )
    return merged

def get_exchange_rates(invoice_date):
    query = f"""
        with ordered_entries as (
            select
                *,
                ROW_NUMBER() OVER (PARTITION BY FROM_CURRENCY,
                                                TO_CURRENCY,
                                                EXCHANGE_DATE
                                    ORDER BY ADDED_WHEN DESC)
                            AS most_recent_entry
             from raw.manual.invoice_validation_exchange_rates
             where exchange_date = '{invoice_date}'
        )
        select
            *
        from ordered_entries
        where most_recent_entry = 1
        """
    exchange_rates = session.sql(query).to_pandas()
    return exchange_rates

def insert_new_exchange_rate_data(data, user):
    """
    Add new data to the configured table. Add additional columns to capture who 
    added the data and when for auditing. 
    """
    # Function to add the data in the dataframe to the table
    data['ADDED_BY'] = user
    data['ADDED_WHEN'] = datetime.now()


    for index, row in data.iterrows():
        sql_statement = f""" INSERT INTO RAW.MANUAL.invoice_validation_exchange_rates (from_currency,
                                                                                        to_currency,
                                                                                        exchange_date,
                                                                                        exchange_rate,
                                                                                        added_by,
                                                                                        added_when)
                            VALUES ('{row['FROM_CURRENCY']}',
                                    '{row['TO_CURRENCY']}',
                                    '{row['EXCHANGE_DATE']}',
                                     {row['EXCHANGE_RATE']},
                                    '{row['ADDED_BY']}',
                                    '{row['ADDED_WHEN']}'
                                    )
                        """
        session.sql(sql_statement).collect()    
    return True

def conduct_analysis_for_given_contracts(df_contracts, contracts, invoice_month):
    """
    contracts should be a list of contracts
    """
    df_invoice_list = []
    df_pricing_list = []
    df_meter_readings_list = []
    df_merged_month_list = []
    compare_list = []

    df_exchange_rates = get_exchange_rates(invoice_month)
    
    
    for contract_number in contracts:
        mask = df_contracts['CONTRACT_NUMBER']== contract_number
        
        customer_number = df_contracts[mask]['CUSTOMER_NUMBER'].values[0]
        facility_number = df_contracts[mask]['FACILITY'].values[0]
        local_currency = df_contracts[mask]['CONTRACT_CURRENCY'].values[0]
        print(df_exchange_rates)

        # If the exchange rate is empty, I need to stop. Or we have to make sure that the exchange rate is never empty
        if df_exchange_rates[df_exchange_rates['TO_CURRENCY']==local_currency].shape[0] == 0:
            st.error(f"Exchange rate for {local_currency} not found for invoice month {invoice_month}.")
            return None, None, None, None, None   
            
        exchange_rate = df_exchange_rates[df_exchange_rates['TO_CURRENCY']==local_currency]['EXCHANGE_RATE'].values[0]

        # exchange_rate = df_exchange_rates[df_exchange_rates['CURRENCY']==local_currency]['EXCHANGE_RATE'].values[0]

        # Get the Sage invoice for this month
        # Note: If this hasn't been generated yet for the invoice month in question,
        # this will return an empty dataframe.
        df_invoice = get_specific_invoice(invoice_month, customer_number)
        df_invoice = df_invoice.rename(columns = {'LINE_ITEM_LOCAL':'INVOICE_AMOUNT_LOCAL',
                                                  'LINE_ITEM_USD':'INVOICE_AMOUNT_USD'})
        
            
        # Uses the current view of the contract line fact table
        df_pricing = get_current_contract_pricing(contract_number)
        df_pricing = derive_local_and_usd_final_prices(df_pricing, exchange_rate)
        
        # Uses the current view of the meter reading fact table.
        # Pulls in all history but with the most recent values.
        df_meter_readings = get_current_meter_readings(contract_number)
        
        # Merges the current pricing with the meter readings and calculates the expected invoice amounts.
        merged = calculate_invoice_line_item_amounts(df_pricing, df_meter_readings)
        
        # reduce the dataset to the invoice month we are interested in.
        # Note: If the meter readings for the month in question have not yet been entered or updated in
        # in the dwh, then this will only filter non-energy related line items. 
        mask = ((pd.to_datetime(merged['BILL_DATE']) == pd.to_datetime(invoice_month)) 
                | (merged['BILL_DATE'].isna())
               )
        df_merged_month = merged[mask]
    
        # Merging validated invoice amounts (df_merged_month) with the sage invoice amount (df_invoice)
        # for comparison. Merging on PRODUCT_CODE _ PRODUCT_DESC because for some reason when new line items 
        # are created, the contract line number at the invoice level doesn't change, even though the
        # old contract line item has been made inactive. 
        df_merged_month['join_key'] = df_merged_month['PRODUCT_CODE'] + '_' + df_merged_month['PRODUCT_DESC']
        df_invoice['join_key'] = df_invoice['PRODUCT_CODE'] + '_' + df_invoice['INVOICE_ITEM_DESCRIPTION']
        compare = (pd.merge(
                        df_merged_month[['PRODUCT_CODE','PRODUCT_DESC','CONTRACT_NUMBER','CONTRACT_LINE','VALIDATED_INVOICE_AMOUNT_USD','VALIDATED_INVOICE_AMOUNT_LOCAL','join_key']],
                        df_invoice[['PRODUCT_CODE','INVOICE_ITEM_DESCRIPTION','INVOICE_AMOUNT_LOCAL','INVOICE_AMOUNT_USD','join_key']],
                        how='left',
                        left_on=['join_key'],
                        right_on=['join_key'],
                        suffixes =('','_y')
                        )
                  )
    
        # Compare to 4dp
        compare['VALIDATED'] = compare['VALIDATED_INVOICE_AMOUNT_LOCAL'].round(4) == compare['INVOICE_AMOUNT_LOCAL'].round(4)
        compare['CUSTOMER_NUMBER'] = customer_number

        df_invoice_list.append(df_invoice)
        df_pricing_list.append(df_pricing)
        df_meter_readings_list.append(df_meter_readings)
        df_merged_month_list.append(df_merged_month)
        compare_list.append(compare)

    if len(df_invoice_list) > 0:
        df_invoice  = pd.concat(df_invoice_list).reset_index(drop=True)
    df_pricing = pd.concat(df_pricing_list).reset_index(drop=True)
    df_meter_readings = pd.concat(df_meter_readings_list).reset_index(drop=True)
    df_merged_month = pd.concat(df_merged_month_list).reset_index(drop=True)
    compare = pd.concat(compare_list).reset_index(drop=True)
    
    return df_pricing, df_meter_readings, df_merged_month, df_invoice, compare  

def rename_dataframe_columns(df):
    """
    Takes a pandas DataFrame and returns a new DataFrame
    with columns renamed:
    - Underscores replaced with spaces
    - Each word capitalized

    Args:
        df (pd.DataFrame): Input DataFrame

    Returns:
        pd.DataFrame: New DataFrame with formatted column names
    """
    renamed_columns = {col: col.replace('_', ' ').title() for col in df.columns}
    return df.rename(columns=renamed_columns)


# ------------------------
# GET SET UP DATA
# ------------------------

df_contracts = get_current_contracts()
all_contracts_list = list(df_contracts['CONTRACT_NUMBER'])
all_customers_list = df_contracts['CUSTOMER_NUMBER'].unique()
all_currencies_list = df_contracts['CONTRACT_CURRENCY'].unique()

month_list = list_of_end_of_months(6)

# ------------------------
# DASHBOARD CONFIGURATION
# ------------------------

# ------------------------
# SECTION Intro: Introduction and context
# ------------------------

st.title("Sage Invoice Validation App")
st.text("""WIP. Author: Rosina Norton

Application for the Asset Management / Finance team to use to validate better invoices created by the Sage system""")

# ------------------------
# SECTION 1: Pricing adjustments
# ------------------------

st.divider()
st.header("1. Contract Pricing Adjustments")
st.subheader('Upcoming and recent adjustments')
st.text("""
The table below shows the contracts and contract lines ordered by the next upcoming pricing adjustment date. 

You can also use this table to find recently changed contracts by looking at the LAST_UPDATED_AT field.
""")
df_pricing_adjustments = get_pricing_adjustments()
st.dataframe(rename_dataframe_columns(df_pricing_adjustments.sort_values(by=['PRICE_ADJUST_DATE','CUSTOMER_NUMBER','CONTRACT_NUMBER','CONTRACT_LINE'])))

# ------------------------
# SECTION 2: Track Contract Changes
# ------------------------

# Track changes to specific contracts
st.divider()
st.header('2. Track contract changes to specific customers')
st.text("""This section allows you to see what changes have been made to the contract pricing in the last 3 months.

NOTE that we only start tracking history as of mid March 2025, so we can't show changes before then.""")
# Pick a contract to track changes
track_changes_customer_selection = st.multiselect(
    label="Choose a customer. All customers with active contracts shown.",
    options=all_customers_list,
    max_selections=1,
)
if (len(track_changes_customer_selection) == 0):
    st.error("Please select a contract to continue")
else:
    # Add a button here that allows the user to toggle on active product lines 
    # st.form_submit_button(
    #     ## Blah
    # )
    track_changes_customer = track_changes_customer_selection[0]
    df_contract_changes = get_recent_contract_changes(track_changes_customer)
    
    # Identify columns to keep (all except the two pivot columns)
    non_pivot_cols = df_contract_changes.columns.difference(['MEASURE_SHORT_NAME', 'MEASURE_VALUE']).tolist()
    
    # Pivot the DataFrame
    df_contract_changes = df_contract_changes.pivot_table(
        index=non_pivot_cols,               # all other fields define uniqueness
        columns='MEASURE_SHORT_NAME',
        values='MEASURE_VALUE',
        aggfunc='first'                     # use first in case of duplicates
    ).reset_index()
    
    # Optional: flatten multi-index columns if needed
    df_contract_changes.columns.name = None

     # Add a checkbox to toggle showing only active lines
    show_active_only = st.checkbox("Show only active product lines (CURRENT_VALUE = True)", value=False)

    # Apply the filter based on toggle
    if show_active_only and 'CURRENT_VALUE' in df_contract_changes.columns:
        df_contract_changes = df_contract_changes[df_contract_changes['CURRENT_VALUE'] == True]

    st.dataframe(rename_dataframe_columns(df_contract_changes))

# There is another product code that we should bringing. 
# We don't want to display the line items that are no longer active
# Check the customer NBL02 - It was 8 codes, and we only use 2. 
# This should only pull in the active product codes 


# ------------------------
# SECTION 3: Validate invoice generation
# ------------------------

st.divider()
st.header("3. Validate invoice generation")
st.text(""" This section recreates what we want the invoice amount to be per line item given our specific
CBE invoice logic. It uses raw contract pricing and meter reading information extracted from the Sage system. 

These values are then compared to the invoices being generated by Sage on a line item basis.
""")
st.text("""
TO DO:
- Once type 2 fact has populated more (or we've built historic snapshots, calculate validation number with the data as of that date, not as of the current date.)
""")

eom_selection = st.multiselect(
    label="Choose an invoice month",
    options=month_list,
    max_selections=1,
)
if (len(eom_selection) == 0):
    st.error("Please select an invoice month to continue")
    st.stop()

invoice_month = eom_selection[0]

# We should have an option to select customers for this invoice month here. Then we'll look at the Exchange rate. 

# ------------------------
# SECTION 4: Exchange Rates
# ------------------------

# Small section to allow the dashboard user to add/update the exchange rates they want to
# use for the invoice validation logic.
st.subheader("""Update or Add Exchange rates""")
st.text("""These exchange rates get saved to the dwh so you only have to add them once. 
Currencies related to active contracts are shown.
The table is interactive so you can click in any cells and update that value. 
Click the 'Add/update exchange rates' button to save the data for future use""")

# Step 1: Pull exchange rates
df_exchange_rates = get_exchange_rates(invoice_month)


if df_exchange_rates.shape[0] == 0:
    df_exchange_rates = pd.DataFrame({
        'FROM_CURRENCY': ['USD'] * len(all_currencies_list),
        'TO_CURRENCY': all_currencies_list,
        'EXCHANGE_DATE': [str(invoice_month)] * len(all_currencies_list),
        'EXCHANGE_RATE': [None] * len(all_currencies_list)
    })

# Step 3: Display editable table
cols = ['FROM_CURRENCY', 'TO_CURRENCY', 'EXCHANGE_DATE', 'EXCHANGE_RATE']
edited_df = st.data_editor(df_exchange_rates[cols], num_rows="dynamic")
# edited_df = st.data_editor(df_exchange_rates[cols])

# Step 4: Handle submission
if st.button("Add/update exchange rates"):
    with st.status("Uploading data...", expanded=True) as upload_status:
        success = insert_new_exchange_rate_data(edited_df, user)
        if success:
            st.success("Data successfully saved!")
        else:
            st.error("Error saving data.")
    upload_status.update(label="Finished!", state="complete", expanded=True)

# Check exchange rates once before processing contracts
if edited_df['EXCHANGE_RATE'].isna().any():
    st.error("Please update all exchange rates before continuing.")
    st.stop()

# Add loading bar
list_df_compares = []
progress_bar = st.progress(0, text="Validating contracts...")

for i, contract_number in enumerate(all_contracts_list):
    # st.write(f"Processing contract: {contract_number}")

    df_pricing, df_meter_readings, df_merged_month, df_invoice, compare = conduct_analysis_for_given_contracts(
        df_contracts, [contract_number], invoice_month
    )
    list_df_compares.append(compare)

    # Update loading bar
    progress_bar.progress((i + 1) / len(all_contracts_list), text=f"Completed {i + 1}/{len(all_contracts_list)}")

progress_bar.empty()  # remove bar when done

# Final output
df_compare = pd.concat(list_df_compares, ignore_index=True).sort_values(by=['CONTRACT_NUMBER','PRODUCT_CODE']).reset_index()

# Calculate the % difference 
df_compare['PCT_DIFF_LOCAL'] = (
    (df_compare['VALIDATED_INVOICE_AMOUNT_LOCAL'] - df_compare['INVOICE_AMOUNT_LOCAL']) 
    / df_compare['INVOICE_AMOUNT_LOCAL']
) * 100

df_compare['PCT_DIFF_USD'] = (
    (df_compare['VALIDATED_INVOICE_AMOUNT_USD'] - df_compare['INVOICE_AMOUNT_USD']) 
    / df_compare['INVOICE_AMOUNT_USD']
) * 100

cols = ['CONTRACT_NUMBER','CUSTOMER_NUMBER',
        'VALIDATED_INVOICE_AMOUNT_LOCAL','INVOICE_AMOUNT_LOCAL',
        'VALIDATED_INVOICE_AMOUNT_USD','INVOICE_AMOUNT_USD',
        'VALIDATED', 'PCT_DIFF_USD', 'PCT_DIFF_LOCAL',
        'CONTRACT_LINE',
        'PRODUCT_CODE','PRODUCT_DESC',]
st.dataframe(rename_dataframe_columns(df_compare[cols]),   
    use_container_width=True)

csv = df_compare.to_csv(index=False)
st.download_button("Download Invoice Generation CSV", data=csv, file_name="invoice_validation.csv", mime="text/csv")

#### Creating Sub Totals ####
# Step 1: Create a new column for the PRODUCT_CODE prefix
df_compare['PRODUCT_GROUP'] = df_compare['PRODUCT_CODE'].str[:2]

# Step 2: Group by the new PRODUCT_GROUP and aggregate the required columns
subtotal_df = df_compare.groupby('PRODUCT_GROUP')[[
    'VALIDATED_INVOICE_AMOUNT_LOCAL',
    'INVOICE_AMOUNT_LOCAL',  # assuming this is the intended column
    'VALIDATED_INVOICE_AMOUNT_USD',
    'INVOICE_AMOUNT_USD'     # assuming this is the intended column
]].sum().reset_index()

# Calculate the % difference 
subtotal_df['PCT_DIFF_LOCAL'] = (
    (subtotal_df['VALIDATED_INVOICE_AMOUNT_LOCAL'] - subtotal_df['INVOICE_AMOUNT_LOCAL']) 
    / subtotal_df['INVOICE_AMOUNT_LOCAL']
) * 100

subtotal_df['PCT_DIFF_USD'] = (
    (subtotal_df['VALIDATED_INVOICE_AMOUNT_USD'] - subtotal_df['INVOICE_AMOUNT_USD']) 
    / subtotal_df['INVOICE_AMOUNT_USD']
) * 100

st.text("""
TO DISCUSS: Here are the sub totals based on the first two letters of the product codes
""")
st.dataframe(rename_dataframe_columns(subtotal_df))

st.text("""
TO DISCUSS: Are we doing % difference correctly? 
""")


# Add section saying what % and number match and don't match. 

# ------------------------
# SECTION 4: Specific Customer Analysis
# ------------------------

st.divider()
st.header("4. Specific Customer Analysis")

customer_selection = st.multiselect(
    label="Choose a customer. All customers with active contracts shown.",
    options=all_customers_list,
    max_selections=1,
    key='customer_selection_for_validation',
)
if (len(customer_selection) == 0):
    st.error("Please select a customer to continue")
    st.stop()

customer_number = customer_selection[0]

# Check box for USD inclusion
st.text("Select if you want to show USD amounts alongside the LOCAL amounts. Note these are very sensitive to the exchange rate being used")
show_usd = st.checkbox("Show USD amounts",value=True)

st.text(f'Validation results for customer {customer_number}')

cols = ['CUSTOMER_NUMBER','CONTRACT_NUMBER','CONTRACT_LINE',
             'PRODUCT_CODE','PRODUCT_DESC',
            'VALIDATED','VALIDATED_INVOICE_AMOUNT_LOCAL','INVOICE_AMOUNT_LOCAL',
                'VALIDATED_INVOICE_AMOUNT_USD','INVOICE_AMOUNT_USD']
if not show_usd:
    cols.remove('VALIDATED_INVOICE_AMOUNT_USD')
    cols.remove('INVOICE_AMOUNT_USD')
mask = df_compare['CUSTOMER_NUMBER'] == customer_number
st.dataframe(rename_dataframe_columns(df_compare[mask][cols]))

# one customer can have multiple active contracts...
contracts = df_compare[mask]['CONTRACT_NUMBER'].unique()
df_pricing, df_meter_readings, df_merged_month, df_invoice, compare = conduct_analysis_for_given_contracts(df_contracts, contracts, invoice_month)


## Contract Information
st.subheader('Contract Information')
last_updated_at = df_pricing['UPDATED_AT'].unique()
last_updated_by = df_pricing['UPDATED_BY'].unique()
if df_pricing['UPDATED_AT'].max() > invoice_month:
    st.warning(f"""The contract configuration has been changed since the invoice date.
    
                 Last updated on {last_updated_at} by sage user {last_updated_by}""", icon="⚠️")

st.text(f"""High-level contract details for {contracts}""")
st.dataframe(rename_dataframe_columns(df_contracts[df_contracts['CONTRACT_NUMBER'].isin(contracts)]))

st.text(f"""Current pricing for contract {contracts}, active lines only""")
st.text(""" The FINAL_PRICE column is a derived from applying the discount and floor/ceiling logic to the gross price 
""")
# TO DO: Flag when FINAL_PRICE is determined by ceiling or floor.
cols = ['CONTRACT_LINE','PRODUCT_CODE','PRODUCT_DESC',
        'FINAL_PRICE_LOCAL','FINAL_PRICE_USD','EXCHANGE_RATE_CBE',
        'GROSS_PRICE','DISCOUNT_1','DISCOUNT_2','DISCOUNT_3',
        'FLOOR_TARIFF_LOCAL','CEILING_TARIFF_LOCAL',
        'FLOOR_TARIFF_USD','CEILING_TARIFF_USD',
        'PRICE_ADJUST_START_DATE']
if not show_usd:
    cols.remove('FINAL_PRICE_USD')
    cols.remove('FLOOR_TARIFF_USD')
    cols.remove('CEILING_TARIFF_USD')
    cols.remove('EXCHANGE_RATE_CBE')
    
st.dataframe(rename_dataframe_columns(df_pricing[cols].sort_values(by='CONTRACT_LINE')))

## Meter readings and pricing
st.subheader("Meter Readings and pricing")
st.text(f"""This table captures the meter readings for the month in question including any 
DISCOUNT_READING or SOURCED_ENERGY that needs to be account for. 
""")

cols = ['CONTRACT_LINE','PRODUCT_CODE','PRODUCT_DESC','SITE_METER_ADJUSTED_READING',
        'OPENING_READING','CLOSING_READING','UTILIZED_READING',
         'DISCOUNT_READING','SOURCED_ENERGY',
        'BILL_DATE',
        ]
st.dataframe(rename_dataframe_columns(df_merged_month[cols].sort_values(by='CONTRACT_LINE')))

totals = df_merged_month[['SITE_METER_ADJUSTED_READING','UTILIZED_READING',
         'DISCOUNT_READING','SOURCED_ENERGY']].sum()
st.text(f"""METER READING TOTALS:

{totals}""")

st.text("""For sites with DISCOUNT_READING or SOURCED_ENERGY, I have calculated the invoice amounts
via two methods:

1) The way CBE wants to : Adjusting the UTILIZED_READING by the SOURCED_ENERGY and/or DISCOUNT_READING
    to get a new SITE_METER_ADJUSTED_READING.
    Then the VALIDATED_INVOICE_AMOUNT = FINAL_PRICE * SITE_METER_ADJUSTED_READING. 
    There is no adjustment to pricing.
     
2) The way SAGE does it : Adjusting the FINAL_PRICE by the ratio of
    (UTILIZED_READING - SOURCED_ENERGY - DISCOUNT_READING) / UTILIZED_READING to get a SAGE_ADJUSTED_PRICE.
    The SAGE_ADJUSTED_PRICE is then rounded to 4 decimal places.  
    Then the SAGE_INVOICE_AMOUNT = UTILIZED_READING * SAGE_ADJUSTED_PRICE.

Discrepencies arise between these two methods because of the rounding of the SAGE_ADJUSTED_PRICE and
the meter reading quantitiy is high. 
""")

st.text('Method 1) CBE method')
cols = ['PRODUCT_CODE','PRODUCT_DESC','SITE_METER_ADJUSTED_READING',
        'FINAL_PRICE_LOCAL','VALIDATED_INVOICE_AMOUNT_LOCAL',
        'FINAL_PRICE_USD','VALIDATED_INVOICE_AMOUNT_USD']
if not show_usd:
    cols.remove('FINAL_PRICE_USD')
    cols.remove('VALIDATED_INVOICE_AMOUNT_USD')
st.dataframe(rename_dataframe_columns(df_merged_month[cols].sort_values(by='PRODUCT_CODE')))

# st.text('Method 1) SAGE method')
# cols = ['PRODUCT_CODE','PRODUCT_DESC','UTILIZED_READING',
#         'SAGE_ADJUSTED_PRICE_LOCAL','SAGE_INVOICE_AMOUNT_LOCAL',
#         'SAGE_ADJUSTED_PRICE_USD','SAGE_INVOICE_AMOUNT_USD']
# if not show_usd:
#     cols.remove('SAGE_ADJUSTED_PRICE_USD')
#     cols.remove('SAGE_INVOICE_AMOUNT_USD')
# st.dataframe(df_merged_month[cols].sort_values(by='PRODUCT_CODE'))

## Invoice data
st.subheader("Invoice Data")
st.text("""If this is empty, it means the invoice has yet to be generated in the Sage system or updated in the warehouse.

Note that the USD conversion is only available in the Invoice data once the invoice has been posted. 
This is a nunance of Sage.""")
st.text(f"""Invoices in {invoice_month}: {df_invoice['INVOICE_NUMBER'].unique()}""")
cols = ['PRODUCT_CODE','INVOICE_ITEM_DESCRIPTION','QUANTITY',
        'UNIT_PRICE_LOCAL','NET_UNIT_PRICE_LOCAL','INVOICE_AMOUNT_LOCAL','DISCOUNT_AMOUNT_LOCAL']
st.text(f"""In LOCAL currency""")
st.dataframe(rename_dataframe_columns(df_invoice[cols].sort_values(by='PRODUCT_CODE')))
if show_usd:
    st.text(f"""In USD currency""")
    cols = [c.replace('LOCAL','USD') for c in cols]
    st.dataframe(rename_dataframe_columns(df_invoice[cols].sort_values(by='PRODUCT_CODE')))



