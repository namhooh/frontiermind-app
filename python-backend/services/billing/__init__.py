"""
Billing compute services package.

Contains:
- TariffRateService: Generate tariff rates from clause_tariff + FX + MRP
- PerformanceService: Compute plant_performance from meter_aggregate + forecasts
- InvoiceService: Generate expected invoices from rates + meter data + tax rules
- BillingCycleOrchestrator: Run the full monthly billing cycle as a dependency graph
"""
