-- Migration: 010_create_case_photos.sql
-- Description: Create case_photos table for before/progress/after photo tracking
-- Date: 2026-01-18

-- ============================================================
-- CASE PHOTOS TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS case_photos (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL REFERENCES patient_cases(id) ON DELETE CASCADE,
    visit_id BIGINT REFERENCES visits(id) ON DELETE SET NULL,
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid),
    
    -- Photo Classification
    photo_type TEXT NOT NULL CHECK (photo_type IN ('before', 'progress', 'after')),
    sequence_number INTEGER DEFAULT 1,  -- For ordering multiple photos of same type
    
    -- File Details
    file_name TEXT NOT NULL,
    file_url TEXT NOT NULL,
    file_size BIGINT,
    file_type TEXT,  -- 'image/jpeg', 'image/png'
    storage_path TEXT,
    thumbnail_url TEXT,  -- Auto-generated thumbnail for quick loading
    
    -- Medical Context
    body_part TEXT,  -- 'right_arm', 'face_front', 'back', etc.
    body_part_detail TEXT,  -- More specific: 'upper right arm, lateral view'
    description TEXT,
    clinical_notes TEXT,
    
    -- Timestamps
    photo_taken_at TIMESTAMPTZ,  -- When the photo was actually taken
    uploaded_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Comparison Flags
    is_primary BOOLEAN DEFAULT FALSE,  -- Primary photo for before/after comparison
    comparison_pair_id BIGINT REFERENCES case_photos(id) ON DELETE SET NULL,  -- Links before to its after
    
    -- AI Analysis
    ai_detected_changes TEXT,  -- AI description of changes from before
    ai_improvement_score NUMERIC(3,2) CHECK (ai_improvement_score IS NULL OR ai_improvement_score BETWEEN 0 AND 1),
    
    -- Metadata
    metadata JSONB DEFAULT '{}',  -- Camera info, dimensions, etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_photos_case ON case_photos(case_id, photo_type);
CREATE INDEX IF NOT EXISTS idx_photos_visit ON case_photos(visit_id) WHERE visit_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_photos_doctor ON case_photos(doctor_firebase_uid);
CREATE INDEX IF NOT EXISTS idx_photos_primary ON case_photos(case_id, is_primary) WHERE is_primary = TRUE;

-- ============================================================
-- ENSURE ONLY ONE PRIMARY PER TYPE PER CASE
-- ============================================================

-- This partial unique index ensures only one primary photo per photo_type per case
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_primary_per_type 
    ON case_photos(case_id, photo_type) 
    WHERE is_primary = TRUE;

-- ============================================================
-- TRIGGER TO UPDATE CASE PHOTO COUNT
-- ============================================================

CREATE OR REPLACE FUNCTION update_case_photo_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE patient_cases SET
            total_photos = (SELECT COUNT(*) FROM case_photos WHERE case_id = NEW.case_id),
            updated_at = NOW()
        WHERE id = NEW.case_id;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE patient_cases SET
            total_photos = (SELECT COUNT(*) FROM case_photos WHERE case_id = OLD.case_id),
            updated_at = NOW()
        WHERE id = OLD.case_id;
    ELSIF TG_OP = 'UPDATE' AND OLD.case_id != NEW.case_id THEN
        -- Photo moved to different case
        UPDATE patient_cases SET
            total_photos = (SELECT COUNT(*) FROM case_photos WHERE case_id = OLD.case_id),
            updated_at = NOW()
        WHERE id = OLD.case_id;
        UPDATE patient_cases SET
            total_photos = (SELECT COUNT(*) FROM case_photos WHERE case_id = NEW.case_id),
            updated_at = NOW()
        WHERE id = NEW.case_id;
    END IF;
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_case_photo_stats ON case_photos;
CREATE TRIGGER trigger_update_case_photo_stats
    AFTER INSERT OR UPDATE OR DELETE ON case_photos
    FOR EACH ROW
    EXECUTE FUNCTION update_case_photo_stats();

-- ============================================================
-- COMMENTS
-- ============================================================

COMMENT ON TABLE case_photos IS 'Stores before/progress/after photos for medical cases to track visual progress';
COMMENT ON COLUMN case_photos.photo_type IS 'Type of photo: before (initial), progress (intermediate), after (resolution)';
COMMENT ON COLUMN case_photos.is_primary IS 'Primary photo used for before/after comparison display';
COMMENT ON COLUMN case_photos.comparison_pair_id IS 'Links a before photo to its corresponding after photo for comparison';
COMMENT ON COLUMN case_photos.ai_improvement_score IS 'AI-calculated improvement score from 0 (no improvement) to 1 (fully resolved)';
