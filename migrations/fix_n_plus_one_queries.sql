-- SQL Functions to Fix N+1 Query Problems
-- Execute this on your Supabase database to optimize performance

-- ============================================
-- 1. Function to get doctors with patient counts (single query)
-- ============================================
CREATE OR REPLACE FUNCTION get_doctors_with_patient_counts(hospital_name_param TEXT)
RETURNS TABLE (
    id INTEGER,
    firebase_uid TEXT,
    email VARCHAR,
    first_name VARCHAR,
    last_name VARCHAR,
    specialization VARCHAR,
    license_number VARCHAR,
    phone VARCHAR,
    hospital_name VARCHAR,
    pathology_lab_name VARCHAR,
    pathology_lab_phone VARCHAR,
    radiology_lab_name VARCHAR,
    radiology_lab_phone VARCHAR,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    patient_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        d.id,
        d.firebase_uid,
        d.email,
        d.first_name,
        d.last_name,
        d.specialization,
        d.license_number,
        d.phone,
        d.hospital_name,
        d.pathology_lab_name,
        d.pathology_lab_phone,
        d.radiology_lab_name,
        d.radiology_lab_phone,
        d.created_at,
        d.updated_at,
        COALESCE(COUNT(p.id), 0)::BIGINT as patient_count
    FROM doctors d
    LEFT JOIN patients p ON p.created_by_doctor = d.firebase_uid
    WHERE d.hospital_name = hospital_name_param
    GROUP BY d.id, d.firebase_uid, d.email, d.first_name, d.last_name, 
             d.specialization, d.license_number, d.phone, d.hospital_name,
             d.pathology_lab_name, d.pathology_lab_phone, 
             d.radiology_lab_name, d.radiology_lab_phone,
             d.created_at, d.updated_at
    ORDER BY d.created_at DESC;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Grant execute permission to authenticated users
GRANT EXECUTE ON FUNCTION get_doctors_with_patient_counts(TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION get_doctors_with_patient_counts(TEXT) TO anon;


-- ============================================
-- 2. Function to get patients with doctor info (single query)
-- ============================================
CREATE OR REPLACE FUNCTION get_patients_with_doctor_info(hospital_name_param TEXT)
RETURNS TABLE (
    id BIGINT,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    phone TEXT,
    date_of_birth DATE,
    gender TEXT,
    address TEXT,
    emergency_contact_name TEXT,
    emergency_contact_phone TEXT,
    blood_group TEXT,
    allergies TEXT,
    medical_history TEXT,
    created_by_doctor TEXT,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    doctor_first_name VARCHAR,
    doctor_last_name VARCHAR,
    doctor_specialization VARCHAR,
    doctor_phone VARCHAR,
    doctor_name TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.id,
        p.first_name,
        p.last_name,
        p.email,
        p.phone,
        p.date_of_birth,
        p.gender,
        p.address,
        p.emergency_contact_name,
        p.emergency_contact_phone,
        p.blood_group,
        p.allergies,
        p.medical_history,
        p.created_by_doctor,
        p.created_at,
        p.updated_at,
        d.first_name as doctor_first_name,
        d.last_name as doctor_last_name,
        d.specialization as doctor_specialization,
        d.phone as doctor_phone,
        CONCAT(d.first_name, ' ', d.last_name) as doctor_name
    FROM patients p
    INNER JOIN doctors d ON p.created_by_doctor = d.firebase_uid
    WHERE d.hospital_name = hospital_name_param
    ORDER BY p.created_at DESC;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Grant execute permission
GRANT EXECUTE ON FUNCTION get_patients_with_doctor_info(TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION get_patients_with_doctor_info(TEXT) TO anon;


-- ============================================
-- 3. Function to get patient counts by multiple doctors (for caching)
-- ============================================
CREATE OR REPLACE FUNCTION get_patient_counts_by_doctors(doctor_uids TEXT[])
RETURNS TABLE (
    created_by_doctor TEXT,
    count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.created_by_doctor,
        COUNT(p.id)::BIGINT as count
    FROM patients p
    WHERE p.created_by_doctor = ANY(doctor_uids)
    GROUP BY p.created_by_doctor;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Grant execute permission
GRANT EXECUTE ON FUNCTION get_patient_counts_by_doctors(TEXT[]) TO authenticated;
GRANT EXECUTE ON FUNCTION get_patient_counts_by_doctors(TEXT[]) TO anon;


-- ============================================
-- 4. Function for hospital dashboard (ultra-optimized single query)
-- ============================================
CREATE OR REPLACE FUNCTION get_hospital_dashboard_data(hospital_name_param TEXT, recent_limit INTEGER DEFAULT 10)
RETURNS JSON AS $$
DECLARE
    result JSON;
BEGIN
    WITH doctor_counts AS (
        SELECT 
            d.id,
            d.firebase_uid,
            d.email,
            d.first_name,
            d.last_name,
            d.specialization,
            d.license_number,
            d.phone,
            d.hospital_name,
            d.created_at,
            d.updated_at,
            COALESCE(COUNT(p.id), 0)::BIGINT as patient_count
        FROM doctors d
        LEFT JOIN patients p ON p.created_by_doctor = d.firebase_uid
        WHERE d.hospital_name = hospital_name_param
        GROUP BY d.id, d.firebase_uid, d.email, d.first_name, d.last_name,
                 d.specialization, d.license_number, d.phone, d.hospital_name,
                 d.created_at, d.updated_at
    ),
    recent_patients_data AS (
        SELECT 
            p.*,
            d.first_name as doctor_first_name,
            d.last_name as doctor_last_name,
            d.specialization as doctor_specialization,
            d.phone as doctor_phone
        FROM patients p
        INNER JOIN doctors d ON p.created_by_doctor = d.firebase_uid
        WHERE d.hospital_name = hospital_name_param
        ORDER BY p.created_at DESC
        LIMIT recent_limit
    )
    SELECT json_build_object(
        'hospital_name', hospital_name_param,
        'total_doctors', (SELECT COUNT(*) FROM doctor_counts),
        'total_patients', (SELECT SUM(patient_count) FROM doctor_counts),
        'doctors', (SELECT json_agg(row_to_json(doctor_counts.*)) FROM doctor_counts),
        'recent_patients', (SELECT json_agg(row_to_json(recent_patients_data.*)) FROM recent_patients_data)
    ) INTO result;
    
    RETURN result;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Grant execute permission
GRANT EXECUTE ON FUNCTION get_hospital_dashboard_data(TEXT, INTEGER) TO authenticated;
GRANT EXECUTE ON FUNCTION get_hospital_dashboard_data(TEXT, INTEGER) TO anon;


-- ============================================
-- 5. Validate patient belongs to hospital (single query)
-- ============================================
CREATE OR REPLACE FUNCTION validate_patient_in_hospital(patient_id_param BIGINT, hospital_name_param TEXT)
RETURNS BOOLEAN AS $$
DECLARE
    result BOOLEAN;
BEGIN
    SELECT EXISTS(
        SELECT 1
        FROM patients p
        INNER JOIN doctors d ON p.created_by_doctor = d.firebase_uid
        WHERE p.id = patient_id_param
        AND d.hospital_name = hospital_name_param
    ) INTO result;
    
    RETURN result;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Grant execute permission
GRANT EXECUTE ON FUNCTION validate_patient_in_hospital(BIGINT, TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION validate_patient_in_hospital(BIGINT, TEXT) TO anon;


-- ============================================
-- Performance Indexes (if not already created)
-- ============================================

-- Index for hospital-based doctor queries
CREATE INDEX IF NOT EXISTS idx_doctors_hospital_name ON doctors(hospital_name) WHERE hospital_name IS NOT NULL;

-- Index for patient-doctor relationship
CREATE INDEX IF NOT EXISTS idx_patients_created_by_doctor ON patients(created_by_doctor);

-- Composite index for faster joins
CREATE INDEX IF NOT EXISTS idx_patients_doctor_created ON patients(created_by_doctor, created_at DESC);

-- Index for doctor lookups
CREATE INDEX IF NOT EXISTS idx_doctors_firebase_uid_hospital ON doctors(firebase_uid, hospital_name);

-- Update table statistics
ANALYZE doctors;
ANALYZE patients;

-- Verification query to check if functions were created
SELECT 
    routine_name,
    routine_type,
    routine_definition IS NOT NULL as has_definition
FROM information_schema.routines
WHERE routine_schema = 'public'
AND routine_name IN (
    'get_doctors_with_patient_counts',
    'get_patients_with_doctor_info',
    'get_patient_counts_by_doctors',
    'get_hospital_dashboard_data',
    'validate_patient_in_hospital'
)
ORDER BY routine_name;
