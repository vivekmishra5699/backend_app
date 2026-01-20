-- Migration: 011_create_ai_case_analysis.sql
-- Description: Create ai_case_analysis table for case-level AI analysis
-- Date: 2026-01-18

-- ============================================================
-- AI CASE ANALYSIS TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS ai_case_analysis (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL REFERENCES patient_cases(id) ON DELETE CASCADE,
    patient_id BIGINT NOT NULL REFERENCES patients(id),
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid),
    
    -- Analysis Scope
    analysis_type TEXT NOT NULL DEFAULT 'comprehensive'
        CHECK (analysis_type IN ('comprehensive', 'progress_review', 'outcome_assessment', 'photo_comparison')),
    visits_analyzed INTEGER[] DEFAULT '{}',  -- Array of visit IDs included
    reports_analyzed INTEGER[] DEFAULT '{}',  -- Array of report IDs included
    photos_analyzed INTEGER[] DEFAULT '{}',  -- Array of photo IDs included
    
    -- Analysis Period
    analysis_from_date DATE,
    analysis_to_date DATE,
    
    -- AI Model Info
    model_used TEXT NOT NULL DEFAULT 'gemini-2.0-flash',
    confidence_score NUMERIC(3,2) CHECK (confidence_score IS NULL OR confidence_score BETWEEN 0 AND 1),
    processing_time_ms INTEGER,
    
    -- Raw & Structured Output
    raw_analysis TEXT NOT NULL,
    structured_data JSONB,  -- Parsed structured response
    
    -- Case Summary Sections
    case_overview TEXT,
    presenting_complaint_summary TEXT,
    clinical_findings_summary TEXT,
    diagnosis_assessment TEXT,
    
    -- Treatment Analysis
    treatment_timeline JSONB,  -- [{date, treatment, response}]
    treatment_effectiveness TEXT,
    treatment_effectiveness_score NUMERIC(3,2) CHECK (treatment_effectiveness_score IS NULL OR treatment_effectiveness_score BETWEEN 0 AND 1),
    medications_analysis JSONB,
    
    -- Progress & Outcome
    progress_assessment TEXT,
    improvement_indicators JSONB,  -- [{indicator, baseline, current, change}]
    photo_comparison_analysis TEXT,
    visual_improvement_score NUMERIC(3,2) CHECK (visual_improvement_score IS NULL OR visual_improvement_score BETWEEN 0 AND 1),
    
    -- Recommendations
    current_status_assessment TEXT,
    recommended_next_steps JSONB,
    follow_up_recommendations TEXT,
    red_flags JSONB DEFAULT '[]',
    
    -- Patient Communication
    patient_friendly_summary TEXT,
    
    -- Metadata
    analysis_success BOOLEAN DEFAULT TRUE,
    analysis_error TEXT,
    analyzed_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_case_analysis_case ON ai_case_analysis(case_id);
CREATE INDEX IF NOT EXISTS idx_case_analysis_doctor ON ai_case_analysis(doctor_firebase_uid);
CREATE INDEX IF NOT EXISTS idx_case_analysis_type ON ai_case_analysis(analysis_type);
CREATE INDEX IF NOT EXISTS idx_case_analysis_date ON ai_case_analysis(analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_analysis_patient ON ai_case_analysis(patient_id);

-- ============================================================
-- ADD FK FROM PATIENT_CASES TO LATEST ANALYSIS
-- ============================================================

-- Add foreign key constraint to patient_cases for latest_ai_analysis_id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'fk_cases_latest_analysis' 
        AND table_name = 'patient_cases'
    ) THEN
        ALTER TABLE patient_cases 
            ADD CONSTRAINT fk_cases_latest_analysis 
            FOREIGN KEY (latest_ai_analysis_id) 
            REFERENCES ai_case_analysis(id)
            ON DELETE SET NULL;
    END IF;
END $$;

-- ============================================================
-- UPDATED_AT TRIGGER
-- ============================================================

CREATE OR REPLACE FUNCTION update_ai_case_analysis_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_ai_case_analysis_updated_at ON ai_case_analysis;
CREATE TRIGGER trigger_ai_case_analysis_updated_at
    BEFORE UPDATE ON ai_case_analysis
    FOR EACH ROW
    EXECUTE FUNCTION update_ai_case_analysis_updated_at();

-- ============================================================
-- COMMENTS
-- ============================================================

COMMENT ON TABLE ai_case_analysis IS 'Stores AI-generated analysis for medical cases, including treatment effectiveness and progress assessment';
COMMENT ON COLUMN ai_case_analysis.analysis_type IS 'Type of analysis: comprehensive (full case), progress_review (interim), outcome_assessment (final), photo_comparison (visual only)';
COMMENT ON COLUMN ai_case_analysis.treatment_effectiveness_score IS 'AI-calculated treatment effectiveness from 0 (ineffective) to 1 (fully effective)';
COMMENT ON COLUMN ai_case_analysis.visual_improvement_score IS 'AI-calculated visual improvement from photos, 0 to 1';
COMMENT ON COLUMN ai_case_analysis.red_flags IS 'Array of concerning findings that need immediate attention';
