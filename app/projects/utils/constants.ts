/**
 * Shared constants for the projects dashboard.
 */

/** Current organization ID (hardcoded until multi-org support). */
export const CURRENT_ORGANIZATION_ID = 1

/** Convert a lookup table into select options. */
export function toOpts(items: { id: number; code?: string; name: string }[]): { value: number; label: string }[] {
  return (items ?? []).map((t) => ({ value: t.id, label: t.name }))
}
