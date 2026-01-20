-- Migration: 012_modify_tables_for_cases.sql
-- Description: Add case_id to visits, reports, and ai_document_analysis tables. Deprecate linked visits columns.
-- Date: 2026-01-18

-- ============================================================
-- MODIFY VISITS TABLE
-- ============================================================

-- Add case_id column to visits
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'visits' AND column_name = 'case_id'
    ) THEN
        ALTER TABLE visits ADD COLUMN case_id BIGINT REFERENCES patient_cases(id) ON DELETE SET NULL;
    END IF;
END $$;

-- Add is_case_opener flag
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'visits' AND column_name = 'is_case_opener'
    ) THEN
        ALTER TABLE visits ADD COLUMN is_case_opener BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

-- Create index for case lookups
CREATE INDEX IF NOT EXISTS idx_visits_case ON visits(case_id) WHERE case_id IS NOT NULL;

-- Deprecate linked visits columns (rename, don't drop for safety)
DO $$
BEGIN
    -- Rename parent_visit_id if it exists and hasn't been renamed
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'visits' AND column_name = 'parent_visit_id'
    ) THEN
        ALTER TABLE visits RENAME COLUMN parent_visit_id TO deprecated_parent_visit_id;
        COMMENT ON COLUMN visits.deprecated_parent_visit_id IS 'DEPRECATED: Use case_id instead. Will be removed in future migration.';
    END IF;
    
    -- Rename link_reason if it exists and hasn't been renamed
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'visits' AND column_name = 'link_reason'
    ) THEN
        ALTER TABLE visits RENAME COLUMN link_reason TO deprecated_link_reason;
        COMMENT ON COLUMN visits.deprecated_link_reason IS 'DEPRECATED: Use case_id instead. Will be removed in future migration.';
    END IF;
END $$;

-- ============================================================
-- MODIFY REPORTS TABLE
-- ============================================================

-- Add case_id column to reports
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'reports' AND column_name = 'case_id'
    ) THEN
        ALTER TABLE reports ADD COLUMN case_id BIGINT REFERENCES patient_cases(id) ON DELETE SET NULL;
    END IF;
END $$;

-- Create index
CREATE INDEX IF NOT EXISTS idx_reports_case ON reports(case_id) WHERE case_id IS NOT NULL;

-- ============================================================
-- MODIFY AI_DOCUMENT_ANALYSIS TABLE
-- ============================================================

-- Add case_id column to ai_document_analysis
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'ai_document_analysis' AND column_name = 'case_id'
    ) THEN
        ALTER TABLE ai_document_analysis ADD COLUMN case_id BIGINT REFERENCES patient_cases(id) ON DELETE SET NULL;
    END IF;
END $$;

-- Create index
CREATE INDEX IF NOT EXISTS idx_ai_doc_analysis_case ON ai_document_analysis(case_id) WHERE case_id IS NOT NULL;

-- ============================================================
-- MODIFY AI_CLINICAL_ALERTS TABLE
-- ============================================================

-- Add case_id column to ai_clinical_alerts
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'ai_clinical_alerts' AND column_name = 'case_id'
    ) THEN
        ALTER TABLE ai_clinical_alerts ADD COLUMN case_id BIGINT REFERENCES patient_cases(id) ON DELETE SET NULL;
    END IF;
END $$;

-- Create index
CREATE INDEX IF NOT EXISTS idx_alerts_case ON ai_clinical_alerts(case_id) WHERE case_id IS NOT NULL;

-- ============================================================
-- TRIGGER TO UPDATE CASE VISIT STATS
-- ============================================================

CREATE OR REPLACE FUNCTION update_case_visit_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        IF NEW.case_id IS NOT NULL THEN
            UPDATE patient_cases SET
                total_visits = (SELECT COUNT(*) FROM visits WHERE case_id = NEW.case_id),
                last_visit_date = (SELECT MAX(visit_date) FROM visits WHERE case_id = NEW.case_id),
                updated_at = NOW()
            WHERE id = NEW.case_id;
        END IF;
        
        -- Handle case_id change on UPDATE
        IF TG_OP = 'UPDATE' AND OLD.case_id IS NOT NULL AND OLD.case_id IS DISTINCT FROM NEW.case_id THEN
            UPDATE patient_cases SET
                total_visits = (SELECT COUNT(*) FROM visits WHERE case_id = OLD.case_id),
                last_visit_date = (SELECT MAX(visit_date) FROM visits WHERE case_id = OLD.case_id),
                updated_at = NOW()
            WHERE id = OLD.case_id;
        END IF;
    END IF;
    
    IF TG_OP = 'DELETE' AND OLD.case_id IS NOT NULL THEN
        UPDATE patient_cases SET
            total_visits = (SELECT COUNT(*) FROM visits WHERE case_id = OLD.case_id),
            last_visit_date = (SELECT MAX(visit_date) FROM visits WHERE case_id = OLD.case_id),
            updated_at = NOW()
        WHERE id = OLD.case_id;
    END IF;
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_case_visit_stats ON visits;
CREATE TRIGGER trigger_update_case_visit_stats
    AFTER INSERT OR UPDATE OR DELETE ON visits
    FOR EACH ROW
    EXECUTE FUNCTION update_case_visit_stats();

-- ============================================================
-- TRIGGER TO UPDATE CASE REPORT STATS
-- ============================================================

CREATE OR REPLACE FUNCTION update_case_report_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        IF NEW.case_id IS NOT NULL THEN
            UPDATE patient_cases SET
                total_reports = (SELECT COUNT(*) FROM reports WHERE case_id = NEW.case_id),
                updated_at = NOW()
            WHERE id = NEW.case_id;
        END IF;
        
        -- Handle case_id change on UPDATE
        IF TG_OP = 'UPDATE' AND OLD.case_id IS NOT NULL AND OLD.case_id IS DISTINCT FROM NEW.case_id THEN
            UPDATE patient_cases SET
                total_reports = (SELECT COUNT(*) FROM reports WHERE case_id = OLD.case_id),
                updated_at = NOW()
            WHERE id = OLD.case_id;
        END IF;
    END IF;
    
    IF TG_OP = 'DELETE' AND OLD.case_id IS NOT NULL THEN
        UPDATE patient_cases SET
            total_reports = (SELECT COUNT(*) FROM reports WHERE case_id = OLD.case_id),
            updated_at = NOW()
        WHERE id = OLD.case_id;
    END IF;
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_case_report_stats ON reports;
CREATE TRIGGER trigger_update_case_report_stats
    AFTER INSERT OR UPDATE OR DELETE ON reports
    FOR EACH ROW
    EXECUTE FUNCTION update_case_report_stats();

-- ============================================================
-- COMMENTS
-- ============================================================

COMMENT ON COLUMN visits.case_id IS 'Reference to the patient_case this visit belongs to. NULL for quick visits not associated with a case.';
COMMENT ON COLUMN visits.is_case_opener IS 'TRUE if this is the first/opening visit of a case';
COMMENT ON COLUMN reports.case_id IS 'Reference to the patient_case this report belongs to';
COMMENT ON COLUMN ai_document_analysis.case_id IS 'Reference to the patient_case for case-scoped analysis';
