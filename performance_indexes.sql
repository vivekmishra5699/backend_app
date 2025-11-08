-- Performance Optimization Indexes
-- Run these queries on your Supabase database to improve query performance

-- ============================================
-- DOCTORS TABLE INDEXES
-- ============================================

-- Index for hospital-based queries (used frequently in frontdesk operations)
CREATE INDEX IF NOT EXISTS idx_doctors_hospital_name 
ON doctors(hospital_name);

-- Index for Firebase UID lookups (used in every authenticated doctor request)
-- Already has UNIQUE constraint, so index exists

-- Composite index for hospital + active status queries
CREATE INDEX IF NOT EXISTS idx_doctors_hospital_active 
ON doctors(hospital_name, firebase_uid) 
WHERE firebase_uid IS NOT NULL;


-- ============================================
-- PATIENTS TABLE INDEXES
-- ============================================

-- Index for created_by_doctor lookups (used to find all patients of a doctor)
CREATE INDEX IF NOT EXISTS idx_patients_created_by_doctor 
ON patients(created_by_doctor);

-- Index for patient ID lookups with doctor
CREATE INDEX IF NOT EXISTS idx_patients_id_doctor 
ON patients(id, created_by_doctor);

-- Index for phone number lookups (if searching patients by phone)
CREATE INDEX IF NOT EXISTS idx_patients_phone 
ON patients(phone);


-- ============================================
-- APPOINTMENTS TABLE INDEXES
-- ============================================

-- Index for doctor + date range queries (most common appointment query)
CREATE INDEX IF NOT EXISTS idx_appointments_doctor_date 
ON appointments(doctor_firebase_uid, appointment_date, appointment_time);

-- Index for appointment status queries (filtering by status)
CREATE INDEX IF NOT EXISTS idx_appointments_status 
ON appointments(status) 
WHERE status != 'cancelled';

-- Index for patient appointments
CREATE INDEX IF NOT EXISTS idx_appointments_patient 
ON appointments(patient_id, appointment_date);

-- Index for frontdesk user appointments
CREATE INDEX IF NOT EXISTS idx_appointments_frontdesk 
ON appointments(frontdesk_user_id, appointment_date);

-- Composite index for conflict checking queries
CREATE INDEX IF NOT EXISTS idx_appointments_conflict_check 
ON appointments(doctor_firebase_uid, appointment_date, status) 
WHERE status != 'cancelled';


-- ============================================
-- FRONTDESK_USERS TABLE INDEXES
-- ============================================

-- Index for username lookups (used in login)
CREATE INDEX IF NOT EXISTS idx_frontdesk_username 
ON frontdesk_users(username) 
WHERE is_active = true;

-- Index for hospital-based frontdesk queries
CREATE INDEX IF NOT EXISTS idx_frontdesk_hospital 
ON frontdesk_users(hospital_name) 
WHERE is_active = true;


-- ============================================
-- VISITS TABLE INDEXES (for AI analysis queries)
-- ============================================

-- Index for patient + doctor visit queries
CREATE INDEX IF NOT EXISTS idx_visits_patient_doctor 
ON visits(patient_id, doctor_firebase_uid, visit_date DESC);

-- Index for doctor's recent visits
CREATE INDEX IF NOT EXISTS idx_visits_doctor_date 
ON visits(doctor_firebase_uid, visit_date DESC);


-- ============================================
-- REPORTS TABLE INDEXES (for lab report queries)
-- ============================================

-- Index for visit reports
CREATE INDEX IF NOT EXISTS idx_reports_visit 
ON reports(visit_id, uploaded_at DESC);

-- Index for patient reports
CREATE INDEX IF NOT EXISTS idx_reports_patient 
ON reports(patient_id, uploaded_at DESC);


-- ============================================
-- AI ANALYSIS QUEUE INDEXES
-- ============================================

-- Index for queue processing (getting pending items)
CREATE INDEX IF NOT EXISTS idx_ai_queue_status_priority 
ON ai_analysis_queue(status, priority, queued_at) 
WHERE status IN ('pending', 'processing');

-- Index for doctor's AI analysis queue
CREATE INDEX IF NOT EXISTS idx_ai_queue_doctor 
ON ai_analysis_queue(doctor_firebase_uid, status, queued_at DESC);


-- ============================================
-- PERFORMANCE STATISTICS
-- ============================================

-- After creating indexes, run ANALYZE to update statistics
ANALYZE doctors;
ANALYZE patients;
ANALYZE appointments;
ANALYZE frontdesk_users;
ANALYZE visits;
ANALYZE reports;
ANALYZE ai_analysis_queue;


-- ============================================
-- QUERY TO CHECK INDEX USAGE
-- ============================================

-- Run this query periodically to see which indexes are being used
SELECT 
    schemaname,
    relname as tablename,
    indexrelname as indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;


-- ============================================
-- QUERY TO CHECK MISSING INDEXES
-- ============================================

-- Run this to identify tables with sequential scans that might benefit from indexes
SELECT 
    schemaname,
    relname as tablename,
    seq_scan as sequential_scans,
    seq_tup_read as rows_read_sequentially,
    idx_scan as index_scans,
    ROUND(100.0 * seq_scan / NULLIF(seq_scan + idx_scan, 0), 2) as sequential_scan_percent
FROM pg_stat_user_tables
WHERE schemaname = 'public'
  AND seq_scan > 0
ORDER BY seq_tup_read DESC
LIMIT 10;
