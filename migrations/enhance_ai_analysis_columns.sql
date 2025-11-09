-- Migration: Enhance AI Document Analysis with Visit-Context Columns
-- Date: 2025-11-09
-- Description: Add new columns to store enhanced visit-contextual AI analysis

-- Add new columns for enhanced visit-contextual analysis
ALTER TABLE public.ai_document_analysis 
ADD COLUMN IF NOT EXISTS clinical_correlation text,
ADD COLUMN IF NOT EXISTS detailed_findings text,
ADD COLUMN IF NOT EXISTS critical_findings text,
ADD COLUMN IF NOT EXISTS treatment_evaluation text;

-- Add comment for documentation
COMMENT ON COLUMN public.ai_document_analysis.clinical_correlation IS 'Detailed correlation between report findings and visit context (chief complaint, symptoms, diagnosis)';
COMMENT ON COLUMN public.ai_document_analysis.detailed_findings IS 'Comprehensive breakdown of all findings with clinical significance';
COMMENT ON COLUMN public.ai_document_analysis.critical_findings IS 'Critical and urgent findings requiring immediate attention';
COMMENT ON COLUMN public.ai_document_analysis.treatment_evaluation IS 'Evaluation of current treatment plan based on report findings';

-- Create index for faster retrieval of critical findings
CREATE INDEX IF NOT EXISTS idx_ai_analysis_critical_findings 
ON public.ai_document_analysis USING gin (to_tsvector('english', critical_findings))
WHERE critical_findings IS NOT NULL AND critical_findings != '';

-- Add index for better performance on visit-based queries
CREATE INDEX IF NOT EXISTS idx_ai_analysis_visit_doctor 
ON public.ai_document_analysis (visit_id, doctor_firebase_uid, analyzed_at DESC);

COMMENT ON TABLE public.ai_document_analysis IS 'AI-powered document analysis with enhanced visit-contextual intelligence';
