-- Migration: Add linked visits feature
-- This allows visits to be linked to previous visits for follow-up context
-- When a doctor creates a new visit from an old visit, they are linked together

-- Add parent_visit_id column to visits table for linking follow-up visits
ALTER TABLE public.visits 
ADD COLUMN IF NOT EXISTS parent_visit_id bigint REFERENCES public.visits(id),
ADD COLUMN IF NOT EXISTS link_reason text;

-- Add comments for documentation
COMMENT ON COLUMN public.visits.parent_visit_id IS 'Reference to the original/parent visit this is a follow-up for. NULL if this is an independent visit.';
COMMENT ON COLUMN public.visits.link_reason IS 'Reason for linking to parent visit (e.g., "Follow-up for treatment", "Recurring symptoms", "Test results review")';

-- Create index for efficient querying of linked visits
CREATE INDEX IF NOT EXISTS idx_visits_parent_visit_id 
ON public.visits(parent_visit_id) 
WHERE parent_visit_id IS NOT NULL;

-- Create index for finding all follow-up visits for a patient
CREATE INDEX IF NOT EXISTS idx_visits_patient_parent 
ON public.visits(patient_id, parent_visit_id);

-- Create a function to get the visit chain (all linked visits)
CREATE OR REPLACE FUNCTION get_visit_chain(p_visit_id bigint)
RETURNS TABLE (
    visit_id bigint,
    parent_visit_id bigint,
    visit_date date,
    visit_type text,
    chief_complaint text,
    diagnosis text,
    chain_level int
) AS $$
WITH RECURSIVE visit_chain AS (
    -- Start with the given visit and find its root
    SELECT 
        v.id as visit_id,
        v.parent_visit_id,
        v.visit_date,
        v.visit_type,
        v.chief_complaint,
        v.diagnosis,
        0 as chain_level
    FROM visits v
    WHERE v.id = p_visit_id
    
    UNION ALL
    
    -- Find parent visits (going up the chain)
    SELECT 
        v.id,
        v.parent_visit_id,
        v.visit_date,
        v.visit_type,
        v.chief_complaint,
        v.diagnosis,
        vc.chain_level - 1
    FROM visits v
    INNER JOIN visit_chain vc ON v.id = vc.parent_visit_id
)
SELECT * FROM visit_chain
ORDER BY chain_level;
$$ LANGUAGE SQL;

-- Create a function to get all child visits (follow-ups) for a visit
CREATE OR REPLACE FUNCTION get_follow_up_visits(p_visit_id bigint)
RETURNS TABLE (
    visit_id bigint,
    parent_visit_id bigint,
    visit_date date,
    visit_type text,
    chief_complaint text,
    diagnosis text,
    link_reason text,
    created_at timestamptz
) AS $$
SELECT 
    v.id as visit_id,
    v.parent_visit_id,
    v.visit_date,
    v.visit_type,
    v.chief_complaint,
    v.diagnosis,
    v.link_reason,
    v.created_at
FROM visits v
WHERE v.parent_visit_id = p_visit_id
ORDER BY v.visit_date DESC, v.created_at DESC;
$$ LANGUAGE SQL;

-- Analyze the table for query optimization
ANALYZE public.visits;
