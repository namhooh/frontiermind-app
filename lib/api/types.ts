/**
 * Shared API types used across multiple API clients.
 *
 * Types defined here are single sources of truth to avoid
 * duplication between reportsClient.ts and notificationsClient.ts.
 */

/** Frequency options for scheduled reports and notification schedules */
export type ReportFrequency = 'monthly' | 'quarterly' | 'annual' | 'on_demand'
