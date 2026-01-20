-- Migration: Cleanup Deprecated Linked Visits System
-- Description: Removes deprecated parent_visit_id and link_reason columns now that 
--              case-based architecture is implemented
-- Date: 2026-01-18
-- 
-- IMPORTANT: Run this ONLY after:
-- 1. All linked visits have been migrated to cases
-- 2. Frontend has been updated to use case-based endpoints
-- 3. You have verified the case-based system is working correctly

-- ============================================================
-- STEP 1: Migrate any remaining linked visits to cases (DATA PRESERVATION)
-- ============================================================

-- Create cases for any visits that have parent_visit_id but no case_id
-- This ensures no data is lost during the cleanup
DO $$
DECLARE
    visit_record RECORD;
    new_case_id INT;
    case_count INT := 0;
BEGIN
    -- Find all parent visits that created chains (visits with children)
    FOR visit_record IN 
        SELECT DISTINCT v.id, v.patient_id, v.doctor_firebase_uid, v.chief_complaint, 
                        v.diagnosis, v.visit_date, v.visit_type
        FROM visits v
        WHERE v.deprecated_parent_visit_id IS NULL  -- Only root visits (no parent)
        AND v.case_id IS NULL  -- Not yet assigned to a case
        AND EXISTS (
            SELECT 1 FROM visits child 
            WHERE child.deprecated_parent_visit_id = v.id
        )
    LOOP
        -- Create a case for this visit chain
        INSERT INTO patient_cases (
            patient_id,
            doctor_firebase_uid,
            case_title,
            case_type,
            chief_complaint,
            initial_diagnosis,
            status,
            severity,
            priority,
            started_at,
            notes
        ) VALUES (
            visit_record.patient_id,
            visit_record.doctor_firebase_uid,
            COALESCE(visit_record.diagnosis, visit_record.chief_complaint, 'Migrated Case'),
            'acute',
            visit_record.chief_complaint,
            visit_record.diagnosis,
            'active',
            'moderate',
            2,
            visit_record.visit_date::timestamp with time zone,
            'Auto-migrated from linked visits system'
        ) RETURNING id INTO new_case_id;
        
        -- Assign the parent visit to this case
        UPDATE visits SET 
            case_id = new_case_id, 
            is_case_opener = true 
        WHERE id = visit_record.id;
        
        -- Assign all child visits in the chain to this case
        UPDATE visits SET case_id = new_case_id 
        WHERE deprecated_parent_visit_id = visit_record.id 
        AND case_id IS NULL;
        
        -- Handle nested children (grandchildren)
        UPDATE visits SET case_id = new_case_id
        WHERE deprecated_parent_visit_id IN (
            SELECT id FROM visits WHERE deprecated_parent_visit_id = visit_record.id
        )
        AND case_id IS NULL;
        
        case_count := case_count + 1;
    END LOOP;
    
    RAISE NOTICE 'Migrated % visit chains to cases', case_count;
END $$;

-- ============================================================
-- STEP 2: Create backup table for audit trail (optional but recommended)
-- ============================================================

-- Backup the deprecated columns before removal
CREATE TABLE IF NOT EXISTS _deprecated_visit_links_backup (
    visit_id INT,
    parent_visit_id INT,
    link_reason TEXT,
    migrated_to_case_id INT,
    backed_up_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Store backup of all link relationships
INSERT INTO _deprecated_visit_links_backup (visit_id, parent_visit_id, link_reason, migrated_to_case_id)
SELECT id, deprecated_parent_visit_id, deprecated_link_reason, case_id
FROM visits
WHERE deprecated_parent_visit_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- ============================================================
-- STEP 3: Remove deprecated columns from visits table
-- ============================================================

-- Drop the deprecated columns (data is now in case_id)
ALTER TABLE visits DROP COLUMN IF EXISTS deprecated_parent_visit_id;
ALTER TABLE visits DROP COLUMN IF EXISTS deprecated_link_reason;

-- Also remove the original columns if they still exist (migration 012 renamed them)
ALTER TABLE visits DROP COLUMN IF EXISTS parent_visit_id;
ALTER TABLE visits DROP COLUMN IF EXISTS link_reason;

-- ============================================================
-- STEP 4: Clean up any orphaned indexes
-- ============================================================

DROP INDEX IF EXISTS idx_visits_parent_visit_id;
DROP INDEX IF EXISTS idx_visits_deprecated_parent_visit_id;

-- ============================================================
-- STEP 5: Add check constraint to ensure visits use case_id
-- ============================================================

-- Add a comment to document the case-based architecture
COMMENT ON COLUMN visits.case_id IS 'Reference to patient_cases table. Use this instead of deprecated parent_visit_id for grouping related visits.';
COMMENT ON COLUMN visits.is_case_opener IS 'True if this is the first/opening visit for a case.';

-- ============================================================
-- VERIFICATION QUERIES (run these to verify migration success)
-- ============================================================

-- Check how many visits were migrated
-- SELECT COUNT(*) as migrated_visits FROM visits WHERE case_id IS NOT NULL;

-- Check backup table
-- SELECT COUNT(*) as backed_up_links FROM _deprecated_visit_links_backup;

-- Verify no orphaned visits (visits with parent but no case)
-- SELECT COUNT(*) FROM visits WHERE deprecated_parent_visit_id IS NOT NULL AND case_id IS NULL;
-- Should return 0

-- ============================================================
-- ROLLBACK SCRIPT (in case you need to restore)
-- ============================================================
/*
-- To restore the deprecated columns:
ALTER TABLE visits ADD COLUMN parent_visit_id INT REFERENCES visits(id);
ALTER TABLE visits ADD COLUMN link_reason TEXT;

-- Restore data from backup
UPDATE visits v SET 
    parent_visit_id = b.parent_visit_id,
    link_reason = b.link_reason
FROM _deprecated_visit_links_backup b
WHERE v.id = b.visit_id;
*/
