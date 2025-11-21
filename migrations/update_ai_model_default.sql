-- Update default model values to Gemini 3.0 Pro (Preview)

ALTER TABLE public.ai_consolidated_analysis 
ALTER COLUMN model_used SET DEFAULT 'gemini-3-pro-preview';

ALTER TABLE public.ai_document_analysis 
ALTER COLUMN model_used SET DEFAULT 'gemini-3-pro-preview';

ALTER TABLE public.patient_history_analysis 
ALTER COLUMN model_used SET DEFAULT 'gemini-3-pro-preview';
