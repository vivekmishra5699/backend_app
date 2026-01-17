-- Migration: 002_add_structured_data_column.sql
-- Purpose: Add structured_data JSONB column to ai_document_analysis
-- Date: January 17, 2026
-- Part of Phase 1: Foundation Fixes (1.4 Simplify Document Analysis Table)

-- ============================================================================
-- ADD STRUCTURED DATA COLUMN
-- This column will store the JSON output from Gemini instead of 
-- parsing into separate text columns
-- ============================================================================

-- Add the new JSONB column for structured AI output
ALTER TABLE ai_document_analysis 
ADD COLUMN IF NOT EXISTS structured_data JSONB;

-- Add index for JSONB queries (GIN index for efficient JSON operations)
CREATE INDEX IF NOT EXISTS idx_ai_analysis_structured_data 
    ON ai_document_analysis USING GIN (structured_data);

-- Add index for finding critical findings quickly
CREATE INDEX IF NOT EXISTS idx_ai_analysis_critical_findings 
    ON ai_document_analysis USING GIN ((structured_data -> 'critical_findings'));

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON COLUMN ai_document_analysis.structured_data IS 'Structured JSON output from AI analysis containing findings, critical_findings, treatment_evaluation, etc.';

-- ============================================================================
-- NOTE: The following columns are now DEPRECATED but kept for backward 
-- compatibility. They will be removed in a future migration after all
-- analyses use structured_data.
-- 
-- Deprecated columns:
--   - document_summary (use structured_data->>'document_summary')
--   - clinical_significance (use structured_data->'clinical_correlation')
--   - correlation_with_patient (use structured_data->'clinical_correlation'->>'relevance_to_complaint')
--   - actionable_insights (use structured_data->'actionable_insights')
--   - patient_communication (use structured_data->'patient_communication')
--   - clinical_notes (use structured_data->>'clinical_notes')
--   - clinical_correlation (use structured_data->'clinical_correlation')
--   - detailed_findings (use structured_data->'findings')
--   - critical_findings (use structured_data->'critical_findings')
--   - treatment_evaluation (use structured_data->'treatment_evaluation')
-- ============================================================================

-- Create a view for easy access to structured data fields
CREATE OR REPLACE VIEW v_ai_analysis_structured AS
SELECT 
    id,
    report_id,
    visit_id,
    patient_id,
    doctor_firebase_uid,
    analysis_type,
    model_used,
    confidence_score,
    
    -- Extract from structured_data if available, fall back to legacy columns
    COALESCE(
        structured_data->>'document_summary',
        document_summary
    ) as document_summary,
    
    COALESCE(
        structured_data->>'document_type',
        'unknown'
    ) as document_type,
    
    structured_data->'findings' as findings,
    structured_data->'critical_findings' as critical_findings,
    structured_data->'clinical_correlation' as clinical_correlation,
    structured_data->'treatment_evaluation' as treatment_evaluation,
    structured_data->'actionable_insights' as actionable_insights,
    structured_data->'patient_communication' as patient_communication,
    structured_data->'follow_up_recommendations' as follow_up_recommendations,
    
    -- Check if using new structured format
    (structured_data IS NOT NULL) as is_structured_format,
    
    analysis_success,
    analysis_error,
    processing_time_ms,
    analyzed_at,
    created_at,
    updated_at
FROM ai_document_analysis;

COMMENT ON VIEW v_ai_analysis_structured IS 'View providing unified access to AI analysis data regardless of whether it uses legacy text columns or new structured_data JSONB';
