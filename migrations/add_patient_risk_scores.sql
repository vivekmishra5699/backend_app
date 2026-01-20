-- Migration: add_patient_risk_scores.sql
-- Phase 2.4: Clinical Intelligence - Patient Risk Scoring
-- Created: January 17, 2026
--
-- This table stores AI-calculated risk scores for patients,
-- enabling quick triage and identification of high-risk patients.

-- Create patient_risk_scores table
CREATE TABLE IF NOT EXISTS patient_risk_scores (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid) ON DELETE CASCADE,
    
    -- Risk scores (0-100, where 100 is highest risk)
    overall_risk_score INTEGER CHECK (overall_risk_score >= 0 AND overall_risk_score <= 100),
    cardiovascular_risk INTEGER CHECK (cardiovascular_risk >= 0 AND cardiovascular_risk <= 100),
    diabetes_risk INTEGER CHECK (diabetes_risk >= 0 AND diabetes_risk <= 100),
    kidney_risk INTEGER CHECK (kidney_risk >= 0 AND kidney_risk <= 100),
    liver_risk INTEGER CHECK (liver_risk >= 0 AND liver_risk <= 100),
    respiratory_risk INTEGER CHECK (respiratory_risk >= 0 AND respiratory_risk <= 100),
    
    -- Risk factors identified by AI
    risk_factors JSONB DEFAULT '[]'::jsonb,
    -- Protective factors (positive health indicators)
    protective_factors JSONB DEFAULT '[]'::jsonb,
    
    -- AI-generated recommendations
    recommendations JSONB DEFAULT '[]'::jsonb,
    
    -- Analysis metadata
    data_points_used INTEGER DEFAULT 0,
    visits_analyzed INTEGER DEFAULT 0,
    reports_analyzed INTEGER DEFAULT 0,
    confidence_score NUMERIC(3,2) CHECK (confidence_score >= 0 AND confidence_score <= 1),
    
    -- AI reasoning/explanation
    analysis_summary TEXT,
    
    -- Timestamps
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure one risk score per patient per doctor
    UNIQUE(patient_id, doctor_firebase_uid)
);

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_risk_scores_doctor ON patient_risk_scores(doctor_firebase_uid);
CREATE INDEX IF NOT EXISTS idx_risk_scores_patient ON patient_risk_scores(patient_id);
CREATE INDEX IF NOT EXISTS idx_risk_scores_overall ON patient_risk_scores(overall_risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_risk_scores_calculated ON patient_risk_scores(calculated_at DESC);

-- Index for finding high-risk patients
CREATE INDEX IF NOT EXISTS idx_risk_scores_high_risk ON patient_risk_scores(doctor_firebase_uid, overall_risk_score DESC)
    WHERE overall_risk_score >= 70;

-- Create visit_summaries table for SOAP notes
CREATE TABLE IF NOT EXISTS visit_summaries (
    id SERIAL PRIMARY KEY,
    visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid) ON DELETE CASCADE,
    
    -- SOAP Note sections (stored as JSONB for flexibility)
    subjective JSONB,
    objective JSONB,
    assessment JSONB,
    plan JSONB,
    
    -- Full SOAP note as text for display
    soap_note_text TEXT,
    
    -- Coding information
    icd10_codes JSONB DEFAULT '[]'::jsonb,
    cpt_codes JSONB DEFAULT '[]'::jsonb,
    
    -- Generation metadata
    ai_generated BOOLEAN DEFAULT TRUE,
    manually_edited BOOLEAN DEFAULT FALSE,
    approved BOOLEAN DEFAULT FALSE,
    approved_at TIMESTAMP WITH TIME ZONE,
    approved_by TEXT,
    
    -- AI metadata
    confidence_score NUMERIC(3,2),
    model_used VARCHAR(100),
    
    -- Timestamps
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- One summary per visit
    UNIQUE(visit_id)
);

-- Create indexes for visit_summaries
CREATE INDEX IF NOT EXISTS idx_visit_summaries_visit ON visit_summaries(visit_id);
CREATE INDEX IF NOT EXISTS idx_visit_summaries_patient ON visit_summaries(patient_id);
CREATE INDEX IF NOT EXISTS idx_visit_summaries_doctor ON visit_summaries(doctor_firebase_uid);
CREATE INDEX IF NOT EXISTS idx_visit_summaries_generated ON visit_summaries(generated_at DESC);

-- Create historical_lab_values table for trend analysis caching
CREATE TABLE IF NOT EXISTS historical_lab_values (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid) ON DELETE CASCADE,
    analysis_id INTEGER REFERENCES ai_document_analysis(id) ON DELETE CASCADE,
    
    -- Lab value information
    parameter_name VARCHAR(100) NOT NULL,
    parameter_value VARCHAR(100),
    numeric_value NUMERIC,  -- For trend calculations
    unit VARCHAR(50),
    reference_range VARCHAR(100),
    status VARCHAR(50),  -- normal, low, high, critical, etc.
    
    -- Source information
    report_id INTEGER REFERENCES reports(id) ON DELETE SET NULL,
    test_date DATE,
    
    -- Timestamps
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for historical_lab_values
CREATE INDEX IF NOT EXISTS idx_historical_labs_patient ON historical_lab_values(patient_id, doctor_firebase_uid);
CREATE INDEX IF NOT EXISTS idx_historical_labs_parameter ON historical_lab_values(patient_id, parameter_name, test_date DESC);
CREATE INDEX IF NOT EXISTS idx_historical_labs_date ON historical_lab_values(test_date DESC);

-- Add trigger to update updated_at on patient_risk_scores
CREATE OR REPLACE FUNCTION update_risk_scores_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_risk_scores_updated_at ON patient_risk_scores;
CREATE TRIGGER trigger_risk_scores_updated_at
    BEFORE UPDATE ON patient_risk_scores
    FOR EACH ROW
    EXECUTE FUNCTION update_risk_scores_updated_at();

-- Add trigger to update updated_at on visit_summaries
DROP TRIGGER IF EXISTS trigger_visit_summaries_updated_at ON visit_summaries;
CREATE TRIGGER trigger_visit_summaries_updated_at
    BEFORE UPDATE ON visit_summaries
    FOR EACH ROW
    EXECUTE FUNCTION update_risk_scores_updated_at();

-- Grant permissions (adjust based on your Supabase setup)
-- GRANT ALL ON patient_risk_scores TO authenticated;
-- GRANT ALL ON visit_summaries TO authenticated;
-- GRANT ALL ON historical_lab_values TO authenticated;

COMMENT ON TABLE patient_risk_scores IS 'AI-calculated patient risk scores for quick triage and identification of high-risk patients';
COMMENT ON TABLE visit_summaries IS 'AI-generated SOAP notes for visit documentation';
COMMENT ON TABLE historical_lab_values IS 'Cached historical lab values for trend analysis';
