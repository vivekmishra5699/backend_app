-- Migration: Add prescription resolution fields to visits table
-- This allows doctors to mark visits as resolved without sending remote prescription

-- Add prescription status and resolution columns
ALTER TABLE public.visits 
ADD COLUMN IF NOT EXISTS prescription_status text,
ADD COLUMN IF NOT EXISTS prescription_resolution_type text,
ADD COLUMN IF NOT EXISTS prescription_resolution_note text,
ADD COLUMN IF NOT EXISTS prescription_resolved_at timestamptz;

-- Add comments for documentation
COMMENT ON COLUMN public.visits.prescription_status IS 'Status of prescription: null (pending), resolved';
COMMENT ON COLUMN public.visits.prescription_resolution_type IS 'How the visit was resolved: in_person, no_prescription_needed, referred, patient_no_show, other';
COMMENT ON COLUMN public.visits.prescription_resolution_note IS 'Optional note explaining the resolution';
COMMENT ON COLUMN public.visits.prescription_resolved_at IS 'When the visit was marked as resolved';

-- Create index for filtering pending vs resolved visits
CREATE INDEX IF NOT EXISTS idx_visits_prescription_status 
ON public.visits(prescription_status) 
WHERE prescription_status IS NOT NULL;

-- Create index for doctor's pending prescriptions query
CREATE INDEX IF NOT EXISTS idx_visits_doctor_prescription_status 
ON public.visits(doctor_firebase_uid, prescription_status);
