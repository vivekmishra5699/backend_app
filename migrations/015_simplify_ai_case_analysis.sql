-- Migration: 015_simplify_ai_case_analysis.sql
-- Description: Remove redundant columns from ai_case_analysis table
-- The data is already stored in raw_analysis (text) and structured_data (jsonb)
-- Having separate columns for each field is wasteful duplication

-- Step 1: Drop redundant text/jsonb columns that duplicate data in structured_data
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS case_overview;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS presenting_complaint_summary;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS clinical_findings_summary;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS diagnosis_assessment;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS treatment_timeline;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS treatment_effectiveness;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS treatment_effectiveness_score;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS medications_analysis;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS progress_assessment;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS improvement_indicators;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS photo_comparison_analysis;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS visual_improvement_score;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS current_status_assessment;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS recommended_next_steps;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS follow_up_recommendations;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS red_flags;
ALTER TABLE ai_case_analysis DROP COLUMN IF EXISTS patient_friendly_summary;

-- After this migration, the table will only have:
-- id, case_id, patient_id, doctor_firebase_uid, analysis_type, 
-- visits_analyzed, reports_analyzed, photos_analyzed,
-- analysis_from_date, analysis_to_date, model_used, confidence_score, processing_time_ms,
-- raw_analysis (TEXT - stores the raw JSON string),
-- structured_data (JSONB - stores the parsed JSON for querying),
-- analysis_success, analysis_error, analyzed_at, created_at, updated_at

-- NOTE: All individual fields can still be accessed via:
-- structured_data->>'case_overview'
-- structured_data->'diagnosis_assessment'->>'current_diagnosis'
-- etc.

COMMENT ON TABLE ai_case_analysis IS 'Stores AI-generated case analysis. Analysis data is stored in structured_data (JSONB) for querying and raw_analysis (TEXT) for original response.';
