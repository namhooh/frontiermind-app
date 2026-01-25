-- Migration: 019_invoice_comparison_final_amount.sql
-- Description: Add final reconciliation columns to invoice_comparison table
-- Date: 2026-01-24
--
-- Purpose:
-- After comparing expected vs received invoices, users need to record the final
-- reconciled amount to pay. This may differ from the received amount after
-- negotiation or dispute resolution.
--
-- Workflow:
-- 1. Comparison created → final_amount = NULL (not yet reconciled)
-- 2. User reviews variance → Updates status (matched/underbilled/overbilled)
-- 3. User reconciles → Sets final_amount (and adjustment_amount is calculated)
-- 4. Reports → Query final_amount for payment reports

-- Add final reconciliation columns to invoice_comparison
ALTER TABLE invoice_comparison
    ADD COLUMN IF NOT EXISTS final_amount DECIMAL,
    ADD COLUMN IF NOT EXISTS adjustment_amount DECIMAL DEFAULT 0;

-- Add comments for documentation
COMMENT ON COLUMN invoice_comparison.final_amount IS 'Final reconciled amount to pay contractor (may differ from received amount after negotiation)';
COMMENT ON COLUMN invoice_comparison.adjustment_amount IS 'Adjustment made during reconciliation (final_amount - received_amount)';

-- Create index for queries filtering by reconciliation status
CREATE INDEX IF NOT EXISTS idx_invoice_comparison_final_amount
    ON invoice_comparison(final_amount)
    WHERE final_amount IS NOT NULL;

-- Verification query (run manually to verify migration)
-- SELECT column_name, data_type, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'invoice_comparison'
-- AND column_name IN ('final_amount', 'adjustment_amount');
