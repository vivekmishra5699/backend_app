-- Fix N+1 query issues with optimized RPC functions

-- 1. Optimize Earnings Report
CREATE OR REPLACE FUNCTION get_doctor_earnings_report(
    p_doctor_uid TEXT,
    p_start_date DATE DEFAULT NULL,
    p_end_date DATE DEFAULT NULL,
    p_payment_status TEXT DEFAULT NULL,
    p_visit_type TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_total_consultations INTEGER;
    v_paid_consultations INTEGER;
    v_unpaid_consultations INTEGER;
    v_total_amount NUMERIC;
    v_paid_amount NUMERIC;
    v_unpaid_amount NUMERIC;
    v_avg_per_consultation NUMERIC;
    v_payment_method_breakdown JSONB;
    v_visit_type_breakdown JSONB;
    v_period TEXT;
BEGIN
    -- Determine period string
    IF p_start_date IS NOT NULL AND p_end_date IS NOT NULL THEN
        v_period := to_char(p_start_date, 'YYYY-MM-DD') || ' to ' || to_char(p_end_date, 'YYYY-MM-DD');
    ELSE
        v_period := 'All Time';
    END IF;

    -- Calculate aggregates
    SELECT
        COUNT(*),
        COUNT(*) FILTER (WHERE payment_status = 'paid'),
        COUNT(*) FILTER (WHERE payment_status = 'unpaid'),
        COALESCE(SUM(total_amount), 0),
        COALESCE(SUM(total_amount) FILTER (WHERE payment_status = 'paid'), 0),
        COALESCE(SUM(total_amount) FILTER (WHERE payment_status = 'unpaid'), 0)
    INTO
        v_total_consultations,
        v_paid_consultations,
        v_unpaid_consultations,
        v_total_amount,
        v_paid_amount,
        v_unpaid_amount
    FROM visits
    WHERE doctor_firebase_uid = p_doctor_uid
    AND (p_start_date IS NULL OR visit_date >= p_start_date)
    AND (p_end_date IS NULL OR visit_date <= p_end_date)
    AND (p_payment_status IS NULL OR payment_status = p_payment_status)
    AND (p_visit_type IS NULL OR visit_type = p_visit_type);

    -- Calculate average
    IF v_total_consultations > 0 THEN
        v_avg_per_consultation := v_total_amount / v_total_consultations;
    ELSE
        v_avg_per_consultation := 0;
    END IF;

    -- Payment method breakdown
    SELECT jsonb_object_agg(COALESCE(payment_method, 'Unknown'), count)
    INTO v_payment_method_breakdown
    FROM (
        SELECT payment_method, COUNT(*) as count
        FROM visits
        WHERE doctor_firebase_uid = p_doctor_uid
        AND (p_start_date IS NULL OR visit_date >= p_start_date)
        AND (p_end_date IS NULL OR visit_date <= p_end_date)
        AND (p_payment_status IS NULL OR payment_status = p_payment_status)
        AND (p_visit_type IS NULL OR visit_type = p_visit_type)
        GROUP BY payment_method
    ) t;

    -- Visit type breakdown
    SELECT jsonb_object_agg(visit_type, count)
    INTO v_visit_type_breakdown
    FROM (
        SELECT visit_type, COUNT(*) as count
        FROM visits
        WHERE doctor_firebase_uid = p_doctor_uid
        AND (p_start_date IS NULL OR visit_date >= p_start_date)
        AND (p_end_date IS NULL OR visit_date <= p_end_date)
        AND (p_payment_status IS NULL OR payment_status = p_payment_status)
        AND (p_visit_type IS NULL OR visit_type = p_visit_type)
        GROUP BY visit_type
    ) t;

    RETURN jsonb_build_object(
        'period', v_period,
        'total_consultations', v_total_consultations,
        'paid_consultations', v_paid_consultations,
        'unpaid_consultations', v_unpaid_consultations,
        'total_amount', v_total_amount,
        'paid_amount', v_paid_amount,
        'unpaid_amount', v_unpaid_amount,
        'average_per_consultation', v_avg_per_consultation,
        'breakdown_by_payment_method', COALESCE(v_payment_method_breakdown, '{}'::jsonb),
        'breakdown_by_visit_type', COALESCE(v_visit_type_breakdown, '{}'::jsonb)
    );
END;
$$;

-- 2. Optimize Cleanup of Outdated Analyses
CREATE OR REPLACE FUNCTION delete_outdated_patient_history_analyses(p_doctor_uid TEXT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_deleted_count INTEGER;
    v_deleted_items JSONB;
BEGIN
    WITH current_counts AS (
        SELECT 
            p.id as patient_id,
            COUNT(DISTINCT v.id) as current_visit_count,
            COUNT(DISTINCT r.id) as current_report_count
        FROM patients p
        LEFT JOIN visits v ON p.id = v.patient_id AND v.doctor_firebase_uid = p_doctor_uid
        LEFT JOIN reports r ON p.id = r.patient_id AND r.doctor_firebase_uid = p_doctor_uid
        WHERE p.created_by_doctor = p_doctor_uid OR EXISTS (SELECT 1 FROM visits WHERE patient_id = p.id AND doctor_firebase_uid = p_doctor_uid)
        GROUP BY p.id
    ),
    outdated_analyses AS (
        SELECT 
            pha.id,
            pha.patient_id,
            pha.total_visits as stored_visits,
            pha.total_reports as stored_reports,
            cc.current_visit_count,
            cc.current_report_count
        FROM patient_history_analysis pha
        JOIN current_counts cc ON pha.patient_id = cc.patient_id
        WHERE pha.doctor_firebase_uid = p_doctor_uid
        AND (pha.total_visits != cc.current_visit_count OR pha.total_reports != cc.current_report_count)
    ),
    deleted_rows AS (
        DELETE FROM patient_history_analysis
        WHERE id IN (SELECT id FROM outdated_analyses)
        RETURNING id, patient_id
    )
    SELECT 
        jsonb_agg(jsonb_build_object(
            'analysis_id', dr.id, 
            'patient_id', dr.patient_id,
            'reason', 'Count mismatch'
        ))
    INTO v_deleted_items
    FROM deleted_rows dr;

    RETURN COALESCE(v_deleted_items, '[]'::jsonb);
END;
$$;

-- 3. Optimize Pharmacy Patient List
CREATE OR REPLACE FUNCTION get_pharmacy_patients_with_medications(
    p_pharmacy_id BIGINT,
    p_hospital_name TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_result JSONB;
BEGIN
    WITH relevant_prescriptions AS (
        SELECT 
            pp.*
        FROM pharmacy_prescriptions pp
        WHERE 
            pp.patient_id IS NOT NULL
            AND (pp.hospital_name = p_hospital_name)
            AND (pp.pharmacy_id IS NULL OR pp.pharmacy_id = p_pharmacy_id)
    ),
    latest_invoices AS (
        SELECT DISTINCT ON (prescription_id)
            *
        FROM pharmacy_invoices
        WHERE pharmacy_id = p_pharmacy_id
        ORDER BY prescription_id, generated_at DESC
    ),
    patient_stats AS (
        SELECT
            rp.patient_id,
            rp.patient_name,
            rp.patient_phone,
            COUNT(rp.id) as total_prescriptions,
            COUNT(CASE WHEN rp.status = 'pending' THEN 1 END) as pending_prescriptions,
            MAX(rp.id) as last_prescription_id,
            MAX(rp.created_at) as last_updated_at,
            MAX(rp.visit_date) as last_visit_date
        FROM relevant_prescriptions rp
        GROUP BY rp.patient_id, rp.patient_name, rp.patient_phone
    ),
    last_prescription_details AS (
        SELECT DISTINCT ON (patient_id)
            patient_id,
            status as last_status,
            medications_json as last_medications
        FROM relevant_prescriptions
        ORDER BY patient_id, created_at DESC
    ),
    last_invoice_details AS (
        SELECT DISTINCT ON (rp.patient_id)
            rp.patient_id,
            li.id as invoice_id,
            li.invoice_number,
            li.total_amount,
            li.status,
            li.generated_at
        FROM relevant_prescriptions rp
        JOIN latest_invoices li ON rp.id = li.prescription_id
        ORDER BY rp.patient_id, li.generated_at DESC
    )
    SELECT jsonb_agg(
        jsonb_build_object(
            'patient_id', ps.patient_id,
            'patient_name', ps.patient_name,
            'patient_phone', ps.patient_phone,
            'total_prescriptions', ps.total_prescriptions,
            'pending_prescriptions', ps.pending_prescriptions,
            'last_prescription_id', ps.last_prescription_id,
            'last_prescription_status', lpd.last_status,
            'last_visit_date', ps.last_visit_date,
            'last_updated_at', ps.last_updated_at,
            'last_medications', COALESCE(lpd.last_medications, '[]'::jsonb),
            'last_invoice_id', lid.invoice_id,
            'last_invoice_number', lid.invoice_number,
            'last_invoice_total', lid.total_amount,
            'last_invoice_status', lid.status,
            'last_invoice_date', lid.generated_at
        )
    ) INTO v_result
    FROM patient_stats ps
    LEFT JOIN last_prescription_details lpd ON ps.patient_id = lpd.patient_id
    LEFT JOIN last_invoice_details lid ON ps.patient_id = lid.patient_id;

    RETURN COALESCE(v_result, '[]'::jsonb);
END;
$$;

