-- Migration: Simplify patient_history_analysis table
-- Purpose: Remove unused columns that are never populated (saves storage and simplifies schema)
-- Date: 2026-01-06
-- 
-- IMPORTANT: Run this migration only after confirming you don't need the parsed fields
-- The raw_analysis column contains ALL the data, which frontend parses for display

-- Step 1: Drop unused columns
ALTER TABLE public.patient_history_analysis 
DROP COLUMN IF EXISTS comprehensive_summary,
DROP COLUMN IF EXISTS medical_trajectory,
DROP COLUMN IF EXISTS chronic_conditions,
DROP COLUMN IF EXISTS recurring_patterns,
DROP COLUMN IF EXISTS treatment_effectiveness,
DROP COLUMN IF EXISTS risk_factors,
DROP COLUMN IF EXISTS recommendations,
DROP COLUMN IF EXISTS significant_findings,
DROP COLUMN IF EXISTS lifestyle_factors,
DROP COLUMN IF EXISTS medication_history,
DROP COLUMN IF EXISTS follow_up_suggestions;

-- The remaining essential columns are:
-- id, patient_id, doctor_firebase_uid, analysis_period_start, analysis_period_end,
-- total_visits, total_reports, model_used, confidence_score, raw_analysis,
-- analysis_success, analysis_error, processing_time_ms, analyzed_at, created_at, updated_at

-- Verify the simplified structure
-- SELECT column_name, data_type FROM information_schema.columns 
-- WHERE table_name = 'patient_history_analysis' ORDER BY ordinal_position;
