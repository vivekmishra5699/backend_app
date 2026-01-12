-- Migration: Add detailed prior medical history columns to patients table
-- Description: Enhances patient medical history tracking to capture information about 
--              previous doctor consultations, medications, symptoms, diagnosis, etc.
-- Date: 2026-01-09

-- =====================================================
-- ADD PRIOR MEDICAL HISTORY COLUMNS TO PATIENTS TABLE
-- =====================================================

-- Whether patient has consulted another doctor before
ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS consulted_other_doctor boolean DEFAULT false;

-- Information about the previous doctor
ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS previous_doctor_name text;

ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS previous_doctor_specialization text;

ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS previous_clinic_hospital text;

-- Date of previous consultation
ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS previous_consultation_date date;

-- Clinical information from previous consultation
ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS previous_symptoms text;

ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS previous_diagnosis text;

-- Previous medications as JSONB array for flexibility
ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS previous_medications jsonb DEFAULT '[]'::jsonb;

ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS previous_medications_duration text;

-- How patient responded to previous treatment
ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS medication_response text 
CHECK (medication_response IS NULL OR medication_response = ANY (ARRAY['improved', 'partial improvement', 'no change', 'worsened']::text[]));

-- Previous tests information
ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS previous_tests_done text;

ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS previous_test_results text;

-- Why patient is seeking new consultation
ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS reason_for_new_consultation text;

-- Current ongoing treatment information
ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS ongoing_treatment boolean DEFAULT false;

ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS current_medications jsonb DEFAULT '[]'::jsonb;

-- =====================================================
-- CREATE INDEXES FOR COMMONLY QUERIED FIELDS
-- =====================================================

-- Index for filtering patients who consulted other doctors
CREATE INDEX IF NOT EXISTS idx_patients_consulted_other_doctor 
ON public.patients(consulted_other_doctor) 
WHERE consulted_other_doctor = true;

-- Index for patients with ongoing treatment
CREATE INDEX IF NOT EXISTS idx_patients_ongoing_treatment 
ON public.patients(ongoing_treatment) 
WHERE ongoing_treatment = true;

-- =====================================================
-- COMMENTS FOR DOCUMENTATION
-- =====================================================

COMMENT ON COLUMN public.patients.consulted_other_doctor IS 'Whether patient has previously consulted another doctor for current condition';
COMMENT ON COLUMN public.patients.previous_doctor_name IS 'Name of the previous doctor consulted';
COMMENT ON COLUMN public.patients.previous_doctor_specialization IS 'Specialization of the previous doctor';
COMMENT ON COLUMN public.patients.previous_clinic_hospital IS 'Name of the clinic or hospital where patient was previously seen';
COMMENT ON COLUMN public.patients.previous_consultation_date IS 'Date of previous consultation';
COMMENT ON COLUMN public.patients.previous_symptoms IS 'Symptoms patient presented with at previous consultation';
COMMENT ON COLUMN public.patients.previous_diagnosis IS 'Diagnosis given by the previous doctor';
COMMENT ON COLUMN public.patients.previous_medications IS 'JSON array of medications prescribed by previous doctor';
COMMENT ON COLUMN public.patients.previous_medications_duration IS 'Duration for which previous medications were prescribed (e.g., 7 days, 2 weeks)';
COMMENT ON COLUMN public.patients.medication_response IS 'Patient response to previous medications: improved, partial improvement, no change, worsened';
COMMENT ON COLUMN public.patients.previous_tests_done IS 'Tests performed during previous consultation';
COMMENT ON COLUMN public.patients.previous_test_results IS 'Results of tests from previous consultation';
COMMENT ON COLUMN public.patients.reason_for_new_consultation IS 'Reason why patient is seeking new consultation (no improvement, second opinion, etc.)';
COMMENT ON COLUMN public.patients.ongoing_treatment IS 'Whether patient is currently on any ongoing treatment';
COMMENT ON COLUMN public.patients.current_medications IS 'JSON array of medications patient is currently taking';

-- =====================================================
-- VERIFICATION QUERY (Run after migration)
-- =====================================================
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns 
-- WHERE table_name = 'patients' 
-- AND column_name LIKE 'previous_%' 
-- OR column_name IN ('consulted_other_doctor', 'medication_response', 'ongoing_treatment', 'current_medications', 'reason_for_new_consultation')
-- ORDER BY ordinal_position;
