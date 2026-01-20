-- Migration: Remove expected_resolution_date and next_follow_up_date from patient_cases
-- Reason: Follow-up dates are better managed at the visit level, and resolution dates are unpredictable

ALTER TABLE patient_cases DROP COLUMN IF EXISTS expected_resolution_date;
ALTER TABLE patient_cases DROP COLUMN IF EXISTS next_follow_up_date;
