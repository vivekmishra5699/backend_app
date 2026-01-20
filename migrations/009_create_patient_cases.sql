-- Migration: 009_create_patient_cases.sql
-- Description: Create patient_cases table for case/episode of care tracking
-- Date: 2026-01-18

-- ============================================================
-- PATIENT CASES TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS patient_cases (
    id BIGSERIAL PRIMARY KEY,
    patient_id BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid),
    
    -- Case Identification
    case_number TEXT NOT NULL,  -- Auto-generated: "CASE-2026-0001"
    case_title TEXT NOT NULL,   -- "Skin Rash - Right Arm"
    case_type TEXT NOT NULL DEFAULT 'acute' 
        CHECK (case_type IN ('acute', 'chronic', 'preventive', 'procedure', 'other')),
    
    -- Medical Details
    chief_complaint TEXT NOT NULL,
    initial_diagnosis TEXT,
    final_diagnosis TEXT,
    icd10_codes JSONB DEFAULT '[]',
    body_parts_affected JSONB DEFAULT '[]',  -- ['right_arm', 'chest']
    
    -- Status & Severity
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'resolved', 'ongoing', 'referred', 'closed', 'on_hold')),
    severity TEXT DEFAULT 'moderate'
        CHECK (severity IN ('mild', 'moderate', 'severe', 'critical')),
    priority INTEGER DEFAULT 2 CHECK (priority BETWEEN 1 AND 5),  -- 1=highest
    
    -- Timeline
    started_at DATE NOT NULL DEFAULT CURRENT_DATE,
    resolved_at DATE,
    expected_resolution_date DATE,
    last_visit_date DATE,
    next_follow_up_date DATE,
    
    -- Outcome Tracking
    outcome TEXT CHECK (outcome IN (
        'fully_resolved', 'significantly_improved', 'partially_improved', 
        'unchanged', 'worsened', 'referred', 'patient_discontinued', NULL
    )),
    outcome_notes TEXT,
    patient_satisfaction INTEGER CHECK (patient_satisfaction IS NULL OR patient_satisfaction BETWEEN 1 AND 5),
    
    -- Treatment Summary (auto-updated via triggers)
    total_visits INTEGER DEFAULT 0,
    total_reports INTEGER DEFAULT 0,
    total_photos INTEGER DEFAULT 0,
    medications_prescribed JSONB DEFAULT '[]',
    treatments_given JSONB DEFAULT '[]',
    
    -- AI Analysis Reference (FK added after ai_case_analysis table creation)
    latest_ai_analysis_id BIGINT,
    ai_summary TEXT,
    ai_treatment_effectiveness NUMERIC(3,2) CHECK (ai_treatment_effectiveness IS NULL OR ai_treatment_effectiveness BETWEEN 0 AND 1),
    
    -- Metadata
    tags JSONB DEFAULT '[]',  -- ['dermatology', 'allergic', 'recurring']
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Unique case number per doctor
    UNIQUE (doctor_firebase_uid, case_number)
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_cases_patient_doctor ON patient_cases(patient_id, doctor_firebase_uid);
CREATE INDEX IF NOT EXISTS idx_cases_status ON patient_cases(doctor_firebase_uid, status);
CREATE INDEX IF NOT EXISTS idx_cases_type ON patient_cases(doctor_firebase_uid, case_type);
CREATE INDEX IF NOT EXISTS idx_cases_started ON patient_cases(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_cases_last_visit ON patient_cases(last_visit_date DESC);

-- ============================================================
-- CASE NUMBER GENERATION FUNCTION
-- ============================================================

CREATE OR REPLACE FUNCTION generate_case_number()
RETURNS TRIGGER AS $$
DECLARE
    year_part TEXT;
    seq_num INTEGER;
BEGIN
    year_part := to_char(CURRENT_DATE, 'YYYY');
    
    SELECT COALESCE(MAX(
        CAST(SUBSTRING(case_number FROM 'CASE-\d{4}-(\d+)') AS INTEGER)
    ), 0) + 1
    INTO seq_num
    FROM patient_cases
    WHERE doctor_firebase_uid = NEW.doctor_firebase_uid
    AND case_number LIKE 'CASE-' || year_part || '-%';
    
    NEW.case_number := 'CASE-' || year_part || '-' || LPAD(seq_num::TEXT, 4, '0');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-generate case number
DROP TRIGGER IF EXISTS set_case_number ON patient_cases;
CREATE TRIGGER set_case_number
    BEFORE INSERT ON patient_cases
    FOR EACH ROW
    WHEN (NEW.case_number IS NULL)
    EXECUTE FUNCTION generate_case_number();

-- ============================================================
-- UPDATED_AT TRIGGER
-- ============================================================

CREATE OR REPLACE FUNCTION update_patient_cases_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_patient_cases_updated_at ON patient_cases;
CREATE TRIGGER trigger_patient_cases_updated_at
    BEFORE UPDATE ON patient_cases
    FOR EACH ROW
    EXECUTE FUNCTION update_patient_cases_updated_at();

-- ============================================================
-- COMMENTS
-- ============================================================

COMMENT ON TABLE patient_cases IS 'Tracks medical cases/episodes of care for patients. Each case represents a distinct medical problem being treated.';
COMMENT ON COLUMN patient_cases.case_number IS 'Auto-generated unique case identifier per doctor (CASE-YYYY-NNNN)';
COMMENT ON COLUMN patient_cases.case_type IS 'Type of case: acute (short-term), chronic (ongoing), preventive, procedure, other';
COMMENT ON COLUMN patient_cases.status IS 'Current status: active, resolved, ongoing (chronic), referred, closed, on_hold';
COMMENT ON COLUMN patient_cases.outcome IS 'Final outcome when case is resolved';
