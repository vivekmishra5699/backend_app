-- Migration: Add appointment_reminders table for automatic notification tracking
-- Purpose: Track sent appointment reminders to avoid duplicate notifications
-- The system will send WhatsApp reminders 24 hours before scheduled appointments

-- Create sequence FIRST (before the table that uses it)
CREATE SEQUENCE IF NOT EXISTS appointment_reminders_id_seq;

-- Create table to track appointment reminders
CREATE TABLE IF NOT EXISTS public.appointment_reminders (
    id bigint NOT NULL DEFAULT nextval('appointment_reminders_id_seq'::regclass),
    
    -- Reference to the source of the appointment
    visit_id bigint,                    -- For follow-up appointments from visits table
    appointment_id bigint,              -- For appointments from appointments table
    
    -- Patient and doctor info
    patient_id bigint NOT NULL,
    doctor_firebase_uid text NOT NULL,
    
    -- Appointment details at time of reminder
    appointment_date date NOT NULL,
    appointment_time time without time zone,
    patient_name text NOT NULL,
    patient_phone text NOT NULL,
    doctor_name text NOT NULL,
    hospital_name text,
    
    -- Reminder details
    reminder_type text NOT NULL DEFAULT '24h_before' CHECK (reminder_type IN ('24h_before', '48h_before', '1h_before', 'same_day', 'custom')),
    scheduled_send_time timestamp with time zone NOT NULL,
    
    -- Send status
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed', 'skipped')),
    sent_at timestamp with time zone,
    
    -- WhatsApp details
    whatsapp_message_id text,
    whatsapp_status text,
    error_message text,
    
    -- Retry tracking
    retry_count integer DEFAULT 0,
    max_retries integer DEFAULT 3,
    next_retry_at timestamp with time zone,
    
    -- Metadata
    message_content text,              -- Store the actual message sent
    metadata jsonb DEFAULT '{}'::jsonb,
    
    -- Timestamps
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    
    CONSTRAINT appointment_reminders_pkey PRIMARY KEY (id),
    CONSTRAINT appointment_reminders_visit_id_fkey FOREIGN KEY (visit_id) REFERENCES public.visits(id) ON DELETE SET NULL,
    CONSTRAINT appointment_reminders_appointment_id_fkey FOREIGN KEY (appointment_id) REFERENCES public.appointments(id) ON DELETE SET NULL,
    CONSTRAINT appointment_reminders_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patients(id),
    CONSTRAINT appointment_reminders_doctor_fkey FOREIGN KEY (doctor_firebase_uid) REFERENCES public.doctors(firebase_uid),
    
    -- Ensure at least one source reference exists
    CONSTRAINT appointment_reminders_source_check CHECK (visit_id IS NOT NULL OR appointment_id IS NOT NULL)
);

-- Add indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_appointment_reminders_status ON public.appointment_reminders(status);
CREATE INDEX IF NOT EXISTS idx_appointment_reminders_scheduled_send ON public.appointment_reminders(scheduled_send_time) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_appointment_reminders_patient ON public.appointment_reminders(patient_id);
CREATE INDEX IF NOT EXISTS idx_appointment_reminders_doctor ON public.appointment_reminders(doctor_firebase_uid);
CREATE INDEX IF NOT EXISTS idx_appointment_reminders_appointment_date ON public.appointment_reminders(appointment_date);
CREATE INDEX IF NOT EXISTS idx_appointment_reminders_visit ON public.appointment_reminders(visit_id) WHERE visit_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_appointment_reminders_appointment ON public.appointment_reminders(appointment_id) WHERE appointment_id IS NOT NULL;

-- Composite index for checking duplicate reminders
CREATE UNIQUE INDEX IF NOT EXISTS idx_appointment_reminders_unique_visit 
    ON public.appointment_reminders(visit_id, reminder_type, appointment_date) 
    WHERE visit_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_appointment_reminders_unique_appointment 
    ON public.appointment_reminders(appointment_id, reminder_type, appointment_date) 
    WHERE appointment_id IS NOT NULL;

-- Add column to doctors table for reminder settings (optional)
ALTER TABLE public.doctors 
    ADD COLUMN IF NOT EXISTS appointment_reminders_enabled boolean DEFAULT true,
    ADD COLUMN IF NOT EXISTS reminder_hours_before integer DEFAULT 24;

-- Add updated_at trigger for appointment_reminders
CREATE OR REPLACE FUNCTION update_appointment_reminders_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_appointment_reminders_updated_at ON public.appointment_reminders;
CREATE TRIGGER set_appointment_reminders_updated_at
    BEFORE UPDATE ON public.appointment_reminders
    FOR EACH ROW
    EXECUTE FUNCTION update_appointment_reminders_updated_at();

-- Comments for documentation
COMMENT ON TABLE public.appointment_reminders IS 'Tracks automatic appointment reminder notifications sent via WhatsApp';
COMMENT ON COLUMN public.appointment_reminders.reminder_type IS 'Type of reminder: 24h_before, 48h_before, 1h_before, same_day, or custom';
COMMENT ON COLUMN public.appointment_reminders.status IS 'Reminder status: pending (scheduled), sent (delivered), failed (error), skipped (e.g., no phone)';
