-- Migration: 001_add_clinical_alerts.sql
-- Purpose: Add clinical alerts system for critical findings
-- Date: January 17, 2026
-- Part of Phase 1: Foundation Fixes

-- ============================================================================
-- CLINICAL ALERTS TABLE
-- Stores alerts generated from AI analyses for critical findings
-- ============================================================================

CREATE TABLE IF NOT EXISTS ai_clinical_alerts (
    id SERIAL PRIMARY KEY,
    
    -- Relationships
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    visit_id INTEGER REFERENCES visits(id) ON DELETE SET NULL,
    report_id INTEGER REFERENCES reports(id) ON DELETE SET NULL,
    analysis_id INTEGER REFERENCES ai_document_analysis(id) ON DELETE SET NULL,
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid) ON DELETE CASCADE,
    
    -- Alert Classification
    alert_type VARCHAR(50) NOT NULL CHECK (alert_type IN (
        'critical_value',      -- Lab value outside critical range
        'abnormal_trend',      -- Worsening trend over time
        'drug_interaction',    -- Potential drug interaction
        'allergy_warning',     -- Medication-allergy conflict
        'urgent_followup',     -- Requires urgent follow-up
        'diagnosis_concern',   -- Diagnosis-related concern
        'treatment_alert',     -- Treatment modification needed
        'missed_test'          -- Recommended test not done
    )),
    
    severity VARCHAR(20) NOT NULL CHECK (severity IN (
        'critical',   -- Requires immediate attention
        'urgent',     -- Requires attention within hours
        'high',       -- Requires attention within 24 hours
        'medium',     -- Requires attention within 48 hours
        'low'         -- Routine attention needed
    )),
    
    -- Alert Content
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    
    -- Clinical Context (optional, for lab values)
    parameter_name VARCHAR(100),
    parameter_value VARCHAR(50),
    reference_range VARCHAR(50),
    
    -- Action Details
    recommended_action TEXT,
    
    -- Status Tracking
    is_acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    acknowledged_by TEXT,
    action_taken TEXT,
    is_dismissed BOOLEAN DEFAULT FALSE,
    dismissed_reason TEXT,
    
    -- Metadata
    source VARCHAR(50) DEFAULT 'ai_analysis' CHECK (source IN (
        'ai_analysis',
        'manual',
        'system',
        'medication_check'
    )),
    metadata JSONB DEFAULT '{}'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE  -- Optional expiration
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

-- Fast lookup of unacknowledged alerts for a doctor (most common query)
CREATE INDEX idx_alerts_doctor_unacknowledged 
    ON ai_clinical_alerts(doctor_firebase_uid, is_acknowledged, created_at DESC) 
    WHERE is_acknowledged = FALSE AND is_dismissed = FALSE;

-- Fast lookup by patient
CREATE INDEX idx_alerts_patient 
    ON ai_clinical_alerts(patient_id, created_at DESC);

-- Fast lookup by severity for dashboard badges
CREATE INDEX idx_alerts_severity 
    ON ai_clinical_alerts(doctor_firebase_uid, severity, created_at DESC)
    WHERE is_acknowledged = FALSE AND is_dismissed = FALSE;

-- Fast lookup by visit
CREATE INDEX idx_alerts_visit 
    ON ai_clinical_alerts(visit_id) 
    WHERE visit_id IS NOT NULL;

-- Fast lookup by report
CREATE INDEX idx_alerts_report 
    ON ai_clinical_alerts(report_id) 
    WHERE report_id IS NOT NULL;

-- Alert type filtering
CREATE INDEX idx_alerts_type 
    ON ai_clinical_alerts(doctor_firebase_uid, alert_type, created_at DESC);

-- ============================================================================
-- TRIGGER FOR UPDATED_AT
-- ============================================================================

CREATE OR REPLACE FUNCTION update_alert_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_alert_updated_at
    BEFORE UPDATE ON ai_clinical_alerts
    FOR EACH ROW
    EXECUTE FUNCTION update_alert_updated_at();

-- ============================================================================
-- HELPER FUNCTION: GET ALERT COUNTS BY SEVERITY
-- ============================================================================

CREATE OR REPLACE FUNCTION get_alert_counts(p_doctor_firebase_uid TEXT)
RETURNS TABLE (
    total_count BIGINT,
    critical_count BIGINT,
    urgent_count BIGINT,
    high_count BIGINT,
    medium_count BIGINT,
    low_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*) as total_count,
        COUNT(*) FILTER (WHERE severity = 'critical') as critical_count,
        COUNT(*) FILTER (WHERE severity = 'urgent') as urgent_count,
        COUNT(*) FILTER (WHERE severity = 'high') as high_count,
        COUNT(*) FILTER (WHERE severity = 'medium') as medium_count,
        COUNT(*) FILTER (WHERE severity = 'low') as low_count
    FROM ai_clinical_alerts
    WHERE doctor_firebase_uid = p_doctor_firebase_uid
        AND is_acknowledged = FALSE
        AND is_dismissed = FALSE
        AND (expires_at IS NULL OR expires_at > NOW());
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE ai_clinical_alerts IS 'Stores clinical alerts generated from AI analyses for critical findings requiring doctor attention';
COMMENT ON COLUMN ai_clinical_alerts.severity IS 'Alert severity: critical (immediate), urgent (hours), high (24h), medium (48h), low (routine)';
COMMENT ON COLUMN ai_clinical_alerts.alert_type IS 'Type of alert: critical_value, abnormal_trend, drug_interaction, allergy_warning, urgent_followup, diagnosis_concern, treatment_alert, missed_test';
