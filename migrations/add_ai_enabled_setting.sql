-- Migration: Add AI enabled setting for doctors
-- This allows doctors to turn on/off AI analysis system-wide

-- Add ai_enabled column to doctors table (default true for existing doctors)
ALTER TABLE public.doctors 
ADD COLUMN IF NOT EXISTS ai_enabled boolean DEFAULT true;

-- Add comment for documentation
COMMENT ON COLUMN public.doctors.ai_enabled IS 'Whether AI analysis features are enabled for this doctor. When false, all AI analysis endpoints will return disabled message.';

-- Create index for filtering doctors by AI setting (useful for analytics)
CREATE INDEX IF NOT EXISTS idx_doctors_ai_enabled 
ON public.doctors(ai_enabled);
