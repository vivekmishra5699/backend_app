-- Migration: Add note_type and prescription_type columns to handwritten_visit_notes
-- This supports remote prescriptions sent from visits

-- Add note_type column to distinguish regular handwritten notes from remote prescriptions
ALTER TABLE public.handwritten_visit_notes 
ADD COLUMN IF NOT EXISTS note_type text DEFAULT 'handwritten';

-- Add prescription_type column for categorizing prescriptions
ALTER TABLE public.handwritten_visit_notes 
ADD COLUMN IF NOT EXISTS prescription_type text;

-- Add comments for documentation
COMMENT ON COLUMN public.handwritten_visit_notes.note_type IS 'Type of note: handwritten, remote_prescription';
COMMENT ON COLUMN public.handwritten_visit_notes.prescription_type IS 'For remote prescriptions: medication, follow_up, report_review, general';

-- Create index for filtering by note type
CREATE INDEX IF NOT EXISTS idx_handwritten_notes_note_type 
ON public.handwritten_visit_notes(note_type);

-- Create index for finding remote prescriptions by visit
CREATE INDEX IF NOT EXISTS idx_handwritten_notes_visit_note_type 
ON public.handwritten_visit_notes(visit_id, note_type);
