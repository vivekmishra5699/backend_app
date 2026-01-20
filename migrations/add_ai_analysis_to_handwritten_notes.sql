-- Migration: Add AI analysis columns to handwritten_visit_notes table
-- This allows storing AI analysis results for handwritten prescription PDFs
-- The AI uses Gemini 3 Pro's multimodal capabilities to read and interpret handwriting

-- Add AI analysis columns to handwritten_visit_notes
ALTER TABLE public.handwritten_visit_notes 
ADD COLUMN IF NOT EXISTS ai_analysis_raw text,
ADD COLUMN IF NOT EXISTS ai_analysis_confidence numeric DEFAULT 0.0 CHECK (ai_analysis_confidence >= 0.0 AND ai_analysis_confidence <= 1.0),
ADD COLUMN IF NOT EXISTS ai_analysis_at timestamp with time zone,
ADD COLUMN IF NOT EXISTS ai_extracted_diagnosis text,
ADD COLUMN IF NOT EXISTS ai_extracted_medications jsonb DEFAULT '[]'::jsonb,
ADD COLUMN IF NOT EXISTS ai_legibility_score integer DEFAULT 7 CHECK (ai_legibility_score >= 1 AND ai_legibility_score <= 10);

-- Add comments for documentation
COMMENT ON COLUMN public.handwritten_visit_notes.ai_analysis_raw IS 'Raw AI analysis text from Gemini 3 Pro interpretation of handwritten prescription';
COMMENT ON COLUMN public.handwritten_visit_notes.ai_analysis_confidence IS 'Confidence score of the AI analysis (0.0 to 1.0)';
COMMENT ON COLUMN public.handwritten_visit_notes.ai_analysis_at IS 'Timestamp when AI analysis was performed';
COMMENT ON COLUMN public.handwritten_visit_notes.ai_extracted_diagnosis IS 'Diagnosis extracted from handwritten notes by AI';
COMMENT ON COLUMN public.handwritten_visit_notes.ai_extracted_medications IS 'Medications extracted from handwritten prescription as JSON array';
COMMENT ON COLUMN public.handwritten_visit_notes.ai_legibility_score IS 'AI assessment of handwriting legibility (1-10 scale)';

-- Create index for efficient querying of analyzed notes
CREATE INDEX IF NOT EXISTS idx_handwritten_notes_ai_analyzed 
ON public.handwritten_visit_notes(doctor_firebase_uid, ai_analysis_at DESC) 
WHERE ai_analysis_at IS NOT NULL;

-- Update table comment
COMMENT ON TABLE public.handwritten_visit_notes IS 'Handwritten visit notes/prescriptions with AI-powered analysis for extracting and interpreting handwritten medical content';

-- Analyze the table for query optimization
ANALYZE public.handwritten_visit_notes;
