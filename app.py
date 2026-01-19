from fastapi import FastAPI, HTTPException, Depends, status, Request, File, Form, UploadFile, Body, Query
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, ValidationError, Field
from datetime import datetime, timezone, timedelta, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
from supabase import create_client, Client, AsyncClient
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth
import os
import json
import traceback
import uuid
import secrets
import shutil
import tempfile
import asyncio
import concurrent.futures
from pathlib import Path
import os
import requests
import re
import jwt
from datetime import timedelta
import httpx
import uvicorn
from async_file_downloader import file_downloader
from connection_pool import get_supabase_client, get_async_supabase_client, close_connection_pools
from thread_pool_manager import shutdown_thread_pool
from optimized_cache import optimized_cache
import firebase_admin
import hashlib
import hmac
from contextlib import asynccontextmanager

# Import our database manager
from database import DatabaseManager
# Import custom exceptions
from firebase_manager import AsyncFirebaseManager, TokenExpiredError, TokenInvalidError, TokenVerificationError
from whatsapp_service import WhatsAppService
from pdf_generator import PatientProfilePDFGenerator  # New import for PDF generation

# Import AI analysis service
from ai_analysis_service import AIAnalysisService
from ai_analysis_processor import AIAnalysisProcessor

# Import Appointment Reminder Service
from appointment_reminder_service import AppointmentReminderService

# Load environment variables
load_dotenv()

# Global variables for services
supabase: Optional[AsyncClient] = None
db: Optional[DatabaseManager] = None
firebase_manager: Optional[AsyncFirebaseManager] = None
whatsapp_service: Optional[WhatsAppService] = None
ai_analysis_service: Optional[AIAnalysisService] = None
ai_processor: Optional[AIAnalysisProcessor] = None
appointment_reminder_service: Optional[AppointmentReminderService] = None
background_task = None
cleanup_task = None
reminder_task = None

# In-memory set to track in-progress analyses (simple deduplication)
_analyses_in_progress: set = set()

async def periodic_queue_cleanup(db_instance, interval_hours: int = 1):
    """
    Background task to periodically clean up the AI analysis queue.
    Runs every interval_hours and removes old completed/failed items.
    """
    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)  # Sleep first, then cleanup
            
            print("🧹 Running periodic queue cleanup...")
            
            # Clean up completed items older than 24 hours
            completed_cleaned = await db_instance.cleanup_completed_queue_items(hours_old=24)
            
            # Reset stale processing items (stuck for more than 2 hours)
            stale_reset = await db_instance.cleanup_stale_processing_items(hours_stale=2)
            
            # Get queue stats for monitoring
            stats = await db_instance.get_queue_stats()
            print(f"📊 Queue stats after cleanup: {stats}")
            
        except asyncio.CancelledError:
            print("🛑 Queue cleanup task cancelled")
            break
        except Exception as e:
            print(f"❌ Error in periodic queue cleanup: {e}")
            # Continue running despite errors
            await asyncio.sleep(60)  # Wait a minute before retrying

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global supabase, db, firebase_manager, whatsapp_service, ai_analysis_service, ai_processor, appointment_reminder_service, background_task, cleanup_task, reminder_task
    
    print("🚀 Starting application...")
    
    # Supabase setup with error handling
    try:
        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        print(f"Supabase URL: {SUPABASE_URL}")
        print(f"Supabase Key present: {'Yes' if SUPABASE_KEY else 'No'}")
        print(f"Supabase Service Role Key present: {'Yes' if SUPABASE_SERVICE_ROLE_KEY else 'No'}")
        
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("Supabase credentials not found in environment variables")
        
        if not SUPABASE_SERVICE_ROLE_KEY:
            raise ValueError("Service role key is required for RLS-enabled operations")
        
        # Use service role client with connection pooling for database operations
        # Initialize async Supabase client
        supabase = await get_async_supabase_client(
            supabase_url=SUPABASE_URL,
            supabase_key=SUPABASE_SERVICE_ROLE_KEY,
            pool_size=10,  # Maintain 10 active connections
            max_overflow=20,  # Allow up to 20 overflow connections
            pool_timeout=30,  # Connection timeout
            pool_recycle=3600  # Recycle connections after 1 hour
        )
        print("✅ Supabase initialized with connection pooling (Async)")
        
        # Initialize database manager with service role client
        db = DatabaseManager(supabase)
        print("Database manager initialized successfully")
        
        # Initialize async Firebase manager  
        firebase_manager = AsyncFirebaseManager()
        print("Firebase manager initialized successfully")
        
        # Initialize WhatsApp service
        whatsapp_service = WhatsAppService()
        print("WhatsApp service initialized successfully")
        
        # Initialize AI Analysis service
        ai_analysis_service = AIAnalysisService()
        print("AI Analysis service initialized successfully")
        
        # Initialize AI Analysis background processor (using global variable)
        ai_processor = AIAnalysisProcessor(db, ai_analysis_service)
        print("AI Analysis processor initialized successfully")
        
        # Initialize Appointment Reminder Service
        appointment_reminder_service = AppointmentReminderService(db, whatsapp_service)
        print("Appointment Reminder service initialized successfully")
        
    except Exception as e:
        print(f"ERROR initializing Supabase: {e}")
        raise

    print("🚀 Starting AI Analysis background processor...")
    
    try:
        # Start the background processor task
        background_task = asyncio.create_task(ai_processor.start_processing())
        print("✅ AI Analysis background processor started successfully")
        
        # Start periodic queue cleanup task (runs every hour)
        cleanup_task = asyncio.create_task(periodic_queue_cleanup(db, interval_hours=1))
        print("✅ Periodic queue cleanup task started (runs every hour)")
        
        # Start appointment reminder service
        reminder_task = asyncio.create_task(appointment_reminder_service.start())
        print("✅ Appointment reminder service started (checks every 15 minutes)")
        
        # Run initial cleanup on startup
        print("🧹 Running initial queue cleanup on startup...")
        await db.cleanup_completed_queue_items(hours_old=24)
        await db.cleanup_stale_processing_items(hours_stale=2)
        initial_stats = await db.get_queue_stats()
        print(f"📊 Initial queue stats: {initial_stats}")
        
        yield
    except Exception as e:
        print(f"❌ Error starting background processor: {e}")
        yield
    finally:
        # Shutdown
        print("🛑 Stopping AI Analysis background processor...")
        if ai_processor:
            ai_processor.stop_processing()
        if background_task:
            background_task.cancel()
            try:
                await background_task
            except asyncio.CancelledError:
                pass
        print("✅ AI Analysis background processor stopped")
        
        # Stop cleanup task
        if cleanup_task:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
        print("✅ Periodic cleanup task stopped")
        
        # Stop appointment reminder service
        print("🛑 Stopping appointment reminder service...")
        if appointment_reminder_service:
            appointment_reminder_service.stop()
        if reminder_task:
            reminder_task.cancel()
            try:
                await reminder_task
            except asyncio.CancelledError:
                pass
        print("✅ Appointment reminder service stopped")
        
        # Get cache stats before shutdown
        print("📊 Final cache statistics:")
        cache_stats = await optimized_cache.get_stats()
        for key, value in cache_stats.items():
            print(f"   - {key}: {value}")
        
        # Close connection pools
        print("🔌 Closing connection pools...")
        await close_connection_pools()
        print("✅ Connection pools closed successfully")
        
        # Shutdown unified thread pool
        print("🧵 Shutting down unified thread pool...")
        shutdown_thread_pool(wait=True)
        print("✅ Thread pool shut down successfully")

app = FastAPI(
    title="Doctor App API", 
    version="1.0.0", 
    description="""## Doctor App Backend API
    
A comprehensive healthcare management API for doctors, frontdesk staff, pharmacies, and labs.

### Key Features:
- **Patient Management**: Register and manage patient profiles with detailed medical history
- **Visit Tracking**: Create and manage patient visits with vitals, diagnosis, and prescriptions
- **Lab Integration**: Request and receive lab reports from pathology and radiology labs
- **AI Analysis**: Get AI-powered analysis of medical reports and patient history
- **Pharmacy Integration**: Manage prescriptions and pharmacy orders

### New: Enhanced Prior Medical History
Patient registration now supports detailed prior medical history including:
- Previous doctor consultations
- Prior medications and their effectiveness
- Previous symptoms and diagnosis
- Reason for seeking new consultation
""",
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "Authentication",
            "description": "Doctor and user authentication endpoints"
        },
        {
            "name": "Patients",
            "description": "Patient registration and management with enhanced prior medical history support"
        },
        {
            "name": "Visits",
            "description": "Patient visit management including vitals, diagnosis, and treatment"
        },
        {
            "name": "Frontdesk",
            "description": "Frontdesk operations for hospital staff"
        },
        {
            "name": "Pharmacy",
            "description": "Pharmacy integration and prescription management"
        },
        {
            "name": "Lab",
            "description": "Lab report requests and uploads"
        },
        {
            "name": "AI Analysis",
            "description": """AI-powered medical document analysis using Google Gemini.

### Features:
- **Structured JSON Output**: All analysis results use structured JSON schemas for reliable parsing
- **Critical Findings Detection**: Automatic detection of critical values and urgent findings
- **Clinical Alert Generation**: Auto-generates alerts for critical findings requiring attention
- **Treatment Evaluation**: AI-powered assessment of treatment effectiveness

### Analysis Types:
- **Document Analysis**: Lab reports, imaging results, discharge summaries
- **Handwritten Notes**: Prescription and clinical note digitization
- **Comprehensive History**: Full patient journey analysis across visits
- **Consolidated Analysis**: Multi-document synthesis and insights

### Output Schemas:
All responses include structured data with:
- findings, critical_findings, clinical_correlation
- treatment_evaluation, actionable_insights
- patient_communication summaries
"""
        },
        {
            "name": "Prescriptions",
            "description": """Prescription management including standard and empirical prescriptions.
            
### Prescription Types:
- **General**: Standard prescriptions based on complete diagnosis
- **Empirical**: Initial prescriptions given before lab/test results are available
- **Follow-up**: Updated prescriptions after reviewing test results

### Empirical Prescriptions:
Empirical prescriptions include a disclaimer that the prescription may be modified based on:
- Laboratory test results
- Diagnostic imaging reports
- Further clinical investigation
- Follow-up examination findings
"""
        },
        {
            "name": "Calendar",
            "description": "Appointment calendar and follow-up management"
        },
        {
            "name": "Billing",
            "description": "Earnings, billing, and payment tracking"
        },
        {
            "name": "Templates",
            "description": "PDF prescription template management"
        },
        {
            "name": "Notifications",
            "description": "Doctor notifications and alerts"
        },
        {
            "name": "Clinical Alerts",
            "description": """AI-powered clinical alerts and critical findings notification system.

### Alert Types:
- **critical_value**: Critical lab values requiring immediate attention
- **drug_interaction**: Potential drug interactions or contraindications
- **diagnosis_concern**: Suspicious findings requiring further investigation
- **follow_up_urgent**: Urgent follow-up recommendations
- **treatment_alert**: Treatment modification recommendations
- **safety_concern**: Patient safety alerts

### Severity Levels:
- **high**: Immediate action required (critical values, life-threatening)
- **medium**: Prompt attention needed (significant abnormalities)
- **low**: Informational alerts for awareness

### Features:
- Real-time alert generation from AI analysis
- Acknowledge alerts with optional notes
- Patient-specific and visit-specific alert views
- Alert history tracking
"""
        },
        {
            "name": "Appointment Reminders",
            "description": """Automatic appointment reminder system via WhatsApp.

### Features:
- **Automatic Reminders**: Sends WhatsApp reminders 24 hours before appointments
- **Configurable Timing**: Customize how many hours before to send reminders (1-72 hours)
- **Per-Doctor Settings**: Each doctor can enable/disable and configure their reminders
- **Retry Logic**: Failed reminders are automatically retried up to 3 times
- **History Tracking**: View sent reminders and their delivery status

### Reminder Sources:
- Follow-up appointments from visits
- Scheduled appointments from the appointments calendar

### How It Works:
1. The service runs in the background, checking every 15 minutes
2. It finds appointments scheduled within the next 24 hours
3. For each appointment, it sends a WhatsApp message to the patient
4. Delivery status is tracked and failed sends are retried

### Manual Overrides:
- Use `/reminders/send-now/{visit_id}` to immediately send a reminder
- Include custom messages for special instructions
"""
        }
    ]
)

# CORS middleware for Flutter app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Firebase setup with error handling
try:
    firebase_creds_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
    print(f"Firebase credentials path: {firebase_creds_path}")
    
    if not firebase_creds_path or not os.path.exists(firebase_creds_path):
        print("ERROR: Firebase credentials file not found!")
        raise FileNotFoundError("Firebase credentials file not found")
    
    # Check if Firebase app is already initialized
    if not firebase_admin._apps:
        cred = credentials.Certificate(firebase_creds_path)
        firebase_admin.initialize_app(cred)
        print("Firebase initialized successfully")
    else:
        print("Firebase app already initialized")
except Exception as e:
    print(f"ERROR initializing Firebase: {e}")
    raise

security = HTTPBearer()

# Pydantic models
class DoctorRegister(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    specialization: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    hospital_name: Optional[str] = None
    
    class Config:
        str_strip_whitespace = True
        str_min_length = 1

class DoctorLogin(BaseModel):
    email: EmailStr
    password: str

class DoctorProfile(BaseModel):
    firebase_uid: str
    email: str
    first_name: str
    last_name: str
    specialization: Optional[str]
    license_number: Optional[str]
    phone: Optional[str]
    hospital_name: Optional[str] = None
    pathology_lab_name: Optional[str] = None
    pathology_lab_phone: Optional[str] = None
    radiology_lab_name: Optional[str] = None
    radiology_lab_phone: Optional[str] = None
    ai_enabled: bool = True  # AI analysis toggle
    created_at: str
    updated_at: str

class DoctorUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    specialization: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    hospital_name: Optional[str] = None
    pathology_lab_phone: Optional[str] = None
    pathology_lab_name: Optional[str] = None
    radiology_lab_phone: Optional[str] = None
    radiology_lab_name: Optional[str] = None
    ai_enabled: Optional[bool] = None  # AI analysis toggle

# Frontdesk Models
class FrontdeskRegister(BaseModel):
    name: str
    phone: str
    hospital_name: str
    username: str
    password: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "John Doe",
                "phone": "1234567890",
                "hospital_name": "City Hospital",
                "username": "john_frontdesk",
                "password": "securepassword123"
            }
        }

class FrontdeskLogin(BaseModel):
    username: str
    password: str

class FrontdeskProfile(BaseModel):
    id: int
    name: str
    phone: str
    hospital_name: str
    username: str
    is_active: bool
    created_at: str
    updated_at: str

class FrontdeskUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    hospital_name: Optional[str] = None
    password: Optional[str] = None

# Pharmacy Models
class PharmacyRegister(BaseModel):
    name: str
    phone: Optional[str] = None
    hospital_name: str
    username: str
    password: str

    class Config:
        json_schema_extra = {
            "example": {
                "name": "City Hospital Pharmacy",
                "phone": "+1-202-555-0110",
                "hospital_name": "City Hospital",
                "username": "city_pharmacy",
                "password": "strongpassword123"
            }
        }


class PharmacyLogin(BaseModel):
    username: str
    password: str


class PharmacyProfile(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    hospital_name: str
    username: str
    is_active: bool
    created_at: str
    updated_at: str
    last_login_at: Optional[str] = None


class PharmacyInventoryCreate(BaseModel):
    medicine_name: str
    sku: Optional[str] = None
    batch_number: Optional[str] = None
    expiry_date: Optional[str] = None  # YYYY-MM-DD
    stock_quantity: int = Field(0, ge=0)
    reorder_level: Optional[int] = Field(default=0, ge=0)
    unit: Optional[str] = None
    purchase_price: Optional[float] = Field(default=None, ge=0)
    selling_price: Optional[float] = Field(default=None, ge=0)
    tax_percent: Optional[float] = Field(default=None, ge=0, le=100, description="GST/VAT percentage for this stock item")
    supplier_id: Optional[int] = Field(default=None, description="Supplier record ID from /pharmacy/{pharmacy_id}/suppliers")


class PharmacyInventoryUpdate(BaseModel):
    medicine_name: Optional[str] = None
    sku: Optional[str] = None
    batch_number: Optional[str] = None
    expiry_date: Optional[str] = None
    stock_quantity: Optional[int] = Field(default=None, ge=0)
    reorder_level: Optional[int] = Field(default=None, ge=0)
    unit: Optional[str] = None
    purchase_price: Optional[float] = Field(default=None, ge=0)
    selling_price: Optional[float] = Field(default=None, ge=0)
    tax_percent: Optional[float] = Field(default=None, ge=0, le=100)
    supplier_id: Optional[int] = Field(default=None, description="Link or unlink a supplier record")


class PharmacyInventorySupplierInfo(BaseModel):
    id: int
    name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None


class PharmacyInventoryItem(BaseModel):
    id: int
    pharmacy_id: int
    medicine_name: str
    sku: Optional[str] = None
    batch_number: Optional[str] = None
    expiry_date: Optional[str] = None
    stock_quantity: int
    reorder_level: Optional[int] = None
    unit: Optional[str] = None
    purchase_price: Optional[float] = None
    selling_price: Optional[float] = None
    tax_percent: Optional[float] = None
    supplier_id: Optional[int] = None
    supplier: Optional["PharmacyInventorySupplierInfo"] = None
    created_at: str
    updated_at: str


class PharmacyInventoryAdjust(BaseModel):
    quantity_delta: int = Field(..., description="Positive to increase stock, negative to decrease stock")
    note: Optional[str] = None


try:
    PharmacyInventoryItem.model_rebuild()
except AttributeError:
    PharmacyInventoryItem.update_forward_refs()


class PharmacyPrescriptionItem(BaseModel):
    name: str
    details: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None


class PharmacyPrescriptionView(BaseModel):
    id: int
    visit_id: int
    patient_id: int
    patient_name: str
    patient_phone: Optional[str] = None
    doctor_firebase_uid: str
    doctor_name: Optional[str] = None
    doctor_specialization: Optional[str] = None
    hospital_name: str
    pharmacy_id: Optional[int] = None
    medications_text: Optional[str] = None
    medications_json: Optional[List[Dict[str, Any]]] = None
    status: str
    visit_date: Optional[str] = None
    visit_type: Optional[str] = None
    notes: Optional[str] = None
    total_estimated_amount: Optional[float] = None
    created_at: str
    updated_at: str
    dispensed_at: Optional[str] = None


class PharmacyPrescriptionStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


class PharmacyInvoiceItem(BaseModel):
    inventory_item_id: Optional[int] = Field(default=None, description="Reference to inventory item if applicable")
    medicine_name: str
    quantity: int = Field(..., gt=0)
    unit_price: float = Field(..., ge=0)
    subtotal: Optional[float] = Field(default=None, ge=0)


class PharmacyInvoiceCreate(BaseModel):
    items: List[PharmacyInvoiceItem]
    subtotal: float = Field(..., ge=0)
    tax: Optional[float] = Field(default=0, ge=0)
    discount: Optional[float] = Field(default=0, ge=0)
    total_amount: float = Field(..., ge=0)
    payment_method: Optional[str] = None
    status: Optional[str] = "paid"
    notes: Optional[str] = None


class PharmacyInvoiceResponse(BaseModel):
    id: int
    pharmacy_id: int
    prescription_id: Optional[int] = None
    invoice_number: str
    items: List[Dict[str, Any]]
    subtotal: float
    tax: float
    discount: float
    total_amount: float
    payment_method: Optional[str] = None
    status: str
    generated_at: str
    created_by: Optional[str] = None
    notes: Optional[str] = None
    # Enriched patient details (sourced from linked prescription)
    patient_id: Optional[int] = None
    patient_name: Optional[str] = None
    patient_phone: Optional[str] = None
    # Prescription date (visit date) for UI display
    prescription_date: Optional[str] = None


class PharmacyPatientMedications(BaseModel):
    patient_id: int
    patient_name: str
    patient_phone: Optional[str] = None
    total_prescriptions: int
    pending_prescriptions: int
    last_prescription_id: Optional[int] = None
    last_prescription_status: Optional[str] = None
    last_visit_date: Optional[str] = None
    last_updated_at: Optional[str] = None
    last_medications: List[Dict[str, Any]] = Field(default_factory=list)
    last_invoice_id: Optional[int] = None
    last_invoice_number: Optional[str] = None
    last_invoice_total: Optional[float] = None
    last_invoice_status: Optional[str] = None
    last_invoice_date: Optional[str] = None


class PharmacyPurchaseHistoryItem(BaseModel):
    invoice_id: int
    invoice_number: str
    prescription_id: int
    patient_id: int
    patient_name: str
    patient_phone: Optional[str] = None
    total_amount: float
    status: str
    payment_method: Optional[str] = None
    generated_at: str
    prescription_status: Optional[str] = None
    prescription_date: Optional[str] = None
    medications: List[Dict[str, Any]] = Field(default_factory=list)
    notes: Optional[str] = None


class PharmacySupplierBase(BaseModel):
    name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = True


class PharmacySupplierCreate(PharmacySupplierBase):
    name: str


class PharmacySupplierUpdate(BaseModel):
    name: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class PharmacySupplierResponse(PharmacySupplierBase):
    id: int
    pharmacy_id: int
    created_at: str
    updated_at: str


class PharmacyPatientDetailResponse(BaseModel):
    patient_id: int
    patient_name: str
    patient_phone: Optional[str] = None
    patient_email: Optional[str] = None
    patient_gender: Optional[str] = None
    patient_date_of_birth: Optional[str] = None
    total_prescriptions: int
    pending_prescriptions: int
    latest_prescription: Optional[PharmacyPrescriptionView] = None
    prescriptions: List[PharmacyPrescriptionView] = Field(default_factory=list)
    invoices: List[PharmacyPurchaseHistoryItem] = Field(default_factory=list)


class PharmacyDashboardSummary(BaseModel):
    pharmacy_profile: PharmacyProfile
    pending_prescriptions: int
    ready_prescriptions: int
    dispensed_today: int
    inventory_low_stock: int
    total_inventory_items: int
    sales_today: float
    sales_month: float

# Hospital-based Response Models for Frontdesk
class DoctorWithPatientCount(BaseModel):
    id: int
    firebase_uid: str
    email: str
    first_name: str
    last_name: str
    specialization: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    hospital_name: Optional[str] = None
    patient_count: int
    created_at: str
    updated_at: str

class PatientWithDoctorInfo(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: str
    date_of_birth: str
    gender: str
    address: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    medical_history: Optional[str] = None
    doctor_name: str
    doctor_specialization: str
    doctor_phone: str
    created_at: str
    updated_at: str

class HospitalDashboardResponse(BaseModel):
    hospital_name: str
    total_doctors: int
    total_patients: int
    doctors: List[DoctorWithPatientCount]
    recent_patients: List[PatientWithDoctorInfo]

# Prior Medical History Model - Detailed medical history from previous consultations
class PriorMedicalHistory(BaseModel):
    """Detailed prior medical history for patients who have consulted other doctors.
    
    This model captures comprehensive information about a patient's previous medical consultations,
    including the treating doctor, diagnosis, medications prescribed, and their response to treatment.
    This helps the current doctor understand the patient's medical journey and make informed decisions.
    """
    consulted_other_doctor: bool = Field(
        default=False,
        description="Whether the patient has consulted another doctor for the current condition before coming here"
    )
    previous_doctor_name: Optional[str] = Field(
        default=None,
        description="Full name of the previous doctor consulted (e.g., 'Dr. Sharma')"
    )
    previous_doctor_specialization: Optional[str] = Field(
        default=None,
        description="Specialization of the previous doctor (e.g., 'General Physician', 'Cardiologist')"
    )
    previous_clinic_hospital: Optional[str] = Field(
        default=None,
        description="Name of the clinic or hospital where the patient was previously treated"
    )
    previous_consultation_date: Optional[str] = Field(
        default=None,
        description="Date of the previous consultation in YYYY-MM-DD format"
    )
    previous_symptoms: Optional[str] = Field(
        default=None,
        description="Symptoms the patient presented with at the previous consultation"
    )
    previous_diagnosis: Optional[str] = Field(
        default=None,
        description="Diagnosis given by the previous doctor"
    )
    previous_medications: Optional[List[str]] = Field(
        default=None,
        description="List of medications prescribed by the previous doctor (e.g., ['Paracetamol 500mg', 'Cetirizine 10mg'])"
    )
    previous_medications_duration: Optional[str] = Field(
        default=None,
        description="Duration for which previous medications were prescribed (e.g., '5 days', '2 weeks')"
    )
    medication_response: Optional[str] = Field(
        default=None,
        description="Patient's response to previous medications. Allowed values: 'improved', 'partial improvement', 'no change', 'worsened'"
    )
    previous_tests_done: Optional[str] = Field(
        default=None,
        description="Medical tests performed during previous consultation (e.g., 'CBC, Dengue NS1, X-ray chest')"
    )
    previous_test_results: Optional[str] = Field(
        default=None,
        description="Results of the previous tests (e.g., 'CBC normal, Dengue negative')"
    )
    reason_for_new_consultation: Optional[str] = Field(
        default=None,
        description="Why the patient is seeking a new consultation (e.g., 'no improvement', 'second opinion', 'symptoms worsened')"
    )
    ongoing_treatment: bool = Field(
        default=False,
        description="Whether the patient is currently on any ongoing treatment"
    )
    current_medications: Optional[List[str]] = Field(
        default=None,
        description="List of medications the patient is currently taking"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "consulted_other_doctor": True,
                "previous_doctor_name": "Dr. Sharma",
                "previous_doctor_specialization": "General Physician",
                "previous_clinic_hospital": "City Hospital",
                "previous_consultation_date": "2026-01-01",
                "previous_symptoms": "Fever, headache, body ache",
                "previous_diagnosis": "Viral fever",
                "previous_medications": ["Paracetamol 500mg", "Cetirizine 10mg"],
                "previous_medications_duration": "5 days",
                "medication_response": "partial improvement",
                "previous_tests_done": "CBC, Dengue NS1",
                "previous_test_results": "CBC normal, Dengue negative",
                "reason_for_new_consultation": "Symptoms persisting after medication",
                "ongoing_treatment": True,
                "current_medications": ["Paracetamol 500mg"]
            }
        }

# Frontdesk Patient Registration Model
class FrontdeskPatientRegister(BaseModel):
    first_name: str
    last_name: str
    email: Optional[EmailStr] = None
    phone: str
    date_of_birth: str  # Format: YYYY-MM-DD
    gender: str  # Male, Female, Other
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    medical_history: Optional[str] = None
    doctor_firebase_uid: str  # The selected doctor for this patient
    # Detailed prior medical history fields
    prior_medical_history: Optional[PriorMedicalHistory] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "first_name": "John",
                "last_name": "Doe",
                "email": "john.doe@email.com",
                "phone": "1234567890",
                "date_of_birth": "1990-01-15",
                "gender": "Male",
                "address": "123 Main St, City",
                "emergency_contact_name": "Jane Doe",
                "emergency_contact_phone": "0987654321",
                "blood_group": "O+",
                "allergies": "None",
                "medical_history": "No significant medical history",
                "doctor_firebase_uid": "doctor_firebase_uid_here",
                "prior_medical_history": {
                    "consulted_other_doctor": True,
                    "previous_doctor_name": "Dr. Sharma",
                    "previous_symptoms": "Fever and cold",
                    "previous_diagnosis": "Viral infection",
                    "previous_medications": ["Paracetamol 500mg"],
                    "medication_response": "partial improvement"
                }
            }
        }

# Appointment Management Models
class AppointmentCreate(BaseModel):
    doctor_firebase_uid: str
    patient_id: Optional[int] = None  # Can be None for blocked time slots
    appointment_date: str  # YYYY-MM-DD format
    appointment_time: str  # HH:MM format
    duration_minutes: int = 30
    appointment_type: str = "consultation"
    notes: Optional[str] = None
    patient_notes: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "doctor_firebase_uid": "doctor_firebase_uid_here",
                "patient_id": 123,
                "appointment_date": "2025-10-01",
                "appointment_time": "10:30",
                "duration_minutes": 30,
                "appointment_type": "consultation",
                "notes": "Follow-up appointment",
                "patient_notes": "Patient prefers morning appointments"
            }
        }

class AppointmentUpdate(BaseModel):
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    status: Optional[str] = None  # scheduled, confirmed, in_progress, completed, cancelled, no_show
    appointment_type: Optional[str] = None
    notes: Optional[str] = None
    patient_notes: Optional[str] = None

class AppointmentView(BaseModel):
    id: int
    doctor_firebase_uid: str
    doctor_name: str
    doctor_specialization: Optional[str] = None
    patient_id: Optional[int] = None
    patient_name: Optional[str] = None
    patient_phone: Optional[str] = None
    appointment_date: str
    appointment_time: str
    duration_minutes: int
    status: str
    appointment_type: str
    notes: Optional[str] = None
    patient_notes: Optional[str] = None
    created_by_frontdesk: bool
    created_at: str
    updated_at: str

class DoctorScheduleView(BaseModel):
    doctor_firebase_uid: str
    doctor_name: str
    doctor_specialization: Optional[str] = None
    doctor_phone: Optional[str] = None
    appointments: List[AppointmentView]

class CalendarDayView(BaseModel):
    date: str  # YYYY-MM-DD
    doctors: List[DoctorScheduleView]

class CalendarWeekView(BaseModel):
    week_start: str  # YYYY-MM-DD (Monday)
    week_end: str    # YYYY-MM-DD (Sunday)
    days: List[CalendarDayView]

class CalendarMonthView(BaseModel):
    year: int
    month: int
    hospital_name: str
    total_appointments: int
    doctors: List[DoctorScheduleView]
    weekly_view: List[CalendarWeekView]

class AppointmentStats(BaseModel):
    total_appointments: int
    scheduled: int
    confirmed: int
    completed: int
    cancelled: int
    no_show: int

class HospitalScheduleOverview(BaseModel):
    hospital_name: str
    date_range: str
    stats: AppointmentStats
    doctors: List[DoctorScheduleView]

# Lab Management Models
class LabContact(BaseModel):
    id: int
    doctor_firebase_uid: str
    lab_type: str  # "pathology" or "radiology"
    lab_name: str
    contact_phone: str
    contact_email: Optional[str] = None
    is_active: bool = True
    created_at: str
    updated_at: str

class LabContactCreate(BaseModel):
    lab_type: str  # "pathology" or "radiology"
    lab_name: str
    contact_phone: str
    contact_email: Optional[str] = None

class LabContactUpdate(BaseModel):
    lab_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    is_active: Optional[bool] = None

class LabLogin(BaseModel):
    phone: str

class LabReportRequest(BaseModel):
    id: int
    visit_id: int
    patient_id: int
    doctor_firebase_uid: str
    lab_contact_id: int
    patient_name: str
    report_type: str  # "pathology" or "radiology"
    test_name: str
    instructions: Optional[str] = None
    status: str  # "pending", "uploaded", "completed"
    request_token: str
    expires_at: str
    created_at: str
    lab_contact: Optional[LabContact] = None

class FirebaseToken(BaseModel):
    id_token: str

# Patient Models
class PatientRegister(BaseModel):
    first_name: str
    last_name: str
    email: Optional[EmailStr] = None
    phone: str
    date_of_birth: str  # Format: YYYY-MM-DD
    gender: str  # Male, Female, Other
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    medical_history: Optional[str] = None  # General medical history notes
    # Detailed prior medical history fields
    prior_medical_history: Optional[PriorMedicalHistory] = None
    
    class Config:
        str_strip_whitespace = True

class PatientUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    medical_history: Optional[str] = None
    # Detailed prior medical history fields
    prior_medical_history: Optional[PriorMedicalHistory] = None

class PatientProfile(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: Optional[str]
    phone: str
    date_of_birth: str
    gender: str
    address: Optional[str]
    emergency_contact_name: Optional[str]
    emergency_contact_phone: Optional[str]
    blood_group: Optional[str]
    allergies: Optional[str]
    medical_history: Optional[str]
    # Detailed prior medical history fields
    consulted_other_doctor: Optional[bool] = None
    previous_doctor_name: Optional[str] = None
    previous_doctor_specialization: Optional[str] = None
    previous_clinic_hospital: Optional[str] = None
    previous_consultation_date: Optional[str] = None
    previous_symptoms: Optional[str] = None
    previous_diagnosis: Optional[str] = None
    previous_medications: Optional[List[str]] = None
    previous_medications_duration: Optional[str] = None
    medication_response: Optional[str] = None
    previous_tests_done: Optional[str] = None
    previous_test_results: Optional[str] = None
    reason_for_new_consultation: Optional[str] = None
    ongoing_treatment: Optional[bool] = None
    current_medications: Optional[List[str]] = None
    created_at: str
    updated_at: str
    created_by_doctor: str



# Visit Models
class Vitals(BaseModel):
    """Patient vital signs recorded during a visit.
    
    Contains all standard vital measurements including temperature, blood pressure,
    heart rate, pulse rate, respiratory rate, oxygen saturation, and body measurements.
    """
    temperature: Optional[float] = Field(
        default=None,
        description="Body temperature in Celsius (e.g., 37.5)",
        ge=30.0,
        le=45.0
    )
    blood_pressure_systolic: Optional[int] = Field(
        default=None,
        description="Systolic blood pressure in mmHg (e.g., 120)",
        ge=50,
        le=300
    )
    blood_pressure_diastolic: Optional[int] = Field(
        default=None,
        description="Diastolic blood pressure in mmHg (e.g., 80)",
        ge=30,
        le=200
    )
    heart_rate: Optional[int] = Field(
        default=None,
        description="Heart rate in beats per minute (BPM), measured via auscultation or ECG",
        ge=20,
        le=300
    )
    pulse_rate: Optional[int] = Field(
        default=None,
        description="Pulse rate in beats per minute (BPM), measured at wrist or other peripheral artery. May differ from heart rate in conditions like atrial fibrillation.",
        ge=20,
        le=300
    )
    respiratory_rate: Optional[int] = Field(
        default=None,
        description="Respiratory rate in breaths per minute",
        ge=5,
        le=60
    )
    oxygen_saturation: Optional[float] = Field(
        default=None,
        description="Oxygen saturation (SpO2) as percentage (e.g., 98.5)",
        ge=50.0,
        le=100.0
    )
    weight: Optional[float] = Field(
        default=None,
        description="Patient weight in kilograms (kg)",
        ge=0.5,
        le=500.0
    )
    height: Optional[float] = Field(
        default=None,
        description="Patient height in centimeters (cm)",
        ge=20.0,
        le=300.0
    )
    bmi: Optional[float] = Field(
        default=None,
        description="Body Mass Index (BMI) - calculated as weight(kg) / height(m)²",
        ge=5.0,
        le=100.0
    )
    waist_circumference: Optional[float] = Field(
        default=None,
        description="Waist circumference in centimeters (cm), measured at the narrowest part of the waist",
        ge=20.0,
        le=300.0
    )
    hip_circumference: Optional[float] = Field(
        default=None,
        description="Hip circumference in centimeters (cm), measured at the widest part of the hip",
        ge=20.0,
        le=300.0
    )
    waist_to_hip_ratio: Optional[float] = Field(
        default=None,
        description="Waist-to-Hip Ratio (WHR) - calculated as waist circumference (cm) / hip circumference (cm). Used to assess abdominal obesity and health risks. Normal: <0.85 (female), <0.90 (male)",
        ge=0.3,
        le=2.0
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "temperature": 37.2,
                "blood_pressure_systolic": 120,
                "blood_pressure_diastolic": 80,
                "heart_rate": 72,
                "pulse_rate": 72,
                "respiratory_rate": 16,
                "oxygen_saturation": 98.0,
                "weight": 70.5,
                "height": 175.0,
                "bmi": 23.0,
                "waist_circumference": 80.0,
                "hip_circumference": 95.0,
                "waist_to_hip_ratio": 0.84
            }
        }

class VisitCreate(BaseModel):
    patient_id: int
    visit_date: str  # Format: YYYY-MM-DD
    visit_time: Optional[str] = None  # Format: HH:MM
    visit_type: str  # Consultation, Follow-up, Emergency, etc.
    chief_complaint: str
    symptoms: Optional[str] = None
    vitals: Optional[Vitals] = None
    clinical_examination: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment_plan: Optional[str] = None
    medications: Optional[str] = None
    tests_recommended: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None
    # Handwritten notes fields
    note_input_type: Optional[str] = "typed"  # typed, handwritten
    selected_template_id: Optional[int] = None  # For handwritten notes
    # Billing fields
    consultation_fee: Optional[float] = None
    additional_charges: Optional[float] = None
    total_amount: Optional[float] = None
    payment_status: Optional[str] = "unpaid"  # unpaid, paid, partially_paid
    payment_method: Optional[str] = None  # cash, card, upi, bank_transfer
    payment_date: Optional[str] = None
    discount: Optional[float] = None
    notes_billing: Optional[str] = None
    # Case-based architecture - group visits by medical problem
    case_id: Optional[int] = None  # Link to patient case/episode of care
    is_case_opener: bool = False  # True if this is the first visit for a case

class VisitUpdate(BaseModel):
    visit_date: Optional[str] = None
    visit_time: Optional[str] = None
    visit_type: Optional[str] = None
    chief_complaint: Optional[str] = None
    symptoms: Optional[str] = None
    vitals: Optional[Vitals] = None
    clinical_examination: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment_plan: Optional[str] = None
    medications: Optional[str] = None
    tests_recommended: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None
    # Handwritten notes fields
    note_input_type: Optional[str] = None
    selected_template_id: Optional[int] = None
    # Billing fields
    consultation_fee: Optional[float] = None
    additional_charges: Optional[float] = None
    total_amount: Optional[float] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None
    payment_date: Optional[str] = None
    discount: Optional[float] = None
    notes_billing: Optional[str] = None
    # Case-based architecture - group visits by medical problem
    case_id: Optional[int] = None  # Link to patient case/episode of care
    is_case_opener: Optional[bool] = None  # True if this is the first visit for a case


class Visit(BaseModel):
    id: int
    patient_id: int
    doctor_firebase_uid: str
    visit_date: str
    visit_time: Optional[str]
    visit_type: str
    chief_complaint: str
    symptoms: Optional[str]
    vitals: Optional[dict]
    clinical_examination: Optional[str]
    diagnosis: Optional[str]
    treatment_plan: Optional[str]
    medications: Optional[str]
    tests_recommended: Optional[str]
    follow_up_date: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    # New handwritten notes fields
    note_input_type: Optional[str] = "typed"
    selected_template_id: Optional[int] = None
    handwritten_pdf_url: Optional[str] = None
    handwritten_pdf_filename: Optional[str] = None
    # New billing fields
    consultation_fee: Optional[float]
    additional_charges: Optional[float]
    total_amount: Optional[float]
    payment_status: Optional[str]
    payment_method: Optional[str]
    payment_date: Optional[str]
    discount: Optional[float]
    notes_billing: Optional[str]
    # Case-based architecture (replaces deprecated parent_visit_id)
    case_id: Optional[int] = None
    is_case_opener: Optional[bool] = False

# ============================================================
# CASE/EPISODE OF CARE MODELS
# ============================================================

class CaseType(str, Enum):
    ACUTE = "acute"
    CHRONIC = "chronic"
    PREVENTIVE = "preventive"
    PROCEDURE = "procedure"
    OTHER = "other"

class CaseStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    ONGOING = "ongoing"  # For chronic conditions
    REFERRED = "referred"
    CLOSED = "closed"
    ON_HOLD = "on_hold"

class CaseSeverity(str, Enum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"

class CaseOutcome(str, Enum):
    FULLY_RESOLVED = "fully_resolved"
    SIGNIFICANTLY_IMPROVED = "significantly_improved"
    PARTIALLY_IMPROVED = "partially_improved"
    UNCHANGED = "unchanged"
    WORSENED = "worsened"
    REFERRED = "referred"
    PATIENT_DISCONTINUED = "patient_discontinued"

class PhotoType(str, Enum):
    BEFORE = "before"
    PROGRESS = "progress"
    AFTER = "after"

class CaseCreate(BaseModel):
    """Create a new case/episode of care for a patient"""
    case_title: str = Field(..., min_length=3, max_length=200, description="Brief title for the case (e.g., 'Skin Rash - Right Arm')")
    case_type: CaseType = Field(default=CaseType.ACUTE, description="Type of case")
    chief_complaint: str = Field(..., min_length=3, description="Primary complaint for this case")
    initial_diagnosis: Optional[str] = Field(default=None, description="Initial diagnosis if known")
    body_parts_affected: Optional[List[str]] = Field(default_factory=list, description="List of body parts affected")
    severity: CaseSeverity = Field(default=CaseSeverity.MODERATE, description="Severity level")
    priority: int = Field(default=2, ge=1, le=5, description="Priority 1-5 (1=highest)")
    expected_resolution_date: Optional[str] = Field(default=None, description="Expected resolution date (YYYY-MM-DD)")
    next_follow_up_date: Optional[str] = Field(default=None, description="Next follow-up date (YYYY-MM-DD)")
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for categorization")
    notes: Optional[str] = Field(default=None, description="Additional notes")
    
    class Config:
        json_schema_extra = {
            "example": {
                "case_title": "Skin Rash - Right Arm",
                "case_type": "acute",
                "chief_complaint": "Red itchy rash appeared 3 days ago",
                "initial_diagnosis": "Contact Dermatitis",
                "body_parts_affected": ["right_arm"],
                "severity": "moderate",
                "priority": 2,
                "tags": ["dermatology", "allergic"]
            }
        }

class CaseUpdate(BaseModel):
    """Update an existing case"""
    case_title: Optional[str] = Field(default=None, min_length=3, max_length=200)
    case_type: Optional[CaseType] = None
    chief_complaint: Optional[str] = None
    initial_diagnosis: Optional[str] = None
    final_diagnosis: Optional[str] = None
    icd10_codes: Optional[List[str]] = None
    body_parts_affected: Optional[List[str]] = None
    status: Optional[CaseStatus] = None
    severity: Optional[CaseSeverity] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    expected_resolution_date: Optional[str] = None
    next_follow_up_date: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None

class CaseResolve(BaseModel):
    """Resolve/close a case with outcome information"""
    final_diagnosis: Optional[str] = Field(default=None, description="Final diagnosis")
    outcome: CaseOutcome = Field(..., description="Case outcome")
    outcome_notes: Optional[str] = Field(default=None, description="Notes about the outcome")
    patient_satisfaction: Optional[int] = Field(default=None, ge=1, le=5, description="Patient satisfaction rating 1-5")
    
    class Config:
        json_schema_extra = {
            "example": {
                "final_diagnosis": "Contact Dermatitis - Resolved",
                "outcome": "fully_resolved",
                "outcome_notes": "Complete resolution after 2 weeks of topical steroids",
                "patient_satisfaction": 5
            }
        }

class CaseResponse(BaseModel):
    """Full case response model"""
    id: int
    patient_id: int
    doctor_firebase_uid: str
    case_number: str
    case_title: str
    case_type: str
    chief_complaint: str
    initial_diagnosis: Optional[str] = None
    final_diagnosis: Optional[str] = None
    icd10_codes: List[str] = Field(default_factory=list)
    body_parts_affected: List[str] = Field(default_factory=list)
    status: str
    severity: str
    priority: int
    started_at: str
    resolved_at: Optional[str] = None
    expected_resolution_date: Optional[str] = None
    last_visit_date: Optional[str] = None
    next_follow_up_date: Optional[str] = None
    outcome: Optional[str] = None
    outcome_notes: Optional[str] = None
    patient_satisfaction: Optional[int] = None
    total_visits: int = 0
    total_reports: int = 0
    total_photos: int = 0
    medications_prescribed: List[dict] = Field(default_factory=list)
    treatments_given: List[dict] = Field(default_factory=list)
    ai_summary: Optional[str] = None
    ai_treatment_effectiveness: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    created_at: str
    updated_at: str

class CaseSummary(BaseModel):
    """Lightweight case summary for lists"""
    id: int
    patient_id: int
    case_number: str
    case_title: str
    case_type: str
    status: str
    severity: str
    started_at: str
    resolved_at: Optional[str] = None
    last_visit_date: Optional[str] = None
    total_visits: int = 0
    total_photos: int = 0
    has_before_photo: bool = False
    has_after_photo: bool = False

class CasePhotoUpload(BaseModel):
    """Metadata for uploading a case photo"""
    photo_type: PhotoType = Field(..., description="Type of photo: before, progress, or after")
    body_part: Optional[str] = Field(default=None, description="Body part shown in photo")
    body_part_detail: Optional[str] = Field(default=None, description="Detailed description of body part/view")
    description: Optional[str] = Field(default=None, description="Photo description")
    clinical_notes: Optional[str] = Field(default=None, description="Clinical notes about this photo")
    photo_taken_at: Optional[str] = Field(default=None, description="When the photo was taken (ISO datetime)")
    is_primary: bool = Field(default=False, description="Set as primary photo for this type")
    visit_id: Optional[int] = Field(default=None, description="Associate with a specific visit")

class CasePhotoResponse(BaseModel):
    """Case photo response model"""
    id: int
    case_id: int
    visit_id: Optional[int] = None
    doctor_firebase_uid: str
    photo_type: str
    sequence_number: int
    file_name: str
    file_url: str
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    storage_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    body_part: Optional[str] = None
    body_part_detail: Optional[str] = None
    description: Optional[str] = None
    clinical_notes: Optional[str] = None
    photo_taken_at: Optional[str] = None
    uploaded_at: str
    is_primary: bool = False
    comparison_pair_id: Optional[int] = None
    ai_detected_changes: Optional[str] = None
    ai_improvement_score: Optional[float] = None
    created_at: str

class BeforeAfterComparison(BaseModel):
    """Before/after photo comparison for a case"""
    case_id: int
    case_title: str
    case_status: str
    body_part: Optional[str] = None
    before_photo: Optional[CasePhotoResponse] = None
    after_photo: Optional[CasePhotoResponse] = None
    progress_photos: List[CasePhotoResponse] = Field(default_factory=list)
    all_before_photos: List[CasePhotoResponse] = Field(default_factory=list)
    all_after_photos: List[CasePhotoResponse] = Field(default_factory=list)
    ai_comparison_analysis: Optional[str] = None
    visual_improvement_score: Optional[float] = None
    days_between: Optional[int] = None

class CaseAnalysisRequest(BaseModel):
    """Request for AI case analysis"""
    analysis_type: str = Field(default="comprehensive", description="Type: comprehensive, progress_review, outcome_assessment, photo_comparison")
    include_photos: bool = Field(default=True, description="Include photos in analysis")
    include_reports: bool = Field(default=True, description="Include reports in analysis")
    from_date: Optional[str] = Field(default=None, description="Analysis start date (YYYY-MM-DD)")
    to_date: Optional[str] = Field(default=None, description="Analysis end date (YYYY-MM-DD)")
    force_reanalyze: bool = Field(default=False, description="Force new analysis even if one exists")

class CaseAnalysisResponse(BaseModel):
    """Case AI analysis response - data stored in raw_analysis and structured_data"""
    id: int
    case_id: int
    patient_id: int
    analysis_type: str
    model_used: Optional[str] = None
    confidence_score: Optional[float] = None
    visits_analyzed: Optional[List[int]] = Field(default_factory=list)
    reports_analyzed: Optional[List[int]] = Field(default_factory=list)
    photos_analyzed: Optional[List[int]] = Field(default_factory=list)
    raw_analysis: Optional[str] = None  # Raw JSON text from AI
    structured_data: Optional[dict] = None  # Parsed JSON with all analysis fields
    analysis_success: Optional[bool] = True
    analysis_error: Optional[str] = None
    analyzed_at: Optional[str] = None
    created_at: Optional[str] = None
    
    class Config:
        from_attributes = True

class CaseWithDetails(CaseResponse):
    """Extended case response with visits, photos, reports, and analysis"""
    visits: List['Visit'] = Field(default_factory=list)
    photos: List[CasePhotoResponse] = Field(default_factory=list)
    reports: List['Report'] = Field(default_factory=list)
    latest_analysis: Optional[CaseAnalysisResponse] = None
    # Patient info for convenience
    patient_name: Optional[str] = None
    patient_phone: Optional[str] = None

class CaseTimeline(BaseModel):
    """Timeline of case events"""
    case_id: int
    case_title: str
    events: List[dict] = Field(default_factory=list, description="Chronological list of events")
    total_days: Optional[int] = None
    status: str

class AssignVisitToCase(BaseModel):
    """Assign a visit to a case"""
    case_id: int = Field(..., description="Case ID to assign the visit to")
    is_case_opener: bool = Field(default=False, description="Mark as the opening visit for this case")

# Additional models used in routes below
class PatientWithVisits(BaseModel):
    patient: 'PatientProfile'
    visits: list['Visit']
    active_cases: Optional[list['CaseSummary']] = None  # Active cases for this patient

class ReportLinkCreate(BaseModel):
    expires_in_hours: int = 24

class WhatsAppReportRequest(BaseModel):
    expires_in_hours: int = 24
    send_whatsapp: bool = True

class Report(BaseModel):
    id: int
    visit_id: int
    patient_id: int
    doctor_firebase_uid: str
    file_name: str  # NOT NULL in database
    file_url: str   # NOT NULL in database
    file_type: str  # NOT NULL in database
    file_size: int  # NOT NULL in database
    storage_path: Optional[str] = None
    test_type: Optional[str] = None
    notes: Optional[str] = None
    uploaded_at: str  # NOT NULL in database
    created_at: Optional[str] = None

class PatientProfileSendRequest(BaseModel):
    include_visits: bool = True
    include_reports: bool = False
    send_whatsapp: bool = True

# New models for billing
class BillingUpdate(BaseModel):
    consultation_fee: Optional[float] = None
    additional_charges: Optional[float] = None
    discount: Optional[float] = None
    payment_status: str  # unpaid, paid, partially_paid
    payment_method: Optional[str] = None  # cash, card, upi, bank_transfer
    payment_date: Optional[str] = None
    notes_billing: Optional[str] = None

class EarningsFilter(BaseModel):
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None    # YYYY-MM-DD
    payment_status: Optional[str] = None  # paid, unpaid, partially_paid
    visit_type: Optional[str] = None

class EarningsReport(BaseModel):
    period: str
    total_consultations: int
    paid_consultations: int
    unpaid_consultations: int
    total_amount: float
    paid_amount: float
    unpaid_amount: float
    average_per_consultation: float
    breakdown_by_payment_method: dict
    breakdown_by_visit_type: dict

# New models for PDF templates and visit reports
class PDFTemplate(BaseModel):
    id: int
    doctor_firebase_uid: str
    template_name: str
    file_name: str
    file_url: str
    file_size: Optional[int] = None
    storage_path: Optional[str] = None
    is_active: bool = True
    created_at: str
    updated_at: str

class PDFTemplateUpload(BaseModel):
    template_name: str
    is_active: bool = True

class VisitReport(BaseModel):
    id: int
    visit_id: int
    patient_id: int
    doctor_firebase_uid: str
    template_id: Optional[int] = None
    file_name: Optional[str] = None
    file_url: Optional[str] = None
    file_size: Optional[int] = None
    storage_path: Optional[str] = None
    generated_at: Optional[str] = None
    sent_via_whatsapp: bool = False
    whatsapp_message_id: Optional[str] = None

class GenerateVisitReportRequest(BaseModel):
    template_id: Optional[int] = None  # If None, use default template
    send_whatsapp: bool = True
    custom_message: Optional[str] = None

# New models for handwritten notes
class HandwrittenVisitNote(BaseModel):
    id: int
    visit_id: int
    patient_id: int
    doctor_firebase_uid: str
    template_id: Optional[int] = None
    original_template_url: str
    handwritten_pdf_url: str
    handwritten_pdf_filename: str
    handwritten_pdf_size: Optional[int] = None
    storage_path: Optional[str] = None
    created_at: str
    updated_at: str
    sent_via_whatsapp: bool = False
    whatsapp_message_id: Optional[str] = None
    is_active: bool = True
    # Prescription type fields
    note_type: Optional[str] = "handwritten"  # handwritten, typed
    prescription_type: Optional[str] = None  # general, empirical, follow_up

class HandwrittenNoteRequest(BaseModel):
    template_id: int
    send_whatsapp: bool = True
    custom_message: Optional[str] = None

class EmpiricalPrescriptionRequest(BaseModel):
    """Request model for uploading an empirical prescription.
    
    Empirical prescriptions are initial prescriptions given based on clinical 
    assessment before lab results/diagnostic tests are available. They include
    a disclaimer that the prescription may be modified based on test results.
    """
    template_id: Optional[int] = Field(
        default=None,
        description="ID of the PDF template to use for the prescription"
    )
    send_whatsapp: bool = Field(
        default=True,
        description="Whether to send the prescription via WhatsApp to the patient"
    )
    custom_message: Optional[str] = Field(
        default=None,
        description="Optional custom message to include with the WhatsApp message"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "template_id": 1,
                "send_whatsapp": True,
                "custom_message": "Please start this medication immediately and return after tests are done."
            }
        }

# Empirical Prescription Disclaimer
EMPIRICAL_PRESCRIPTION_DISCLAIMER = """
⚠️ IMPORTANT NOTICE - EMPIRICAL PRESCRIPTION ⚠️

This is an empirical (initial) prescription based on clinical assessment.
This prescription may be MODIFIED or CHANGED based on:
• Laboratory test results
• Diagnostic imaging reports  
• Further clinical investigation
• Follow-up examination findings

Please complete the recommended tests and return for follow-up.
Do not discontinue or modify medications without consulting your doctor.
"""

class TemplateSelectionRequest(BaseModel):
    template_id: int

# Calendar Models
class CalendarAppointment(BaseModel):
    visit_id: int
    patient_id: int
    patient_name: str
    follow_up_date: str
    follow_up_time: Optional[str] = None
    original_visit_date: str
    visit_type: str
    chief_complaint: Optional[str] = None  # Can be None/empty
    phone: Optional[str] = None
    notes: Optional[str] = None
    is_overdue: Optional[bool] = False
    days_until_appointment: Optional[int] = None

class MonthlyCalendar(BaseModel):
    year: int
    month: int
    doctor_name: str
    appointments: List[CalendarAppointment]
    total_appointments: int
    appointments_by_date: Dict[str, List[CalendarAppointment]]

class CalendarSummary(BaseModel):
    today: int
    this_week: int
    this_month: int
    next_month: int
    overdue: int

# Notification Models
class NotificationCreate(BaseModel):
    title: str
    message: str
    notification_type: str = "report_upload"
    priority: int = 1  # 1=normal, 2=high, 3=urgent

class Notification(BaseModel):
    id: int
    doctor_firebase_uid: str
    title: str
    message: str
    notification_type: str
    priority: int
    is_read: bool
    created_at: str
    read_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class NotificationUpdate(BaseModel):
    is_read: Optional[bool] = None

class NotificationSummary(BaseModel):
    total_unread: int
    recent_notifications: List[Notification]

# AI Analysis Models
class AIAnalysisResult(BaseModel):
    id: int
    report_id: int
    visit_id: int
    patient_id: int
    doctor_firebase_uid: str
    analysis_type: str
    model_used: str
    confidence_score: float
    raw_analysis: str
    # Enhanced visit-contextual fields
    clinical_correlation: Optional[str] = None
    detailed_findings: Optional[str] = None
    critical_findings: Optional[str] = None
    treatment_evaluation: Optional[str] = None
    # Original fields (keeping for backward compatibility)
    document_summary: Optional[str] = None
    clinical_significance: Optional[str] = None
    correlation_with_patient: Optional[str] = None
    actionable_insights: Optional[str] = None
    patient_communication: Optional[str] = None
    clinical_notes: Optional[str] = None
    key_findings: Optional[List[str]] = None
    analysis_success: bool
    analysis_error: Optional[str] = None
    processing_time_ms: Optional[int] = None
    analyzed_at: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class PatientHistoryAnalysis(BaseModel):
    """Simplified patient history analysis - only essential fields"""
    id: int
    patient_id: int
    doctor_firebase_uid: str
    analysis_period_start: Optional[str] = None
    analysis_period_end: Optional[str] = None
    total_visits: int
    total_reports: int
    model_used: str
    confidence_score: float
    raw_analysis: str  # Contains full AI analysis - frontend parses for display
    analysis_success: bool
    analysis_error: Optional[str] = None
    processing_time_ms: Optional[int] = None
    analyzed_at: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Legacy fields - kept for backward compatibility with existing records
    comprehensive_summary: Optional[str] = None
    medical_trajectory: Optional[str] = None
    chronic_conditions: Optional[List[str]] = None
    recurring_patterns: Optional[List[str]] = None
    treatment_effectiveness: Optional[str] = None
    risk_factors: Optional[List[str]] = None
    recommendations: Optional[List[str]] = None
    significant_findings: Optional[List[str]] = None
    lifestyle_factors: Optional[str] = None
    medication_history: Optional[str] = None
    follow_up_suggestions: Optional[List[str]] = None

class PatientHistoryAnalysisRequest(BaseModel):
    include_visits: bool = True
    include_reports: bool = True
    analysis_period_months: Optional[int] = None  # If specified, only analyze last X months
    priority: Optional[int] = 1

class ConsolidatedAnalysisResult(BaseModel):
    id: int
    visit_id: int
    patient_id: int
    doctor_firebase_uid: str
    report_ids: List[int]
    document_count: int
    model_used: str
    confidence_score: float
    raw_analysis: str
    overall_assessment: Optional[str] = None
    clinical_picture: Optional[str] = None
    integrated_recommendations: Optional[str] = None
    patient_summary: Optional[str] = None
    consolidated_findings: Optional[List[str]] = None
    priority_actions: Optional[List[str]] = None
    analysis_success: bool
    analysis_error: Optional[str] = None
    processing_time_ms: Optional[int] = None
    analyzed_at: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class AIAnalysisRequest(BaseModel):
    report_id: int
    priority: Optional[int] = 1  # 1=normal, 2=high, 3=urgent

class ConsolidatedAnalysisRequest(BaseModel):
    visit_id: int
    report_ids: Optional[List[int]] = None  # If None, analyze all reports for the visit

class AIAnalysisSummary(BaseModel):
    analysis_count: int
    latest_analysis_date: Optional[str] = None
    avg_confidence_score: float
    pending_analyses: int
    failed_analyses: int

class ReportWithAnalysis(BaseModel):
    report: Report
    ai_analysis: Optional[AIAnalysisResult] = None
    analysis_status: str  # "completed", "pending", "failed", "not_requested"


# ============================================================================
# CLINICAL ALERT MODELS
# ============================================================================

class ClinicalAlertBase(BaseModel):
    """Base model for clinical alerts"""
    id: str = Field(..., description="Unique alert identifier (UUID)")
    alert_type: str = Field(..., description="Type of alert: critical_value, drug_interaction, diagnosis_concern, follow_up_urgent, treatment_alert, safety_concern")
    severity: str = Field(..., description="Severity level: high, medium, low")
    title: str = Field(..., description="Brief alert title")
    description: str = Field(..., description="Detailed alert description")
    source_finding: Optional[Dict[str, Any]] = Field(default=None, description="Original finding that triggered the alert")
    recommended_action: Optional[str] = Field(default=None, description="Recommended action to take")
    patient_id: int = Field(..., description="Patient ID")
    visit_id: Optional[int] = Field(default=None, description="Visit ID if applicable")
    analysis_id: Optional[str] = Field(default=None, description="Source AI analysis ID")
    created_at: str = Field(..., description="Alert creation timestamp")


class ClinicalAlert(ClinicalAlertBase):
    """Full clinical alert model including acknowledgment status"""
    acknowledged: bool = Field(default=False, description="Whether alert has been acknowledged")
    acknowledged_at: Optional[str] = Field(default=None, description="When alert was acknowledged")
    acknowledged_by: Optional[str] = Field(default=None, description="Doctor who acknowledged")
    acknowledgment_notes: Optional[str] = Field(default=None, description="Notes added during acknowledgment")


class AlertListResponse(BaseModel):
    """Response model for alert list endpoints"""
    alerts: List[ClinicalAlert] = Field(..., description="List of clinical alerts")
    count: int = Field(..., description="Number of alerts returned")

    class Config:
        json_schema_extra = {
            "example": {
                "alerts": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "alert_type": "critical_value",
                        "severity": "high",
                        "title": "Critical Hemoglobin Level",
                        "description": "Hemoglobin at 6.2 g/dL is critically low",
                        "recommended_action": "Consider blood transfusion",
                        "patient_id": 123,
                        "visit_id": 456,
                        "created_at": "2026-01-17T10:30:00Z",
                        "acknowledged": False
                    }
                ],
                "count": 1
            }
        }


class AlertCountsResponse(BaseModel):
    """Response model for alert counts endpoint"""
    counts: Dict[str, int] = Field(..., description="Alert counts by severity")
    has_alerts: bool = Field(..., description="Whether any unacknowledged alerts exist")
    has_high_priority: bool = Field(..., description="Whether high severity alerts exist")

    class Config:
        json_schema_extra = {
            "example": {
                "counts": {"high": 2, "medium": 5, "low": 3, "total": 10},
                "has_alerts": True,
                "has_high_priority": True
            }
        }


class AlertAcknowledgeResponse(BaseModel):
    """Response model for alert acknowledgment"""
    message: str = Field(..., description="Success message")
    alert_id: str = Field(..., description="ID of acknowledged alert")


class AlertAcknowledgeAllResponse(BaseModel):
    """Response model for bulk alert acknowledgment"""
    message: str = Field(..., description="Success message")
    patient_id: int = Field(..., description="Patient ID")
    acknowledged_count: int = Field(..., description="Number of alerts acknowledged")


class AlertHistoryResponse(BaseModel):
    """Response model for alert history"""
    alerts: List[ClinicalAlert] = Field(..., description="List of alerts including acknowledged ones")
    count: int = Field(..., description="Total alerts returned")
    patient_id: int = Field(..., description="Patient ID")
    days: int = Field(..., description="Number of days of history")


class VisitAlertsResponse(BaseModel):
    """Response model for visit-specific alerts"""
    alerts: List[ClinicalAlert] = Field(..., description="Alerts for the visit")
    count: int = Field(..., description="Number of alerts")
    visit_id: int = Field(..., description="Visit ID")


# ============================================================================
# END CLINICAL ALERT MODELS
# ============================================================================


# Enhanced exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"Global exception handler caught: {type(exc).__name__}: {exc}")
    print(f"Traceback: {traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"detail": f"Internal server error: {str(exc)}"})

@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    print(f"Validation error: {exc}")
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# Authentication dependency
async def get_current_doctor(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        # Verify Firebase ID token asynchronously
        decoded_token = await firebase_manager.verify_id_token(credentials.credentials)
        if not decoded_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        firebase_uid = decoded_token['uid']
        email = decoded_token['email']
        
        # Get doctor profile from Supabase using database manager
        doctor = await db.get_doctor_by_firebase_uid(firebase_uid)
        if doctor is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Doctor profile not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        return doctor
    except TokenExpiredError as e:
        print(f"Token expired: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase ID token has expired. Please refresh your authentication.",
            headers={"WWW-Authenticate": "Bearer", "X-Auth-Error": "token_expired"},
        )
    except TokenInvalidError as e:
        print(f"Invalid token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase ID token format.",
            headers={"WWW-Authenticate": "Bearer", "X-Auth-Error": "token_invalid"},
        )
    except TokenVerificationError as e:
        print(f"Token verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed. Please try logging in again.",
            headers={"WWW-Authenticate": "Bearer", "X-Auth-Error": "verification_failed"},
        )
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        print(f"Unexpected authentication error: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed due to unexpected error",
            headers={"WWW-Authenticate": "Bearer"},
        )

# Simple frontdesk authentication - for production, consider using JWT tokens
async def get_current_frontdesk_user(frontdesk_id: int) -> Dict[str, Any]:
    """Get frontdesk user by ID - simple authentication for now"""
    try:
        frontdesk_user = await db.get_frontdesk_user_by_id(frontdesk_id)
        if not frontdesk_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Frontdesk user not found"
            )
        
        if not frontdesk_user.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Frontdesk account is deactivated"
            )
        
        return frontdesk_user
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting frontdesk user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error"
        )


async def get_current_pharmacy_user(pharmacy_id: int) -> Dict[str, Any]:
    """Get pharmacy user by ID - temporary simple auth"""
    try:
        pharmacy_user = await db.get_pharmacy_user_by_id(pharmacy_id)
        if not pharmacy_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Pharmacy account not found or inactive"
            )

        if not pharmacy_user.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Pharmacy account is deactivated"
            )

        return pharmacy_user
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting pharmacy user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error"
        )

# API Routes with database manager
@app.post(
    "/doctors", 
    response_model=dict, 
    status_code=status.HTTP_201_CREATED,
    tags=["Authentication"],
    summary="Register a new doctor",
    description="Create a new doctor account with Firebase authentication"
)
async def register_doctor(doctor: DoctorRegister):
    firebase_user = None
    try:
        print(f"=== REGISTRATION START ===")
        print(f"Received doctor data: {doctor.model_dump()}")
        
        # Validate required fields
        if not doctor.email or not doctor.password or not doctor.first_name or not doctor.last_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email, password, first_name, and last_name are required"
            )
        
        # Validate password length
        if len(doctor.password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters long"
            )
        
        print("Creating Firebase user...")
        # Create user in Firebase asynchronously
        firebase_user = await firebase_manager.create_user(
            email=doctor.email,
            password=doctor.password,
            display_name=f"{doctor.first_name} {doctor.last_name}"
        )
        
        print(f"Firebase user created successfully: {firebase_user.uid}")
        
        # Check if doctor profile already exists in Supabase
        print("Checking for existing doctor in Supabase...")
        existing_doctor = await db.get_doctor_by_email(doctor.email)
        if existing_doctor:
            print(f"Doctor already exists, deleting Firebase user: {firebase_user.uid}")
            await firebase_manager.delete_user(firebase_user.uid)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Prepare doctor data for Supabase
        doctor_data = {
            "firebase_uid": firebase_user.uid,
            "email": doctor.email,
            "first_name": doctor.first_name,
            "last_name": doctor.last_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add optional fields only if they have values
        if doctor.specialization:
            doctor_data["specialization"] = doctor.specialization
        if doctor.license_number:
            doctor_data["license_number"] = doctor.license_number
        if doctor.phone:
            doctor_data["phone"] = doctor.phone
        # Always include hospital_name, convert empty strings to None
        doctor_data["hospital_name"] = doctor.hospital_name if doctor.hospital_name and doctor.hospital_name.strip() else None
        
        print(f"Final doctor_data before database insert: {doctor_data}")
        print(f"Hospital name value: '{doctor.hospital_name}' (type: {type(doctor.hospital_name)})")
        
        # Create doctor using database manager
        created_doctor = await db.create_doctor(doctor_data)
        if created_doctor:
            print(f"Registration successful for: {doctor.email}")
            return {"message": "Doctor registered successfully", "firebase_uid": firebase_user.uid}
        else:
            print("Supabase insert failed - no data returned")
            if firebase_user:
                await firebase_manager.delete_user(firebase_user.uid)
                print(f"Cleaned up Firebase user: {firebase_user.uid}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create doctor profile in database"
            )
            
    except auth.EmailAlreadyExistsError as e:
        print(f"Firebase email already exists error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered in Firebase"
        )
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        print(f"Unexpected registration error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        
        # Cleanup Firebase user if it was created
        if firebase_user:
            try:
                await firebase_manager.delete_user(firebase_user.uid)
                print(f"Cleaned up Firebase user after error: {firebase_user.uid}")
            except Exception as cleanup_error:
                print(f"Failed to cleanup Firebase user: {cleanup_error}")
        
        # Check for specific error types
        error_str = str(e).lower()
        if "duplicate key" in error_str or "unique constraint" in error_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="License number already exists"
            )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration error: {str(e)}"
        )

# Test endpoint for debugging
@app.get("/test")
async def test_endpoint():
    try:
        # Test database connection using database manager
        db_result = await db.test_connection()
        
        # Test WhatsApp connection
        whatsapp_result = await whatsapp_service.test_connection()
        
        return {
            "message": "API is working",
            "database_connection": db_result["status"],
            "firebase_connection": "OK",
            "whatsapp_connection": whatsapp_result["success"],
            "whatsapp_details": whatsapp_result
        }
    except Exception as e:
        return {
            "message": "API test failed",
            "error": str(e),
            "traceback": traceback.format_exc()
        }



@app.post("/validate-token", response_model=dict)
async def validate_token(token_data: FirebaseToken):
    """Validate Firebase ID token and return user info"""
    try:
        # Verify the Firebase ID token asynchronously
        decoded_token = await firebase_manager.verify_id_token(token_data.id_token)
        
        firebase_uid = decoded_token['uid']
        email = decoded_token['email']
        
        # Check if doctor profile exists using database manager
        doctor = await db.get_doctor_by_firebase_uid(firebase_uid)
        if not doctor:
            return {
                "valid": False,
                "error": "Doctor profile not found",
                "error_code": "profile_not_found"
            }
        
        # Token is valid and doctor exists
        return {
            "valid": True,
            "firebase_uid": firebase_uid,
            "email": email,
            "doctor_name": f"Dr. {doctor['first_name']} {doctor['last_name']}",
            "expires_at": decoded_token.get('exp'),  # Token expiration timestamp
            "issued_at": decoded_token.get('iat')    # Token issued timestamp
        }
        
    except TokenExpiredError:
        return {
            "valid": False,
            "error": "Firebase ID token has expired",
            "error_code": "token_expired",
            "requires_refresh": True
        }
    except TokenInvalidError:
        return {
            "valid": False,
            "error": "Invalid Firebase ID token format",
            "error_code": "token_invalid",
            "requires_reauth": True
        }
    except TokenVerificationError as e:
        return {
            "valid": False,
            "error": f"Token verification failed: {str(e)}",
            "error_code": "verification_failed",
            "requires_reauth": True
        }
    except Exception as e:
        print(f"Unexpected token validation error: {e}")
        return {
            "valid": False,
            "error": "Token validation failed due to unexpected error",
            "error_code": "unexpected_error",
            "requires_reauth": True
        }

@app.post("/login", response_model=dict)
async def login_doctor(token_data: FirebaseToken):
    try:
        # Verify the Firebase ID token asynchronously
        decoded_token = await firebase_manager.verify_id_token(token_data.id_token)
            
        firebase_uid = decoded_token['uid']
        email = decoded_token['email']
        
        # Check if doctor profile exists using database manager
        doctor = await db.get_doctor_by_firebase_uid(firebase_uid)
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor profile not found"
            )
        
        return {
            "message": "Login successful",
            "firebase_uid": firebase_uid,
            "email": email,
            "id_token": token_data.id_token,
            "doctor_name": f"Dr. {doctor['first_name']} {doctor['last_name']}"
        }
        
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase ID token has expired. Please refresh your authentication.",
            headers={"X-Auth-Error": "token_expired"}
        )
    except TokenInvalidError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase ID token format.",
            headers={"X-Auth-Error": "token_invalid"}
        )
    except TokenVerificationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {str(e)}",
            headers={"X-Auth-Error": "verification_failed"}
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected login error: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login error: {str(e)}"
        )

@app.get("/profile", response_model=DoctorProfile)
async def get_doctor_profile(current_doctor = Depends(get_current_doctor)):
    return DoctorProfile(
        firebase_uid=current_doctor["firebase_uid"],
        email=current_doctor["email"],
        first_name=current_doctor["first_name"],
        last_name=current_doctor["last_name"],
        specialization=current_doctor["specialization"],
        license_number=current_doctor["license_number"],
        phone=current_doctor["phone"],
        hospital_name=current_doctor.get("hospital_name"),
        pathology_lab_name=current_doctor.get("pathology_lab_name"),
        pathology_lab_phone=current_doctor.get("pathology_lab_phone"),
        radiology_lab_name=current_doctor.get("radiology_lab_name"),
        radiology_lab_phone=current_doctor.get("radiology_lab_phone"),
        ai_enabled=current_doctor.get("ai_enabled", True),
        created_at=current_doctor["created_at"],
        updated_at=current_doctor["updated_at"]
    )

@app.put("/profile", response_model=dict)
async def update_doctor_profile(
    doctor_update: DoctorUpdate,
    current_doctor = Depends(get_current_doctor)
):
    # Get only the fields that were provided
    update_data = doctor_update.model_dump(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )
    
    # Add updated timestamp
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # Update using database manager
    success = await db.update_doctor(current_doctor["firebase_uid"], update_data)
    if success:
        return {"message": "Profile updated successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile"
        )

@app.patch(
    "/profile/ai-enabled", 
    response_model=dict,
    tags=["Authentication"],
    summary="Toggle AI analysis setting",
    description="Enable or disable AI-powered analysis for the doctor's patients"
)
async def toggle_ai_setting(
    current_doctor = Depends(get_current_doctor)
):
    """Toggle AI analysis on/off for the doctor"""
    try:
        # Get current AI setting (default to True if not set)
        current_setting = current_doctor.get("ai_enabled", True)
        new_setting = not current_setting
        
        # Update the setting
        update_data = {
            "ai_enabled": new_setting,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        success = await db.update_doctor(current_doctor["firebase_uid"], update_data)
        
        if success:
            return {
                "message": f"AI analysis {'enabled' if new_setting else 'disabled'}",
                "ai_enabled": new_setting
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update AI setting"
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error toggling AI setting: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to toggle AI setting: {str(e)}"
        )

@app.get("/profile/ai-status", response_model=dict)
async def get_ai_status(current_doctor = Depends(get_current_doctor)):
    """Get current AI analysis status for the doctor"""
    ai_enabled = current_doctor.get("ai_enabled", True)
    return {
        "ai_enabled": ai_enabled,
        "message": "AI analysis is enabled" if ai_enabled else "AI analysis is disabled"
    }

# Helper functions for password hashing
def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with salt"""
    salt = os.getenv("PASSWORD_SALT", "default_salt_change_in_production")
    return hashlib.sha256((password + salt).encode()).hexdigest()

def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return hash_password(password) == hashed_password


def check_ai_enabled(doctor: dict) -> None:
    """Check if AI is enabled for the doctor, raise exception if not"""
    if not doctor.get("ai_enabled", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "AI analysis is disabled for your account",
                "action_required": "Enable AI in Settings → Profile → Toggle AI Analysis",
                "ai_enabled": False,
                "endpoint_to_enable": "/profile/toggle-ai"
            }
        )


def generate_invoice_number() -> str:
    """Generate a human-readable invoice number"""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"INV-{timestamp}-{uuid.uuid4().hex[:6].upper()}"


def parse_medications_text_to_items(medications_text: Optional[str]) -> List[Dict[str, Any]]:
    """Parse free-text medications into structured items"""
    if not medications_text:
        return []
    entries = re.split(r"[\n;]+", medications_text)
    items: List[Dict[str, Any]] = []
    for entry in entries:
        raw = entry.strip()
        if not raw:
            continue
        item_name = raw
        item: Dict[str, Any] = {
            "name": item_name,
            "medicine_name": item_name
        }
        if "-" in raw:
            name_part, detail_part = raw.split("-", 1)
            cleaned_name = name_part.strip()
            item["name"] = cleaned_name
            item["medicine_name"] = cleaned_name
            if detail_part.strip():
                item["details"] = detail_part.strip()
        elif ":" in raw:
            name_part, detail_part = raw.split(":", 1)
            cleaned_name = name_part.strip()
            item["name"] = cleaned_name
            item["medicine_name"] = cleaned_name
            if detail_part.strip():
                item["details"] = detail_part.strip()
        items.append(item)
    return items


def normalize_medication_items(raw_items: Optional[Any]) -> List[Dict[str, Any]]:
    if not raw_items:
        return []
    normalized: List[Dict[str, Any]] = []
    if isinstance(raw_items, str):
        try:
            raw_items = json.loads(raw_items)
        except (json.JSONDecodeError, TypeError):
            raw_items = []
    if not isinstance(raw_items, list):
        return []
    for entry in raw_items:
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("medicine_name")
            if not name:
                name = str(entry)
            normalized.append({
                **entry,
                "name": name,
                "medicine_name": entry.get("medicine_name") or name
            })
        else:
            name = str(entry)
            normalized.append({
                "name": name,
                "medicine_name": name
            })
    return normalized


async def sync_pharmacy_prescription_from_visit(visit: Dict[str, Any], doctor: Dict[str, Any], patient: Dict[str, Any]) -> None:
    """Create or update pharmacy prescription data whenever visit medications change"""
    try:
        if not visit or not doctor or not patient:
            print("❌ Sync skipped: Missing required data (visit, doctor, or patient)")
            return

        visit_id = visit.get("id")
        if not visit_id:
            print("❌ Sync skipped: No visit ID found")
            return

        medications_text = visit.get("medications")
        existing_prescription = await db.get_pharmacy_prescription_by_visit(visit_id)

        if medications_text and medications_text.strip():
            hospital_name = doctor.get("hospital_name")
            if not hospital_name:
                print(f"❌ Doctor {doctor.get('firebase_uid')} missing hospital name; skipping pharmacy sync")
                return

            parsed_items = parse_medications_text_to_items(medications_text)
            doctor_name = f"Dr. {doctor.get('first_name', '').strip()} {doctor.get('last_name', '').strip()}".strip()
            timestamp = datetime.now(timezone.utc).isoformat()

            prescription_payload: Dict[str, Any] = {
                "visit_id": visit_id,
                "patient_id": visit.get("patient_id"),
                "patient_name": f"{patient.get('first_name', '')} {patient.get('last_name', '')}".strip(),
                "patient_phone": patient.get("phone"),
                "doctor_firebase_uid": doctor.get("firebase_uid"),
                "doctor_name": doctor_name,
                "doctor_specialization": doctor.get("specialization"),
                "hospital_name": hospital_name,
                "medications_text": medications_text.strip(),
                "medications_json": parsed_items,
                "status": "pending",
                "visit_date": visit.get("visit_date"),
                "visit_type": visit.get("visit_type"),
                "notes": visit.get("notes") or visit.get("treatment_plan"),
                "updated_at": timestamp,
                "created_at": timestamp
            }

            assigned_pharmacy_id: Optional[int] = None
            if existing_prescription and existing_prescription.get("pharmacy_id"):
                assigned_pharmacy_id = existing_prescription["pharmacy_id"]
            else:
                pharmacies = await db.get_pharmacy_users_by_hospital(hospital_name)
                if pharmacies:
                    assigned_pharmacy_id = pharmacies[0]["id"]

            if assigned_pharmacy_id:
                prescription_payload["pharmacy_id"] = assigned_pharmacy_id

            if existing_prescription:
                if existing_prescription.get("status") == "dispensed":
                    print(f"Prescription for visit {visit_id} already dispensed; skipping update")
                    return
                # Preserve original creation timestamp
                prescription_payload.pop("created_at")
                await db.update_pharmacy_prescription(existing_prescription["id"], prescription_payload)
                print(f"✅ Updated pharmacy prescription for visit {visit_id}")
            else:
                created_prescription = await db.create_pharmacy_prescription(prescription_payload)
                if created_prescription:
                    print(f"✅ Created pharmacy prescription for visit {visit_id}")
                else:
                    print(f"❌ Failed to create pharmacy prescription for visit {visit_id}")
                    
        else:
            # No medications -> cancel pending prescriptions if applicable
            if existing_prescription and existing_prescription.get("status") not in ["dispensed", "cancelled"]:
                await db.update_pharmacy_prescription(existing_prescription["id"], {
                    "status": "cancelled",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "notes": "Automatically cancelled because medications were removed from the visit"
                })
    except Exception as e:
        print(f"Error syncing pharmacy prescription for visit {visit.get('id')}: {e}")
        print(f"Traceback: {traceback.format_exc()}")


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def map_inventory_item(item: Dict[str, Any]) -> PharmacyInventoryItem:
    supplier_payload = item.get("supplier")
    supplier_info = None
    if isinstance(supplier_payload, dict) and supplier_payload.get("id") is not None:
        supplier_info = PharmacyInventorySupplierInfo(
            id=supplier_payload.get("id"),
            name=supplier_payload.get("name", ""),
            contact_person=supplier_payload.get("contact_person"),
            phone=supplier_payload.get("phone"),
            email=supplier_payload.get("email")
        )

    return PharmacyInventoryItem(
        id=item.get("id"),
        pharmacy_id=item.get("pharmacy_id"),
        medicine_name=item.get("medicine_name", ""),
        sku=item.get("sku"),
        batch_number=item.get("batch_number"),
        expiry_date=item.get("expiry_date"),
        stock_quantity=safe_int(item.get("stock_quantity")) or 0,
        reorder_level=safe_int(item.get("reorder_level")),
        unit=item.get("unit"),
        purchase_price=safe_float(item.get("purchase_price")),
        selling_price=safe_float(item.get("selling_price")),
        tax_percent=safe_float(item.get("tax_percent")),
        supplier_id=safe_int(item.get("supplier_id")),
        supplier=supplier_info,
        created_at=item.get("created_at", datetime.now(timezone.utc).isoformat()),
        updated_at=item.get("updated_at", datetime.now(timezone.utc).isoformat())
    )


def map_prescription_to_view(prescription: Dict[str, Any]) -> PharmacyPrescriptionView:
    meds_json = normalize_medication_items(prescription.get("medications_json"))

    return PharmacyPrescriptionView(
        id=prescription.get("id"),
        visit_id=prescription.get("visit_id"),
        patient_id=prescription.get("patient_id"),
        patient_name=prescription.get("patient_name", ""),
        patient_phone=prescription.get("patient_phone"),
        doctor_firebase_uid=prescription.get("doctor_firebase_uid", ""),
        doctor_name=prescription.get("doctor_name"),
        doctor_specialization=prescription.get("doctor_specialization"),
        hospital_name=prescription.get("hospital_name", ""),
        pharmacy_id=prescription.get("pharmacy_id"),
        medications_text=prescription.get("medications_text"),
    medications_json=meds_json,
        status=prescription.get("status", "pending"),
        visit_date=prescription.get("visit_date"),
        visit_type=prescription.get("visit_type"),
        notes=prescription.get("notes"),
        total_estimated_amount=safe_float(prescription.get("total_estimated_amount")),
        created_at=prescription.get("created_at", datetime.now(timezone.utc).isoformat()),
        updated_at=prescription.get("updated_at", datetime.now(timezone.utc).isoformat()),
        dispensed_at=prescription.get("dispensed_at")
    )


def map_invoice_to_response(invoice: Dict[str, Any]) -> PharmacyInvoiceResponse:
    invoice_items = normalize_medication_items(invoice.get("items"))

    return PharmacyInvoiceResponse(
        id=invoice.get("id"),
        pharmacy_id=invoice.get("pharmacy_id"),
        prescription_id=invoice.get("prescription_id"),
        invoice_number=invoice.get("invoice_number", ""),
        items=invoice_items,
        subtotal=safe_float(invoice.get("subtotal")) or 0.0,
        tax=safe_float(invoice.get("tax")) or 0.0,
        discount=safe_float(invoice.get("discount")) or 0.0,
        total_amount=safe_float(invoice.get("total_amount")) or 0.0,
        payment_method=invoice.get("payment_method"),
        status=invoice.get("status", "paid"),
        generated_at=invoice.get("generated_at", datetime.now(timezone.utc).isoformat()),
        created_by=invoice.get("created_by"),
        notes=invoice.get("notes"),
        patient_id=invoice.get("patient_id"),
        patient_name=invoice.get("patient_name"),
        patient_phone=invoice.get("patient_phone"),
        prescription_date=invoice.get("prescription_date"),
    )


def map_pharmacy_profile(pharmacy_user: Dict[str, Any]) -> PharmacyProfile:
    return PharmacyProfile(
        id=pharmacy_user.get("id"),
        name=pharmacy_user.get("name", ""),
        phone=pharmacy_user.get("phone"),
        hospital_name=pharmacy_user.get("hospital_name", ""),
        username=pharmacy_user.get("username", ""),
        is_active=pharmacy_user.get("is_active", True),
        created_at=pharmacy_user.get("created_at", datetime.now(timezone.utc).isoformat()),
        updated_at=pharmacy_user.get("updated_at", datetime.now(timezone.utc).isoformat()),
        last_login_at=pharmacy_user.get("last_login_at")
    )


def map_supplier_record(supplier: Dict[str, Any]) -> PharmacySupplierResponse:
    return PharmacySupplierResponse(
        id=supplier.get("id"),
        pharmacy_id=supplier.get("pharmacy_id"),
        name=supplier.get("name", ""),
        contact_person=supplier.get("contact_person"),
        phone=supplier.get("phone"),
        email=supplier.get("email"),
        address=supplier.get("address"),
        notes=supplier.get("notes"),
        is_active=bool(supplier.get("is_active", True)),
        created_at=supplier.get("created_at", datetime.now(timezone.utc).isoformat()),
        updated_at=supplier.get("updated_at", datetime.now(timezone.utc).isoformat()),
    )

# Frontdesk Authentication Routes
@app.post("/frontdesk/register", response_model=dict)
async def register_frontdesk_user(frontdesk: FrontdeskRegister):
    try:
        print(f"=== FRONTDESK REGISTRATION START ===")
        print(f"Received frontdesk data: {frontdesk.model_dump()}")
        
        # Validate required fields
        if not frontdesk.name or not frontdesk.phone or not frontdesk.hospital_name or not frontdesk.username or not frontdesk.password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="All fields are required"
            )
        
        # Validate password length
        if len(frontdesk.password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters long"
            )
        
        # Check if username already exists
        print("Checking for existing username...")
        existing_frontdesk = await db.get_frontdesk_user_by_username(frontdesk.username)
        if existing_frontdesk:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists"
            )
        
        # Hash the password
        password_hash = hash_password(frontdesk.password)
        
        # Prepare frontdesk data for database
        frontdesk_data = {
            "name": frontdesk.name,
            "phone": frontdesk.phone,
            "hospital_name": frontdesk.hospital_name,
            "username": frontdesk.username,
            "password_hash": password_hash,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        print(f"Creating frontdesk user with data: {frontdesk_data}")
        
        # Create frontdesk user
        created_frontdesk = await db.create_frontdesk_user(frontdesk_data)
        if created_frontdesk:
            print(f"Frontdesk registration successful for: {frontdesk.username}")
            return {"message": "Frontdesk user registered successfully", "frontdesk_id": created_frontdesk["id"]}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create frontdesk user"
            )
            
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        print(f"Unexpected frontdesk registration error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration error: {str(e)}"
        )

@app.post("/frontdesk/login", response_model=dict)
async def login_frontdesk_user(frontdesk_login: FrontdeskLogin):
    try:
        print(f"=== FRONTDESK LOGIN START ===")
        print(f"Login attempt for username: {frontdesk_login.username}")
        
        # Validate required fields
        if not frontdesk_login.username or not frontdesk_login.password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username and password are required"
            )
        
        # Get frontdesk user by username
        frontdesk_user = await db.get_frontdesk_user_by_username(frontdesk_login.username)
        if not frontdesk_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        # Verify password
        if not verify_password(frontdesk_login.password, frontdesk_user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        # Check if user is active
        if not frontdesk_user.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is deactivated"
            )
        
        print(f"Frontdesk login successful for: {frontdesk_login.username}")
        
        # Return frontdesk user profile (without password hash)
        frontdesk_profile = FrontdeskProfile(
            id=frontdesk_user["id"],
            name=frontdesk_user["name"],
            phone=frontdesk_user["phone"],
            hospital_name=frontdesk_user["hospital_name"],
            username=frontdesk_user["username"],
            is_active=frontdesk_user["is_active"],
            created_at=frontdesk_user["created_at"],
            updated_at=frontdesk_user["updated_at"]
        )
        
        return {
            "message": "Login successful",
            "frontdesk_user": frontdesk_profile.model_dump()
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        print(f"Unexpected frontdesk login error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login error: {str(e)}"
        )

# Pharmacy Authentication & Dashboard Routes
@app.post("/pharmacy/register", response_model=dict)
async def register_pharmacy_user(pharmacy: PharmacyRegister):
    try:
        if not pharmacy.name or not pharmacy.hospital_name or not pharmacy.username or not pharmacy.password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Name, hospital_name, username and password are required"
            )

        if len(pharmacy.password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters long"
            )

        existing = await db.get_pharmacy_user_by_username(pharmacy.username)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists"
            )

        timestamp = datetime.now(timezone.utc).isoformat()
        pharmacy_data = {
            "name": pharmacy.name,
            "phone": pharmacy.phone,
            "hospital_name": pharmacy.hospital_name,
            "username": pharmacy.username,
            "password_hash": hash_password(pharmacy.password),
            "is_active": True,
            "created_at": timestamp,
            "updated_at": timestamp
        }

        created_pharmacy = await db.create_pharmacy_user(pharmacy_data)
        if not created_pharmacy:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create pharmacy user"
            )

        return {
            "message": "Pharmacy registered successfully",
            "pharmacy_id": created_pharmacy["id"]
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected pharmacy registration error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pharmacy registration error: {str(e)}"
        )


@app.post("/pharmacy/login", response_model=dict)
async def login_pharmacy_user(pharmacy_login: PharmacyLogin):
    try:
        if not pharmacy_login.username or not pharmacy_login.password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username and password are required"
            )

        pharmacy_user = await db.get_pharmacy_user_by_username(pharmacy_login.username)
        if not pharmacy_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )

        if not verify_password(pharmacy_login.password, pharmacy_user.get("password_hash", "")):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )

        if not pharmacy_user.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Pharmacy account is deactivated"
            )

        timestamp = datetime.now(timezone.utc).isoformat()
        await db.update_pharmacy_user(pharmacy_user["id"], {
            "last_login_at": timestamp,
            "updated_at": timestamp
        })

        refreshed = await db.get_pharmacy_user_by_id(pharmacy_user["id"])
        profile = map_pharmacy_profile(refreshed or pharmacy_user)

        return {
            "message": "Login successful",
            "pharmacy_user": profile.model_dump()
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected pharmacy login error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login error: {str(e)}"
        )


@app.get("/pharmacy/{pharmacy_id}/profile", response_model=PharmacyProfile)
async def get_pharmacy_profile(pharmacy_id: int):
    pharmacy_user = await get_current_pharmacy_user(pharmacy_id)
    return map_pharmacy_profile(pharmacy_user)


@app.get("/pharmacy/{pharmacy_id}/dashboard", response_model=PharmacyDashboardSummary)
async def get_pharmacy_dashboard(pharmacy_id: int):
    pharmacy_user = await get_current_pharmacy_user(pharmacy_id)
    profile = map_pharmacy_profile(pharmacy_user)

    hospital_name = profile.hospital_name
    # Get all prescriptions for this hospital
    all_prescriptions = await db.get_pharmacy_prescriptions(hospital_name, None)
    # Include both unassigned and assigned to this pharmacy
    prescriptions = [
        p for p in all_prescriptions 
        if p.get("pharmacy_id") is None or p.get("pharmacy_id") == pharmacy_id
    ]

    pending_prescriptions = len([p for p in prescriptions if (p.get("status") or "").lower() == "pending"])
    ready_prescriptions = len([p for p in prescriptions if (p.get("status") or "").lower() == "ready"])

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dispensed_today = len([
        p for p in prescriptions
        if (p.get("status") or "").lower() == "dispensed"
        and ((p.get("dispensed_at") or p.get("updated_at") or "")[:10] == today_str)
    ])

    inventory_raw = await db.get_pharmacy_inventory_items(pharmacy_id)
    inventory_items = [map_inventory_item(item) for item in inventory_raw]
    inventory_low_stock = len([
        item for item in inventory_items
        if item.reorder_level is not None and item.reorder_level > 0 and item.stock_quantity <= item.reorder_level
    ])

    total_inventory_items = len(inventory_items)

    month_start = datetime.now(timezone.utc).replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    month_end = next_month - timedelta(days=1)

    sales_today_summary = await db.get_pharmacy_invoice_summary(pharmacy_id, start_date=today_str, end_date=today_str)
    sales_month_summary = await db.get_pharmacy_invoice_summary(
        pharmacy_id,
        start_date=month_start.strftime("%Y-%m-%d"),
        end_date=month_end.strftime("%Y-%m-%d")
    )

    return PharmacyDashboardSummary(
        pharmacy_profile=profile,
        pending_prescriptions=pending_prescriptions,
        ready_prescriptions=ready_prescriptions,
        dispensed_today=dispensed_today,
        inventory_low_stock=inventory_low_stock,
        total_inventory_items=total_inventory_items,
        sales_today=sales_today_summary.get("total_sales", 0.0),
        sales_month=sales_month_summary.get("total_sales", 0.0)
    )


@app.get("/pharmacy/{pharmacy_id}/prescriptions", response_model=List[PharmacyPrescriptionView])
async def list_pharmacy_prescriptions(
    pharmacy_id: int,
    status: Optional[str] = None,
    include_unassigned: bool = True
):
    pharmacy_user = await get_current_pharmacy_user(pharmacy_id)
    hospital_name = pharmacy_user["hospital_name"]

    # Get all prescriptions for this hospital
    prescriptions = await db.get_pharmacy_prescriptions(hospital_name, None)
    
    # Filter prescriptions based on pharmacy assignment
    if include_unassigned:
        # Include both unassigned prescriptions and prescriptions assigned to this pharmacy
        prescriptions = [
            p for p in prescriptions 
            if p.get("pharmacy_id") is None or p.get("pharmacy_id") == pharmacy_id
        ]
    else:
        # Only include prescriptions specifically assigned to this pharmacy
        prescriptions = [p for p in prescriptions if p.get("pharmacy_id") == pharmacy_id]

    # Filter by status if specified
    if status:
        desired = {s.strip().lower() for s in status.split(",") if s.strip()}
        prescriptions = [
            p for p in prescriptions
            if (p.get("status") or "").lower() in desired
        ]

    return [map_prescription_to_view(prescription) for prescription in prescriptions]


@app.get("/pharmacy/{pharmacy_id}/prescriptions/{prescription_id}", response_model=PharmacyPrescriptionView)
async def get_pharmacy_prescription(pharmacy_id: int, prescription_id: int):
    pharmacy_user = await get_current_pharmacy_user(pharmacy_id)
    prescription = await db.get_pharmacy_prescription_by_id(prescription_id)

    if not prescription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found")

    if prescription.get("hospital_name") != pharmacy_user.get("hospital_name"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied for this prescription")

    if prescription.get("pharmacy_id") not in (None, pharmacy_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Prescription is assigned to a different pharmacy")

    return map_prescription_to_view(prescription)


@app.patch("/pharmacy/{pharmacy_id}/prescriptions/{prescription_id}/claim", response_model=dict)
async def claim_pharmacy_prescription(pharmacy_id: int, prescription_id: int):
    pharmacy_user = await get_current_pharmacy_user(pharmacy_id)
    prescription = await db.get_pharmacy_prescription_by_id(prescription_id)

    if not prescription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found")

    if prescription.get("hospital_name") != pharmacy_user.get("hospital_name"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot claim prescription from another hospital")

    if prescription.get("pharmacy_id") not in (None, pharmacy_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Prescription already assigned to another pharmacy")

    timestamp = datetime.now(timezone.utc).isoformat()
    await db.update_pharmacy_prescription(prescription_id, {
        "pharmacy_id": pharmacy_id,
        "updated_at": timestamp
    })

    return {"message": "Prescription claimed successfully"}


@app.patch("/pharmacy/{pharmacy_id}/prescriptions/{prescription_id}/status", response_model=dict)
async def update_pharmacy_prescription_status(
    pharmacy_id: int,
    prescription_id: int,
    status_update: PharmacyPrescriptionStatusUpdate
):
    pharmacy_user = await get_current_pharmacy_user(pharmacy_id)
    prescription = await db.get_pharmacy_prescription_by_id(prescription_id)

    if not prescription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found")

    if prescription.get("hospital_name") != pharmacy_user.get("hospital_name"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot update prescription from another hospital")

    if prescription.get("pharmacy_id") not in (None, pharmacy_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Prescription belongs to a different pharmacy")

    allowed_statuses = {"pending", "preparing", "ready", "dispensed", "cancelled"}
    new_status = (status_update.status or "").lower()
    if new_status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Status must be one of {', '.join(allowed_statuses)}"
        )

    timestamp = datetime.now(timezone.utc).isoformat()
    update_data: Dict[str, Any] = {
        "status": new_status,
        "pharmacy_id": pharmacy_id,
        "updated_at": timestamp
    }

    if status_update.notes:
        update_data["notes"] = status_update.notes

    if new_status == "dispensed":
        update_data["dispensed_at"] = timestamp

    await db.update_pharmacy_prescription(prescription_id, update_data)

    return {"message": "Prescription status updated", "status": new_status}


@app.post("/pharmacy/{pharmacy_id}/prescriptions/{prescription_id}/invoice", response_model=PharmacyInvoiceResponse)
async def create_pharmacy_invoice(
    pharmacy_id: int,
    prescription_id: int,
    invoice: PharmacyInvoiceCreate
):
    pharmacy_user = await get_current_pharmacy_user(pharmacy_id)
    prescription = await db.get_pharmacy_prescription_by_id(prescription_id)

    if not prescription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found")

    if prescription.get("hospital_name") != pharmacy_user.get("hospital_name"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot invoice prescription from another hospital")

    if prescription.get("pharmacy_id") not in (None, pharmacy_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Prescription belongs to a different pharmacy")

    if not invoice.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invoice must contain at least one item")

    normalized_items = []
    subtotal_acc = 0.0
    for item in invoice.items:
        item_subtotal = item.subtotal if item.subtotal is not None else round(item.quantity * item.unit_price, 2)
        normalized = {
            "inventory_item_id": item.inventory_item_id,
            "medicine_name": item.medicine_name,
            "name": item.medicine_name,
            "quantity": item.quantity,
            "unit_price": round(item.unit_price, 2),
            "subtotal": round(item_subtotal, 2)
        }
        subtotal_acc += normalized["subtotal"]
        normalized_items.append(normalized)

    subtotal_acc = round(subtotal_acc, 2)
    if abs(subtotal_acc - round(invoice.subtotal, 2)) > 0.05:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Subtotal does not match line items")

    tax_amount = round(invoice.tax or 0.0, 2)
    discount_amount = round(invoice.discount or 0.0, 2)
    total_expected = round(subtotal_acc + tax_amount - discount_amount, 2)
    if abs(total_expected - round(invoice.total_amount, 2)) > 0.05:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Total amount does not balance with subtotal, tax and discount")

    timestamp = datetime.now(timezone.utc).isoformat()
    invoice_payload = {
        "pharmacy_id": pharmacy_id,
        "prescription_id": prescription_id,
        "invoice_number": generate_invoice_number(),
        "items": normalized_items,
        "subtotal": subtotal_acc,
        "tax": tax_amount,
        "discount": discount_amount,
        "total_amount": round(invoice.total_amount, 2),
        "payment_method": invoice.payment_method,
        "status": (invoice.status or "paid").lower(),
        "generated_at": timestamp,
        "created_at": timestamp,
        "updated_at": timestamp,
        "created_by": pharmacy_user.get("username"),
        "notes": invoice.notes
    }

    created_invoice = await db.create_pharmacy_invoice(invoice_payload)
    if not created_invoice:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create invoice")

    # Update stock levels for referenced items
    for item in normalized_items:
        if item.get("inventory_item_id"):
            await db.adjust_pharmacy_inventory_stock(pharmacy_id, item["inventory_item_id"], -item["quantity"])

    await db.update_pharmacy_prescription(prescription_id, {
        "status": "dispensed",
        "pharmacy_id": pharmacy_id,
        "dispensed_at": timestamp,
        "updated_at": timestamp
    })

    created_invoice["items"] = normalized_items
    # Enrich with patient details for immediate response
    try:
        presc = await db.get_pharmacy_prescription_by_id(prescription_id)
        if presc:
            created_invoice["patient_id"] = presc.get("patient_id")
            created_invoice["patient_name"] = presc.get("patient_name")
            created_invoice["patient_phone"] = presc.get("patient_phone")
            # Prefer the visit_date; fallback to prescription created_at's date part
            visit_date = presc.get("visit_date")
            if visit_date:
                created_invoice["prescription_date"] = visit_date[:10]
            else:
                created_at = presc.get("created_at") or ""
                created_date = created_at[:10] if len(created_at) >= 10 else None
                created_invoice["prescription_date"] = created_date
    except Exception:
        pass
    return map_invoice_to_response(created_invoice)


# Pharmacy Inventory & Analytics Routes
@app.get("/pharmacy/{pharmacy_id}/invoices", response_model=List[PharmacyInvoiceResponse])
async def list_pharmacy_invoices(
    pharmacy_id: int,
    prescription_id: Optional[int] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,  # YYYY-MM-DD
    end_date: Optional[str] = None     # YYYY-MM-DD
):
    """List invoices for a pharmacy with optional filtering.

    - prescription_id: only invoices for a specific prescription
    - status: comma-separated (paid, pending, cancelled, refunded, etc.)
    - start_date/end_date: filter by generated_at date (inclusive)
    """
    await get_current_pharmacy_user(pharmacy_id)

    invoices = await db.get_pharmacy_invoices_by_pharmacy(pharmacy_id)

    # Filter by prescription_id
    if prescription_id is not None:
        invoices = [inv for inv in invoices if inv.get("prescription_id") == prescription_id]

    # Filter by status
    if status:
        desired = {s.strip().lower() for s in status.split(",") if s.strip()}
        invoices = [
            inv for inv in invoices
            if (inv.get("status") or "").lower() in desired
        ]

    # Filter by date range using the date part of generated_at (or created_at fallback)
    if start_date or end_date:
        start = start_date or "0001-01-01"
        end = end_date or "9999-12-31"
        filtered: List[Dict[str, Any]] = []
        for inv in invoices:
            dt_str = inv.get("generated_at") or inv.get("created_at") or ""
            inv_date = dt_str[:10] if len(dt_str) >= 10 else "0001-01-01"
            if start <= inv_date <= end:
                filtered.append(inv)
        invoices = filtered

    # Enrich with patient details from prescriptions
    prescription_cache: Dict[int, Optional[Dict[str, Any]]] = {}
    enriched_responses: List[PharmacyInvoiceResponse] = []
    for inv in invoices:
        presc_id = inv.get("prescription_id")
        if presc_id:
            if presc_id not in prescription_cache:
                prescription_cache[presc_id] = await db.get_pharmacy_prescription_by_id(presc_id)
            presc = prescription_cache[presc_id]
            if presc:
                visit_date = presc.get("visit_date")
                created_at = presc.get("created_at") or ""
                created_date = created_at[:10] if len(created_at) >= 10 else None
                inv = {
                    **inv,
                    "patient_id": presc.get("patient_id"),
                    "patient_name": presc.get("patient_name"),
                    "patient_phone": presc.get("patient_phone"),
                    "prescription_date": (visit_date[:10] if visit_date else created_date),
                }
        enriched_responses.append(map_invoice_to_response(inv))

    # Map to response model (also normalizes items JSON)
    return enriched_responses


@app.get("/pharmacy/{pharmacy_id}/patients/with-medications", response_model=List[PharmacyPatientMedications])
async def list_pharmacy_patients_with_medications(pharmacy_id: int):
    """
    Get all patients with their medication summary for a pharmacy.
    
    OPTIMIZED: Uses SQL aggregation function for 80% faster response.
    Falls back to Python-based processing if SQL function not available.
    """
    pharmacy_user = await get_current_pharmacy_user(pharmacy_id)
    hospital_name = pharmacy_user.get("hospital_name")
    
    # TRY OPTIMIZED SQL FUNCTION FIRST (80% faster)
    optimized_result = await db.get_pharmacy_patient_summary_optimized(pharmacy_id, hospital_name)
    
    if optimized_result is not None:
        # SQL function available - use pre-aggregated data
        summaries = []
        for row in optimized_result:
            summaries.append(PharmacyPatientMedications(
                patient_id=row["patient_id"],
                patient_name=row["patient_name"] or "",
                patient_phone=row.get("patient_phone"),
                total_prescriptions=row["total_prescriptions"],
                pending_prescriptions=row["pending_prescriptions"],
                last_prescription_id=row.get("last_prescription_id"),
                last_prescription_status=row.get("last_prescription_status"),
                last_visit_date=str(row["last_visit_date"]) if row.get("last_visit_date") else None,
                last_updated_at=row.get("last_updated_at"),
                last_medications=row.get("last_medications") or [],
                last_invoice_id=row.get("last_invoice_id"),
                last_invoice_number=row.get("last_invoice_number"),
                last_invoice_total=safe_float(row.get("last_invoice_total")),
                last_invoice_status=row.get("last_invoice_status"),
                last_invoice_date=str(row["last_invoice_date"]) if row.get("last_invoice_date") else None,
            ))
        return summaries
    
    # FALLBACK: Python-based processing (if SQL function not deployed)
    print("⚠️ Using Python fallback for pharmacy patient summary")
    
    prescriptions = await db.get_pharmacy_prescriptions(hospital_name, None)
    relevant_prescriptions = [
        p for p in prescriptions
        if p.get("patient_id") is not None
        and (p.get("hospital_name") == hospital_name or not p.get("hospital_name"))
        and (p.get("pharmacy_id") in (None, pharmacy_id))
    ]

    if not relevant_prescriptions:
        return []

    invoices = await db.get_pharmacy_invoices_by_pharmacy(pharmacy_id)
    latest_invoice_by_prescription: Dict[int, Dict[str, Any]] = {}
    for inv in invoices:
        presc_id = inv.get("prescription_id")
        if not presc_id:
            continue
        current = latest_invoice_by_prescription.get(presc_id)
        if not current or (inv.get("generated_at") or "") > (current.get("generated_at") or ""):
            latest_invoice_by_prescription[presc_id] = inv

    patient_summary: Dict[int, Dict[str, Any]] = {}
    for raw_prescription in relevant_prescriptions:
        patient_id = raw_prescription.get("patient_id")
        if patient_id is None:
            continue
        view = map_prescription_to_view(raw_prescription)
        summary = patient_summary.get(patient_id)
        if not summary:
            summary = {
                "patient_id": patient_id,
                "patient_name": view.patient_name or "",
                "patient_phone": view.patient_phone,
                "total_prescriptions": 0,
                "pending_prescriptions": 0,
                "last_prescription_id": None,
                "last_prescription_status": None,
                "last_visit_date": None,
                "last_updated_at": None,
                "last_medications": [],
                "last_invoice_id": None,
                "last_invoice_number": None,
                "last_invoice_total": None,
                "last_invoice_status": None,
                "last_invoice_date": None,
            }
            patient_summary[patient_id] = summary

        summary["total_prescriptions"] += 1
        if (view.status or "").lower() in {"pending", "preparing", "ready"}:
            summary["pending_prescriptions"] += 1

        timestamp = (view.updated_at or view.created_at or "")
        last_timestamp = summary.get("last_updated_at") or ""
        if timestamp > last_timestamp:
            prescription_date = (view.visit_date or view.created_at or "")[:10] if (view.visit_date or view.created_at) else None
            summary.update({
                "last_prescription_id": view.id,
                "last_prescription_status": view.status,
                "last_visit_date": prescription_date,
                "last_updated_at": timestamp,
                "last_medications": view.medications_json or [],
            })

            invoice = latest_invoice_by_prescription.get(view.id)
            if invoice:
                summary.update({
                    "last_invoice_id": invoice.get("id"),
                    "last_invoice_number": invoice.get("invoice_number"),
                    "last_invoice_total": safe_float(invoice.get("total_amount")),
                    "last_invoice_status": invoice.get("status"),
                    "last_invoice_date": (invoice.get("generated_at") or "")[:10] if invoice.get("generated_at") else None,
                })
            else:
                summary.update({
                    "last_invoice_id": None,
                    "last_invoice_number": None,
                    "last_invoice_total": None,
                    "last_invoice_status": None,
                    "last_invoice_date": None,
                })

    summaries = [PharmacyPatientMedications(**summary) for summary in patient_summary.values()]
    return sorted(summaries, key=lambda s: (s.patient_name or "").lower())


@app.get("/pharmacy/{pharmacy_id}/patients/{patient_id}/purchase-history", response_model=PharmacyPatientDetailResponse)
async def get_pharmacy_patient_purchase_history(pharmacy_id: int, patient_id: int):
    pharmacy_user = await get_current_pharmacy_user(pharmacy_id)
    hospital_name = pharmacy_user.get("hospital_name")

    prescriptions = await db.get_pharmacy_prescriptions(hospital_name, None)
    patient_prescriptions = [
        p for p in prescriptions
        if p.get("patient_id") == patient_id
        and (p.get("hospital_name") == hospital_name or not p.get("hospital_name"))
        and (p.get("pharmacy_id") in (None, pharmacy_id))
    ]

    prescription_views: List[PharmacyPrescriptionView] = [
        map_prescription_to_view(prescription) for prescription in patient_prescriptions
    ]

    invoices = await db.get_pharmacy_invoices_by_pharmacy(pharmacy_id)
    invoices_by_prescription: Dict[int, List[Dict[str, Any]]] = {}
    for inv in invoices:
        presc_id = inv.get("prescription_id")
        if presc_id is None:
            continue
        invoices_by_prescription.setdefault(presc_id, []).append(inv)

    history_items: List[PharmacyPurchaseHistoryItem] = []
    for prescription_view in prescription_views:
        records = invoices_by_prescription.get(prescription_view.id, [])
        for inv in records:
            meds = normalize_medication_items(inv.get("items")) or prescription_view.medications_json or []
            history_items.append(
                PharmacyPurchaseHistoryItem(
                    invoice_id=inv.get("id"),
                    invoice_number=inv.get("invoice_number", ""),
                    prescription_id=prescription_view.id,
                    patient_id=patient_id,
                    patient_name=prescription_view.patient_name or "",
                    patient_phone=prescription_view.patient_phone,
                    total_amount=safe_float(inv.get("total_amount")) or 0.0,
                    status=inv.get("status", "paid"),
                    payment_method=inv.get("payment_method"),
                    generated_at=inv.get("generated_at", datetime.now(timezone.utc).isoformat()),
                    prescription_status=prescription_view.status,
                    prescription_date=(prescription_view.visit_date or prescription_view.created_at or "")[:10]
                    if (prescription_view.visit_date or prescription_view.created_at) else None,
                    medications=meds or [],
                    notes=inv.get("notes"),
                )
            )

    history_items.sort(key=lambda item: item.generated_at, reverse=True)

    patient_record = await db.get_patient_by_id_unrestricted(patient_id)
    patient_name = ""
    patient_phone = None
    patient_email = None
    patient_gender = None
    patient_dob = None

    if patient_record:
        patient_name = f"{patient_record.get('first_name', '').strip()} {patient_record.get('last_name', '').strip()}".strip()
        patient_phone = patient_record.get("phone")
        patient_email = patient_record.get("email")
        patient_gender = patient_record.get("gender")
        dob_value = patient_record.get("date_of_birth")
        if isinstance(dob_value, str):
            patient_dob = dob_value
        elif dob_value:
            patient_dob = str(dob_value)

    if not patient_record and not prescription_views:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")

    if not patient_name and prescription_views:
        sample_view = prescription_views[0]
        patient_name = sample_view.patient_name or ""
        patient_phone = patient_phone or sample_view.patient_phone

    total_prescriptions = len(prescription_views)
    pending_prescriptions = len([
        view for view in prescription_views if (view.status or "").lower() in {"pending", "preparing", "ready"}
    ])

    latest_prescription = None
    if prescription_views:
        latest_prescription = max(
            prescription_views,
            key=lambda view: (view.updated_at or view.created_at or "")
        )

    return PharmacyPatientDetailResponse(
        patient_id=patient_id,
        patient_name=patient_name,
        patient_phone=patient_phone,
        patient_email=patient_email,
        patient_gender=patient_gender,
        patient_date_of_birth=patient_dob,
        total_prescriptions=total_prescriptions,
        pending_prescriptions=pending_prescriptions,
        latest_prescription=latest_prescription,
        prescriptions=prescription_views,
        invoices=history_items,
    )


@app.get("/pharmacy/{pharmacy_id}/suppliers", response_model=List[PharmacySupplierResponse])
async def list_pharmacy_suppliers(pharmacy_id: int):
    await get_current_pharmacy_user(pharmacy_id)
    suppliers = await db.get_pharmacy_suppliers(pharmacy_id)
    return [map_supplier_record(supplier) for supplier in suppliers]


@app.post("/pharmacy/{pharmacy_id}/suppliers", response_model=PharmacySupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_pharmacy_supplier(pharmacy_id: int, supplier: PharmacySupplierCreate):
    await get_current_pharmacy_user(pharmacy_id)
    timestamp = datetime.now(timezone.utc).isoformat()
    supplier_data = supplier.model_dump(exclude_none=True)
    supplier_data.update({
        "pharmacy_id": pharmacy_id,
        "created_at": timestamp,
        "updated_at": timestamp,
    })
    created = await db.create_pharmacy_supplier(supplier_data)
    if not created:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create supplier")
    return map_supplier_record(created)


@app.put("/pharmacy/{pharmacy_id}/suppliers/{supplier_id}", response_model=PharmacySupplierResponse)
async def update_pharmacy_supplier(pharmacy_id: int, supplier_id: int, supplier_update: PharmacySupplierUpdate):
    await get_current_pharmacy_user(pharmacy_id)
    update_data = supplier_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided for update")

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated = await db.update_pharmacy_supplier(pharmacy_id, supplier_id, update_data)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return map_supplier_record(updated)


@app.post("/pharmacy/{pharmacy_id}/inventory", response_model=PharmacyInventoryItem)
async def create_inventory_item(pharmacy_id: int, inventory_item: PharmacyInventoryCreate):
    await get_current_pharmacy_user(pharmacy_id)
    timestamp = datetime.now(timezone.utc).isoformat()
    item_data = inventory_item.model_dump(exclude_none=True)
    item_data.update({
        "pharmacy_id": pharmacy_id,
        "created_at": timestamp,
        "updated_at": timestamp
    })

    created_item = await db.create_pharmacy_inventory_item(item_data)
    if not created_item:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create inventory item")

    return map_inventory_item(created_item)


@app.put("/pharmacy/{pharmacy_id}/inventory/{item_id}", response_model=PharmacyInventoryItem)
async def update_inventory_item(pharmacy_id: int, item_id: int, inventory_update: PharmacyInventoryUpdate):
    await get_current_pharmacy_user(pharmacy_id)
    existing_item = await db.get_pharmacy_inventory_item_by_id(pharmacy_id, item_id)
    if not existing_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")

    update_data = inventory_update.model_dump(exclude_unset=True, exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.update_pharmacy_inventory_item(pharmacy_id, item_id, update_data)

    refreshed = await db.get_pharmacy_inventory_item_by_id(pharmacy_id, item_id)
    return map_inventory_item(refreshed or existing_item)


@app.post("/pharmacy/{pharmacy_id}/inventory/{item_id}/adjust-stock", response_model=PharmacyInventoryItem)
async def adjust_inventory_stock(pharmacy_id: int, item_id: int, adjustment: PharmacyInventoryAdjust):
    await get_current_pharmacy_user(pharmacy_id)
    if adjustment.quantity_delta == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity delta must be non-zero")

    updated_item = await db.adjust_pharmacy_inventory_stock(pharmacy_id, item_id, adjustment.quantity_delta)
    if not updated_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")

    return map_inventory_item(updated_item)


@app.get("/pharmacy/{pharmacy_id}/inventory", response_model=List[PharmacyInventoryItem])
async def list_inventory_items(pharmacy_id: int, low_stock_only: bool = False):
    await get_current_pharmacy_user(pharmacy_id)
    inventory_raw = await db.get_pharmacy_inventory_items(pharmacy_id)
    inventory_items = [map_inventory_item(item) for item in inventory_raw]

    if low_stock_only:
        inventory_items = [
            item for item in inventory_items
            if item.reorder_level is not None and item.reorder_level > 0 and item.stock_quantity <= item.reorder_level
        ]

    return inventory_items


@app.get("/pharmacy/{pharmacy_id}/alerts/low-stock", response_model=List[PharmacyInventoryItem])
async def get_low_stock_alerts(pharmacy_id: int):
    return await list_inventory_items(pharmacy_id, low_stock_only=True)


@app.get("/pharmacy/{pharmacy_id}/reports/sales", response_model=dict)
async def get_pharmacy_sales_report(
    pharmacy_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    await get_current_pharmacy_user(pharmacy_id)

    if start_date:
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start_date must be YYYY-MM-DD")

    if end_date:
        try:
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end_date must be YYYY-MM-DD")

    summary = await db.get_pharmacy_invoice_summary(pharmacy_id, start_date=start_date, end_date=end_date)
    invoices_raw = await db.get_pharmacy_invoices_by_pharmacy(pharmacy_id)

    if start_date or end_date:
        invoices_filtered = []
        for invoice in invoices_raw:
            generated_at = invoice.get("generated_at") or ""
            date_part = generated_at[:10]
            if start_date and date_part < start_date:
                continue
            if end_date and date_part > end_date:
                continue
            invoices_filtered.append(invoice)
        invoices_raw = invoices_filtered

    invoices = [map_invoice_to_response(invoice).model_dump() for invoice in invoices_raw]
    return {"summary": summary, "invoices": invoices}


@app.get("/pharmacy/{pharmacy_id}/prescriptions/stats", response_model=dict)
async def get_pharmacy_prescription_stats(pharmacy_id: int):
    pharmacy_user = await get_current_pharmacy_user(pharmacy_id)
    hospital_name = pharmacy_user["hospital_name"]
    
    # Get all prescriptions for this hospital (debug)
    all_prescriptions = await db.get_pharmacy_prescriptions(hospital_name, None)
    # Filter to show those relevant to this pharmacy
    relevant_prescriptions = [
        p for p in all_prescriptions 
        if p.get("pharmacy_id") is None or p.get("pharmacy_id") == pharmacy_id
    ]

    stats: Dict[str, int] = {
        "pending": 0,
        "preparing": 0,
        "ready": 0,
        "dispensed": 0,
        "cancelled": 0
    }

    for prescription in relevant_prescriptions:
        status_value = (prescription.get("status") or "pending").lower()
        if status_value in stats:
            stats[status_value] += 1
        else:
            stats.setdefault(status_value, 0)
            stats[status_value] += 1

    return {
        "counts": stats, 
        "total": len(relevant_prescriptions),
        "hospital_name": hospital_name,
        "pharmacy_id": pharmacy_id,
        "debug_info": {
            "total_hospital_prescriptions": len(all_prescriptions),
            "relevant_prescriptions": len(relevant_prescriptions),
            "sample_prescriptions": [
                {
                    "id": p.get("id"),
                    "hospital_name": p.get("hospital_name"),
                    "pharmacy_id": p.get("pharmacy_id"),
                    "status": p.get("status"),
                    "patient_name": p.get("patient_name"),
                    "created_at": p.get("created_at")
                }
                for p in all_prescriptions[:3]
            ]
        }
    }

# Frontdesk Dashboard Routes
@app.get("/frontdesk/{frontdesk_id}/doctors", response_model=List[DoctorWithPatientCount])
async def get_hospital_doctors(frontdesk_id: int):
    """Get all doctors for the frontdesk user's hospital with patient counts"""
    try:
        # Get and verify frontdesk user
        frontdesk_user = await get_current_frontdesk_user(frontdesk_id)
        hospital_name = frontdesk_user["hospital_name"]
        
        print(f"Fetching doctors for hospital: {hospital_name}")
        
        # Get doctors with patient counts
        doctors = await db.get_doctors_with_patient_count_by_hospital(hospital_name)
        
        # Convert to response models
        doctor_responses = []
        for doctor in doctors:
            doctor_response = DoctorWithPatientCount(
                id=doctor["id"],
                firebase_uid=doctor["firebase_uid"],
                email=doctor["email"],
                first_name=doctor["first_name"],
                last_name=doctor["last_name"],
                specialization=doctor.get("specialization"),
                license_number=doctor.get("license_number"),
                phone=doctor.get("phone"),
                hospital_name=doctor.get("hospital_name"),
                patient_count=doctor["patient_count"],
                created_at=doctor["created_at"],
                updated_at=doctor["updated_at"]
            )
            doctor_responses.append(doctor_response)
        
        print(f"Returning {len(doctor_responses)} doctors for hospital: {hospital_name}")
        return doctor_responses
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching hospital doctors: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch hospital doctors"
        )

@app.get("/frontdesk/{frontdesk_id}/patients", response_model=List[PatientWithDoctorInfo])
async def get_hospital_patients(frontdesk_id: int, limit: Optional[int] = None):
    """Get all patients under doctors of the frontdesk user's hospital"""
    try:
        # Get and verify frontdesk user
        frontdesk_user = await get_current_frontdesk_user(frontdesk_id)
        hospital_name = frontdesk_user["hospital_name"]
        
        print(f"Fetching patients for hospital: {hospital_name}")
        
        # Get patients with doctor info
        patients = await db.get_patients_with_doctor_info_by_hospital(hospital_name)
        
        # Apply limit if specified
        if limit and limit > 0:
            patients = patients[:limit]
        
        # Convert to response models
        patient_responses = []
        for patient in patients:
            patient_response = PatientWithDoctorInfo(
                id=patient["id"],
                first_name=patient["first_name"],
                last_name=patient["last_name"],
                email=patient.get("email"),
                phone=patient["phone"],
                date_of_birth=patient["date_of_birth"],
                gender=patient["gender"],
                address=patient.get("address"),
                blood_group=patient.get("blood_group"),
                allergies=patient.get("allergies"),
                medical_history=patient.get("medical_history"),
                doctor_name=patient["doctor_name"],
                doctor_specialization=patient["doctor_specialization"],
                doctor_phone=patient["doctor_phone"],
                created_at=patient["created_at"],
                updated_at=patient["updated_at"]
            )
            patient_responses.append(patient_response)
        
        print(f"Returning {len(patient_responses)} patients for hospital: {hospital_name}")
        return patient_responses
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching hospital patients: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch hospital patients"
        )

@app.get("/frontdesk/{frontdesk_id}/dashboard", response_model=HospitalDashboardResponse)
async def get_hospital_dashboard(frontdesk_id: int):
    """Get complete dashboard data for the frontdesk user's hospital"""
    try:
        # Get and verify frontdesk user
        frontdesk_user = await get_current_frontdesk_user(frontdesk_id)
        hospital_name = frontdesk_user["hospital_name"]
        
        print(f"🚀 Fetching dashboard data for hospital: {hospital_name} (optimized)")
        
        # Try to use the ultra-optimized single-query dashboard method
        dashboard_data = await db.get_hospital_dashboard_optimized(hospital_name, recent_limit=20)
        
        if dashboard_data:
            # Dashboard loaded with single query! Parse the JSON response
            print(f"✅ Dashboard loaded with 1 query!")
            
            # Convert doctors from dashboard data
            doctor_responses = []
            for doctor in dashboard_data.get('doctors', []):
                doctor_response = DoctorWithPatientCount(
                    id=doctor["id"],
                    firebase_uid=doctor["firebase_uid"],
                    email=doctor["email"],
                    first_name=doctor["first_name"],
                    last_name=doctor["last_name"],
                    specialization=doctor.get("specialization"),
                    license_number=doctor.get("license_number"),
                    phone=doctor.get("phone"),
                    hospital_name=doctor.get("hospital_name"),
                    patient_count=doctor.get("patient_count", 0),
                    created_at=doctor["created_at"],
                    updated_at=doctor["updated_at"]
                )
                doctor_responses.append(doctor_response)
            
            # Convert patients from dashboard data
            patient_responses = []
            for patient in dashboard_data.get('recent_patients', []):
                patient_response = PatientWithDoctorInfo(
                    id=patient["id"],
                    first_name=patient["first_name"],
                    last_name=patient["last_name"],
                    email=patient.get("email"),
                    phone=patient["phone"],
                    date_of_birth=patient["date_of_birth"],
                    gender=patient["gender"],
                    address=patient.get("address"),
                    blood_group=patient.get("blood_group"),
                    allergies=patient.get("allergies"),
                    medical_history=patient.get("medical_history"),
                    doctor_name=f"{patient.get('doctor_first_name', '')} {patient.get('doctor_last_name', '')}".strip(),
                    doctor_specialization=patient.get("doctor_specialization", ""),
                    doctor_phone=patient.get("doctor_phone", ""),
                    created_at=patient["created_at"],
                    updated_at=patient["updated_at"]
                )
                patient_responses.append(patient_response)
            
            dashboard_response = HospitalDashboardResponse(
                hospital_name=hospital_name,
                total_doctors=dashboard_data.get('total_doctors', 0),
                total_patients=dashboard_data.get('total_patients', 0),
                doctors=doctor_responses,
                recent_patients=patient_responses
            )
            
            print(f"✅ Returning optimized dashboard for {hospital_name}: {dashboard_data.get('total_doctors')} doctors, {dashboard_data.get('total_patients')} patients")
            return dashboard_response
            
        else:
            # Fallback to old method if optimized function not available
            print(f"⚠️ Using fallback method for dashboard (multiple queries)")
            
            # Get doctors with patient counts
            doctors = await db.get_doctors_with_patient_count_by_hospital(hospital_name)
            
            # Get recent patients (limit to 20 most recent)
            patients = await db.get_patients_with_doctor_info_by_hospital(hospital_name)
            # Sort by created_at desc and take first 20
            recent_patients = sorted(patients, key=lambda x: x.get("created_at", ""), reverse=True)[:20]
            
            # Convert doctors to response models
            doctor_responses = []
            for doctor in doctors:
                doctor_response = DoctorWithPatientCount(
                    id=doctor["id"],
                    firebase_uid=doctor["firebase_uid"],
                    email=doctor["email"],
                    first_name=doctor["first_name"],
                    last_name=doctor["last_name"],
                    specialization=doctor.get("specialization"),
                    license_number=doctor.get("license_number"),
                    phone=doctor.get("phone"),
                    hospital_name=doctor.get("hospital_name"),
                    patient_count=doctor["patient_count"],
                    created_at=doctor["created_at"],
                    updated_at=doctor["updated_at"]
                )
                doctor_responses.append(doctor_response)
            
            # Convert patients to response models
            patient_responses = []
            for patient in recent_patients:
                patient_response = PatientWithDoctorInfo(
                    id=patient["id"],
                    first_name=patient["first_name"],
                    last_name=patient["last_name"],
                    email=patient.get("email"),
                    phone=patient["phone"],
                    date_of_birth=patient["date_of_birth"],
                    gender=patient["gender"],
                    address=patient.get("address"),
                    blood_group=patient.get("blood_group"),
                    allergies=patient.get("allergies"),
                    medical_history=patient.get("medical_history"),
                    doctor_name=patient["doctor_name"],
                    doctor_specialization=patient["doctor_specialization"],
                    doctor_phone=patient["doctor_phone"],
                    created_at=patient["created_at"],
                    updated_at=patient["updated_at"]
                )
                patient_responses.append(patient_response)
            
            # Calculate totals
            total_doctors = len(doctor_responses)
            total_patients = sum(doctor["patient_count"] for doctor in doctors)
            
            dashboard_response = HospitalDashboardResponse(
                hospital_name=hospital_name,
                total_doctors=total_doctors,
                total_patients=total_patients,
                doctors=doctor_responses,
                recent_patients=patient_responses
            )
            
            print(f"Returning dashboard for {hospital_name}: {total_doctors} doctors, {total_patients} patients")
            return dashboard_response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching hospital dashboard: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch hospital dashboard"
        )

@app.post(
    "/frontdesk/{frontdesk_id}/register-patient", 
    response_model=dict,
    tags=["Frontdesk", "Patients"],
    summary="Register a new patient by frontdesk staff",
    description="""Register a new patient by frontdesk staff with doctor assignment.
    
## Prior Medical History Support

This endpoint now supports capturing detailed prior medical history when a patient has previously consulted another doctor. This is especially useful for frontdesk staff during patient intake.

### Fields Available in prior_medical_history:

| Field | Type | Description |
|-------|------|-------------|
| consulted_other_doctor | boolean | Whether patient consulted another doctor |
| previous_doctor_name | string | Name of the previous doctor |
| previous_doctor_specialization | string | Specialization of previous doctor |
| previous_clinic_hospital | string | Previous clinic/hospital name |
| previous_consultation_date | string | Date in YYYY-MM-DD format |
| previous_symptoms | string | Symptoms at previous visit |
| previous_diagnosis | string | Diagnosis by previous doctor |
| previous_medications | array | List of prescribed medications |
| previous_medications_duration | string | Duration of medication |
| medication_response | string | Response: improved/partial improvement/no change/worsened |
| previous_tests_done | string | Tests performed previously |
| previous_test_results | string | Results of previous tests |
| reason_for_new_consultation | string | Why seeking new consultation |
| ongoing_treatment | boolean | Currently on treatment |
| current_medications | array | Current medications being taken |
"""
)
async def register_patient_by_frontdesk(frontdesk_id: int, patient: FrontdeskPatientRegister):
    """Register a new patient by frontdesk staff with doctor assignment"""
    try:
        print(f"=== FRONTDESK PATIENT REGISTRATION START ===")
        print(f"Frontdesk ID: {frontdesk_id}")
        print(f"Patient data: {patient.model_dump()}")
        
        # Get and verify frontdesk user
        frontdesk_user = await get_current_frontdesk_user(frontdesk_id)
        hospital_name = frontdesk_user["hospital_name"]
        
        print(f"Frontdesk user hospital: {hospital_name}")
        
        # Validate required fields
        if not patient.first_name or not patient.last_name or not patient.phone or not patient.date_of_birth or not patient.gender:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="First name, last name, phone, date of birth, and gender are required"
            )
        
        if not patient.doctor_firebase_uid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Doctor selection is required"
            )
        
        # Validate that the selected doctor belongs to the same hospital
        is_valid_doctor = await db.validate_doctor_belongs_to_hospital(
            patient.doctor_firebase_uid, 
            hospital_name
        )
        
        if not is_valid_doctor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected doctor does not belong to this hospital"
            )
        
        # Validate date of birth format
        try:
            from datetime import datetime
            datetime.strptime(patient.date_of_birth, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Date of birth must be in YYYY-MM-DD format"
            )
        
        # Validate gender
        if patient.gender not in ["Male", "Female", "Other"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gender must be Male, Female, or Other"
            )
        
        # Prepare patient data for database
        patient_data = {
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "phone": patient.phone,
            "date_of_birth": patient.date_of_birth,
            "gender": patient.gender,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add optional fields only if they have values
        if patient.email:
            patient_data["email"] = patient.email
        if patient.address:
            patient_data["address"] = patient.address
        if patient.emergency_contact_name:
            patient_data["emergency_contact_name"] = patient.emergency_contact_name
        if patient.emergency_contact_phone:
            patient_data["emergency_contact_phone"] = patient.emergency_contact_phone
        if patient.blood_group:
            patient_data["blood_group"] = patient.blood_group
        if patient.allergies:
            patient_data["allergies"] = patient.allergies
        if patient.medical_history:
            patient_data["medical_history"] = patient.medical_history
        
        # Add prior medical history fields if provided
        if patient.prior_medical_history:
            pmh = patient.prior_medical_history
            patient_data["consulted_other_doctor"] = pmh.consulted_other_doctor
            
            if pmh.previous_doctor_name:
                patient_data["previous_doctor_name"] = pmh.previous_doctor_name
            if pmh.previous_doctor_specialization:
                patient_data["previous_doctor_specialization"] = pmh.previous_doctor_specialization
            if pmh.previous_clinic_hospital:
                patient_data["previous_clinic_hospital"] = pmh.previous_clinic_hospital
            if pmh.previous_consultation_date:
                patient_data["previous_consultation_date"] = pmh.previous_consultation_date
            if pmh.previous_symptoms:
                patient_data["previous_symptoms"] = pmh.previous_symptoms
            if pmh.previous_diagnosis:
                patient_data["previous_diagnosis"] = pmh.previous_diagnosis
            if pmh.previous_medications:
                patient_data["previous_medications"] = pmh.previous_medications  # Will be stored as JSONB
            if pmh.previous_medications_duration:
                patient_data["previous_medications_duration"] = pmh.previous_medications_duration
            if pmh.medication_response:
                # Normalize to lowercase to match database check constraint
                patient_data["medication_response"] = pmh.medication_response.lower()
            if pmh.previous_tests_done:
                patient_data["previous_tests_done"] = pmh.previous_tests_done
            if pmh.previous_test_results:
                patient_data["previous_test_results"] = pmh.previous_test_results
            if pmh.reason_for_new_consultation:
                patient_data["reason_for_new_consultation"] = pmh.reason_for_new_consultation
            
            patient_data["ongoing_treatment"] = pmh.ongoing_treatment
            if pmh.current_medications:
                patient_data["current_medications"] = pmh.current_medications  # Will be stored as JSONB
        
        print(f"Creating patient with data: {patient_data}")
        
        # Create patient using database manager
        created_patient = await db.create_patient_by_frontdesk(patient_data, patient.doctor_firebase_uid)
        if created_patient:
            print(f"Patient registration successful: {patient.first_name} {patient.last_name}")
            return {
                "message": "Patient registered successfully",
                "patient_id": created_patient["id"],
                "patient_name": f"{created_patient['first_name']} {created_patient['last_name']}",
                "doctor_name": created_patient.get("doctor_name", "Unknown"),
                "assigned_to_doctor": patient.doctor_firebase_uid
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create patient record"
            )
            
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        print(f"Unexpected frontdesk patient registration error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Patient registration error: {str(e)}"
        )

# Appointment Management Endpoints for Frontdesk
@app.post("/frontdesk/{frontdesk_id}/appointments", response_model=dict)
async def create_appointment_by_frontdesk(frontdesk_id: int, appointment: AppointmentCreate):
    """Create a new appointment by frontdesk staff"""
    try:
        print(f"=== FRONTDESK APPOINTMENT CREATION START ===")
        print(f"Frontdesk ID: {frontdesk_id}")
        print(f"Appointment data: {appointment.model_dump()}")
        
        # Get and verify frontdesk user
        frontdesk_user = await get_current_frontdesk_user(frontdesk_id)
        hospital_name = frontdesk_user["hospital_name"]
        
        # Validate that the selected doctor belongs to the same hospital
        is_valid_doctor = await db.validate_doctor_belongs_to_hospital(
            appointment.doctor_firebase_uid, 
            hospital_name
        )
        
        if not is_valid_doctor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected doctor does not belong to this hospital"
            )
        
        # Validate patient if provided - check if patient exists in the same hospital
        if appointment.patient_id:
            is_valid_patient = await db.validate_patient_belongs_to_hospital(
                appointment.patient_id,
                hospital_name
            )
            
            if not is_valid_patient:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Patient not found or belongs to a different hospital"
                )
        
        # Validate date and time format
        try:
            from datetime import datetime
            datetime.strptime(appointment.appointment_date, "%Y-%m-%d")
            datetime.strptime(appointment.appointment_time, "%H:%M")
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use YYYY-MM-DD for date and HH:MM for time"
            )
        
        # Check for appointment conflicts
        has_conflict = await db.check_appointment_conflicts(
            appointment.doctor_firebase_uid,
            appointment.appointment_date,
            appointment.appointment_time,
            appointment.duration_minutes
        )
        
        if has_conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Appointment conflicts with existing appointment"
            )
        
        # Prepare appointment data
        appointment_data = {
            "doctor_firebase_uid": appointment.doctor_firebase_uid,
            "patient_id": appointment.patient_id,
            "frontdesk_user_id": frontdesk_id,
            "appointment_date": appointment.appointment_date,
            "appointment_time": appointment.appointment_time,
            "duration_minutes": appointment.duration_minutes,
            "status": "scheduled",
            "appointment_type": appointment.appointment_type,
            "notes": appointment.notes,
            "patient_notes": appointment.patient_notes,
            "created_by_frontdesk": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Create appointment
        created_appointment = await db.create_appointment(appointment_data)
        if created_appointment:
            print(f"Appointment created successfully: {created_appointment['id']}")
            return {
                "message": "Appointment created successfully",
                "appointment_id": created_appointment["id"],
                "appointment_date": created_appointment["appointment_date"],
                "appointment_time": created_appointment["appointment_time"]
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create appointment"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected appointment creation error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Appointment creation error: {str(e)}"
        )

@app.get("/frontdesk/{frontdesk_id}/appointments", response_model=List[AppointmentView])
async def get_hospital_appointments(frontdesk_id: int, start_date: str, end_date: str):
    """Get all appointments for the hospital within date range"""
    try:
        # Get and verify frontdesk user
        frontdesk_user = await get_current_frontdesk_user(frontdesk_id)
        hospital_name = frontdesk_user["hospital_name"]
        
        print(f"Fetching appointments for hospital: {hospital_name} from {start_date} to {end_date}")
        
        # Get appointments
        appointments = await db.get_appointments_by_hospital_and_date_range(
            hospital_name, start_date, end_date
        )
        
        # Convert to response models
        appointment_responses = []
        for apt in appointments:
            appointment_response = AppointmentView(
                id=apt["id"],
                doctor_firebase_uid=apt["doctor_firebase_uid"],
                doctor_name=apt.get("doctor_name", "Unknown"),
                doctor_specialization=apt.get("doctor_specialization"),
                patient_id=apt.get("patient_id"),
                patient_name=apt.get("patient_name"),
                patient_phone=apt.get("patient_phone"),
                appointment_date=apt["appointment_date"],
                appointment_time=apt["appointment_time"],
                duration_minutes=apt["duration_minutes"],
                status=apt["status"],
                appointment_type=apt["appointment_type"],
                notes=apt.get("notes"),
                patient_notes=apt.get("patient_notes"),
                created_by_frontdesk=apt.get("created_by_frontdesk", False),
                created_at=apt["created_at"],
                updated_at=apt["updated_at"]
            )
            appointment_responses.append(appointment_response)
        
        print(f"Returning {len(appointment_responses)} appointments")
        return appointment_responses
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching hospital appointments: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch appointments"
        )

@app.put("/frontdesk/{frontdesk_id}/appointments/{appointment_id}", response_model=dict)
async def update_appointment_by_frontdesk(frontdesk_id: int, appointment_id: int, appointment: AppointmentUpdate):
    """Update an existing appointment by frontdesk staff"""
    try:
        print(f"=== FRONTDESK APPOINTMENT UPDATE START ===")
        print(f"Frontdesk ID: {frontdesk_id}, Appointment ID: {appointment_id}")
        print(f"Update data: {appointment.model_dump(exclude_unset=True)}")
        
        # Get and verify frontdesk user
        frontdesk_user = await get_current_frontdesk_user(frontdesk_id)
        hospital_name = frontdesk_user["hospital_name"]
        
        # Get the existing appointment
        loop = asyncio.get_event_loop()
        existing_apt_response = await loop.run_in_executor(
            db.executor,
            lambda: db.supabase.table("appointments").select("*").eq("id", appointment_id).execute()
        )
        
        if not existing_apt_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )
        
        existing_apt = existing_apt_response.data[0]
        
        # Get the doctor's hospital to verify it matches
        doctor_response = await loop.run_in_executor(
            db.executor,
            lambda: db.supabase.table("doctors").select("hospital_name").eq("firebase_uid", existing_apt["doctor_firebase_uid"]).execute()
        )
        
        if not doctor_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor not found"
            )
        
        apt_hospital = doctor_response.data[0].get("hospital_name")
        
        if apt_hospital != hospital_name:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot update appointment from another hospital"
            )
        
        # Prepare update data
        update_data = appointment.model_dump(exclude_unset=True)
        
        # If changing time or duration, check for conflicts
        if "appointment_time" in update_data or "duration_minutes" in update_data or "appointment_date" in update_data:
            check_date = update_data.get("appointment_date", existing_apt["appointment_date"])
            check_time = update_data.get("appointment_time", existing_apt["appointment_time"])
            check_duration = update_data.get("duration_minutes", existing_apt["duration_minutes"])
            
            has_conflict = await db.check_appointment_conflicts(
                existing_apt["doctor_firebase_uid"],
                check_date,
                check_time,
                check_duration,
                exclude_appointment_id=appointment_id
            )
            
            if has_conflict:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Updated appointment time conflicts with existing appointment"
                )
        
        # Update the appointment
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        updated_appointment = await db.update_appointment(appointment_id, update_data)
        
        if updated_appointment:
            print(f"Appointment {appointment_id} updated successfully")
            return {
                "message": "Appointment updated successfully",
                "appointment_id": updated_appointment["id"]
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update appointment"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected appointment update error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Appointment update error: {str(e)}"
        )

@app.delete("/frontdesk/{frontdesk_id}/appointments/{appointment_id}", response_model=dict)
async def delete_appointment_by_frontdesk(frontdesk_id: int, appointment_id: int):
    """Delete an appointment by frontdesk staff"""
    try:
        print(f"=== FRONTDESK APPOINTMENT DELETE START ===")
        print(f"Frontdesk ID: {frontdesk_id}, Appointment ID: {appointment_id}")
        
        # Get and verify frontdesk user
        frontdesk_user = await get_current_frontdesk_user(frontdesk_id)
        hospital_name = frontdesk_user["hospital_name"]
        
        # Get the existing appointment
        loop = asyncio.get_event_loop()
        existing_apt_response = await loop.run_in_executor(
            db.executor,
            lambda: db.supabase.table("appointments").select("*").eq("id", appointment_id).execute()
        )
        
        if not existing_apt_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )
        
        existing_apt = existing_apt_response.data[0]
        
        # Get the doctor's hospital to verify it matches
        doctor_response = await loop.run_in_executor(
            db.executor,
            lambda: db.supabase.table("doctors").select("hospital_name").eq("firebase_uid", existing_apt["doctor_firebase_uid"]).execute()
        )
        
        if not doctor_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor not found"
            )
        
        apt_hospital = doctor_response.data[0].get("hospital_name")
        
        if apt_hospital != hospital_name:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete appointment from another hospital"
            )
        
        # Delete the appointment
        success = await db.delete_appointment(appointment_id)
        
        if success:
            print(f"Appointment {appointment_id} deleted successfully")
            return {
                "message": "Appointment deleted successfully",
                "appointment_id": appointment_id
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete appointment"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected appointment delete error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Appointment delete error: {str(e)}"
        )

@app.get("/")
async def root():
    """Welcome page with all available access links"""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Doctor App - Backend Services</title>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                margin: 0;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                color: #333;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                border-radius: 15px;
                padding: 30px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            }
            h1 {
                color: #4a90e2;
                text-align: center;
                margin-bottom: 30px;
                font-size: 2.5em;
            }
            .section {
                margin: 30px 0;
                padding: 20px;
                border-left: 4px solid #4a90e2;
                background: #f8f9fa;
                border-radius: 5px;
            }
            .section h2 {
                color: #2c3e50;
                margin-top: 0;
                font-size: 1.5em;
            }
            .link-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
                margin: 20px 0;
            }
            .link-card {
                background: white;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                border: 1px solid #e1e8ed;
                transition: transform 0.2s;
            }
            .link-card:hover {
                transform: translateY(-2px);
                box-shadow: 0 6px 12px rgba(0,0,0,0.15);
            }
            .link-card h3 {
                margin-top: 0;
                color: #4a90e2;
                font-size: 1.2em;
            }
            .link-card a {
                display: inline-block;
                background: #4a90e2;
                color: white;
                padding: 10px 20px;
                text-decoration: none;
                border-radius: 5px;
                margin: 5px 0;
                transition: background 0.3s;
            }
            .link-card a:hover {
                background: #357abd;
            }
            .endpoint-list {
                background: #f1f3f4;
                padding: 15px;
                border-radius: 5px;
                margin: 10px 0;
            }
            .endpoint {
                font-family: 'Courier New', monospace;
                font-size: 0.9em;
                margin: 5px 0;
                padding: 5px;
                background: white;
                border-radius: 3px;
            }
            .method {
                display: inline-block;
                padding: 2px 8px;
                border-radius: 3px;
                color: white;
                font-size: 0.8em;
                margin-right: 10px;
                min-width: 60px;
                text-align: center;
            }
            .GET { background: #28a745; }
            .POST { background: #007bff; }
            .PUT { background: #ffc107; color: #000; }
            .DELETE { background: #dc3545; }
            .status {
                display: inline-block;
                padding: 5px 10px;
                border-radius: 15px;
                font-size: 0.85em;
                font-weight: bold;
                margin: 10px 0;
            }
            .online { background: #d4edda; color: #155724; }
            .info { background: #d1ecf1; color: #0c5460; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🏥 Doctor App - Backend Services</h1>
            <div class="status online">✅ API Server Online</div>
            
            <div class="section">
                <h2>🔗 Quick Access Links</h2>
                <div class="link-grid">
                    <div class="link-card">
                        <h3>📊 API Documentation</h3>
                        <p>Interactive API documentation and testing</p>
                        <a href="/docs" target="_blank">Swagger UI</a>
                        <a href="/redoc" target="_blank">ReDoc</a>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h2>🔐 Authentication Endpoints</h2>
                <div class="endpoint-list">
                    <div class="endpoint">
                        <span class="method POST">POST</span>
                        <code>/login</code> - Doctor login with email/password
                    </div>
                    <div class="endpoint">
                        <span class="method POST">POST</span>
                        <code>/register</code> - Doctor registration
                    </div>
                    <div class="endpoint">
                        <span class="method POST">POST</span>
                        <code>/lab-login</code> - Lab technician login (phone only, no OTP)
                    </div>
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/profile</code> - Get doctor profile
                    </div>
                    <div class="endpoint">
                        <span class="method PUT">PUT</span>
                        <code>/profile</code> - Update doctor profile (including lab contacts)
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h2>🧬 Lab Management Endpoints</h2>
                <div class="endpoint-list">
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/lab-contacts/{phone}</code> - Get lab contact info
                    </div>
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/lab-dashboard/{phone}</code> - Lab dashboard with pending requests
                    </div>
                    <div class="endpoint">
                        <span class="method POST">POST</span>
                        <code>/visits/{visit_id}/request-lab-report</code> - Request lab report
                    </div>
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/upload/{request_token}</code> - Lab report upload page
                    </div>
                    <div class="endpoint">
                        <span class="method POST">POST</span>
                        <code>/upload/{request_token}</code> - Upload lab report
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h2>📅 Calendar & Appointments</h2>
                <div class="endpoint-list">
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/appointments</code> - Get all appointments
                    </div>
                    <div class="endpoint">
                        <span class="method POST">POST</span>
                        <code>/appointments</code> - Create new appointment
                    </div>
                    <div class="endpoint">
                        <span class="method PUT">PUT</span>
                        <code>/appointments/{appointment_id}</code> - Update appointment
                    </div>
                    <div class="endpoint">
                        <span class="method DELETE">DELETE</span>
                        <code>/appointments/{appointment_id}</code> - Cancel appointment
                    </div>
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/appointments/today</code> - Today's appointments
                    </div>
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/appointments/upcoming</code> - Upcoming appointments
                    </div>
                    <div class="endpoint">
                        <span class="method POST">POST</span>
                        <code>/appointments/{appointment_id}/complete</code> - Mark as completed
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h2>🔔 Notification System</h2>
                <div class="endpoint-list">
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/notifications</code> - Get all notifications
                    </div>
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/notifications/unread</code> - Get unread notifications
                    </div>
                    <div class="endpoint">
                        <span class="method PUT">PUT</span>
                        <code>/notifications/{notification_id}/read</code> - Mark as read
                    </div>
                    <div class="endpoint">
                        <span class="method PUT">PUT</span>
                        <code>/notifications/mark-all-read</code> - Mark all as read
                    </div>
                    <div class="endpoint">
                        <span class="method DELETE">DELETE</span>
                        <code>/notifications/{notification_id}</code> - Delete notification
                    </div>
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/notifications/count</code> - Get notification count
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h2>👥 Patient & Visit Management</h2>
                <div class="endpoint-list">
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/patients</code> - Get all patients
                    </div>
                    <div class="endpoint">
                        <span class="method POST">POST</span>
                        <code>/patients</code> - Register new patient
                    </div>
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/patients/{patient_id}</code> - Get patient details
                    </div>
                    <div class="endpoint">
                        <span class="method POST">POST</span>
                        <code>/visits</code> - Create new visit
                    </div>
                    <div class="endpoint">
                        <span class="method GET">GET</span>
                        <code>/visits/{visit_id}</code> - Get visit details
                    </div>
                    <div class="endpoint">
                        <span class="method PUT">PUT</span>
                        <code>/visits/{visit_id}</code> - Update visit
                    </div>
                </div>
            </div>
            
            <div class="section info">
                <h2>📱 How to Use</h2>
                <p><strong>For Doctors:</strong> Use your frontend app to login and manage patients</p>
                <p><strong>For Lab Technicians:</strong> Use <code>POST /lab-login</code> with just your phone number (no OTP required)</p>
                <p><strong>Lab Dashboard Access:</strong> <code>GET /lab-dashboard/{your-phone-number}</code></p>
                <p><strong>Report Upload:</strong> Use the token provided in lab requests to access upload page</p>
            </div>
            
            <div class="section">
                <h2>💡 Examples</h2>
                <div class="endpoint-list">
                    <div class="endpoint">
                        <strong>Lab Login:</strong> <code>POST /lab-login</code><br>
                        <code>{"phone": "9876543210"}</code>
                    </div>
                    <div class="endpoint">
                        <strong>Lab Dashboard:</strong> <code>GET /lab-dashboard/9876543210</code>
                    </div>
                    <div class="endpoint">
                        <strong>Update Profile with Labs:</strong> <code>PUT /profile</code><br>
                        <code>{"pathology_lab_name": "City Labs", "pathology_lab_phone": "9876543210"}</code>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content, status_code=200)

# Patient Routes using database manager
@app.post(
    "/patients/register", 
    response_model=dict,
    tags=["Patients"],
    summary="Register a new patient",
    description="""Register a new patient under the authenticated doctor.
    
## Prior Medical History Support

This endpoint now supports capturing detailed prior medical history when a patient has previously consulted another doctor. Include the `prior_medical_history` object to record:

- **Previous Doctor Details**: Name, specialization, clinic/hospital
- **Previous Consultation**: Date, symptoms, diagnosis
- **Previous Treatment**: Medications, duration, patient's response
- **Previous Tests**: Tests done and their results
- **Current Status**: Ongoing treatment and current medications
- **Reason for Visit**: Why seeking new consultation

## Example with Prior Medical History

```json
{
    "first_name": "John",
    "last_name": "Doe",
    "phone": "9876543210",
    "date_of_birth": "1990-05-15",
    "gender": "Male",
    "prior_medical_history": {
        "consulted_other_doctor": true,
        "previous_doctor_name": "Dr. Sharma",
        "previous_diagnosis": "Viral fever",
        "previous_medications": ["Paracetamol 500mg"],
        "medication_response": "partial improvement",
        "reason_for_new_consultation": "Symptoms persisting"
    }
}
```
"""
)
async def register_patient(patient: PatientRegister, current_doctor = Depends(get_current_doctor)):
    try:
        print(f"=== PATIENT REGISTRATION START ===")
        print(f"Received patient data: {patient.model_dump()}")
        
        # Validate required fields
        if not patient.first_name or not patient.last_name or not patient.phone or not patient.date_of_birth or not patient.gender:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="First name, last name, phone, date of birth, and gender are required"
            )
        
        # Validate gender
        valid_genders = ["Male", "Female", "Other"]
        if patient.gender not in valid_genders:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gender must be Male, Female, or Other"
            )
        
        # Prepare patient data
        patient_data = {
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "phone": patient.phone,
            "date_of_birth": patient.date_of_birth,
            "gender": patient.gender,
            "created_by_doctor": current_doctor["firebase_uid"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add optional fields only if they have values
        optional_fields = ["email", "address", "emergency_contact_name", "emergency_contact_phone", 
                          "blood_group", "allergies", "medical_history"]
        
        for field in optional_fields:
            value = getattr(patient, field)
            if value:
                patient_data[field] = value
        
        # Add prior medical history fields if provided
        if patient.prior_medical_history:
            pmh = patient.prior_medical_history
            patient_data["consulted_other_doctor"] = pmh.consulted_other_doctor
            
            if pmh.previous_doctor_name:
                patient_data["previous_doctor_name"] = pmh.previous_doctor_name
            if pmh.previous_doctor_specialization:
                patient_data["previous_doctor_specialization"] = pmh.previous_doctor_specialization
            if pmh.previous_clinic_hospital:
                patient_data["previous_clinic_hospital"] = pmh.previous_clinic_hospital
            if pmh.previous_consultation_date:
                patient_data["previous_consultation_date"] = pmh.previous_consultation_date
            if pmh.previous_symptoms:
                patient_data["previous_symptoms"] = pmh.previous_symptoms
            if pmh.previous_diagnosis:
                patient_data["previous_diagnosis"] = pmh.previous_diagnosis
            if pmh.previous_medications:
                patient_data["previous_medications"] = pmh.previous_medications  # Will be stored as JSONB
            if pmh.previous_medications_duration:
                patient_data["previous_medications_duration"] = pmh.previous_medications_duration
            if pmh.medication_response:
                # Normalize to lowercase to match database check constraint
                patient_data["medication_response"] = pmh.medication_response.lower()
            if pmh.previous_tests_done:
                patient_data["previous_tests_done"] = pmh.previous_tests_done
            if pmh.previous_test_results:
                patient_data["previous_test_results"] = pmh.previous_test_results
            if pmh.reason_for_new_consultation:
                patient_data["reason_for_new_consultation"] = pmh.reason_for_new_consultation
            
            patient_data["ongoing_treatment"] = pmh.ongoing_treatment
            if pmh.current_medications:
                patient_data["current_medications"] = pmh.current_medications  # Will be stored as JSONB
        
        # Create patient using database manager
        created_patient = await db.create_patient(patient_data)
        if created_patient:
            patient_id = created_patient["id"]
            print(f"Patient registration successful. ID: {patient_id}")
            return {"message": "Patient registered successfully", "patient_id": patient_id}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create patient profile in database"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected patient registration error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Patient registration error: {str(e)}"
        )

@app.get("/patients", response_model=list[PatientProfile])
async def get_all_patients(current_doctor = Depends(get_current_doctor)):
    try:
        patients = await db.get_all_patients_for_doctor(current_doctor["firebase_uid"])
        return [PatientProfile(**patient) for patient in patients]
    except Exception as e:
        print(f"Error fetching patients: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch patients: {str(e)}"
        )
@app.delete("/patients/{patient_id}", response_model=dict)
async def delete_patient(patient_id: int, current_doctor = Depends(get_current_doctor)):
    try:
        # Check if patient exists and belongs to current doctor
        existing_patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not existing_patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Delete patient using database manager
        success = await db.delete_patient(patient_id, current_doctor["firebase_uid"])
        if success:
            return {"message": "Patient deleted successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete patient"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected patient deletion error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Patient deletion error: {str(e)}"
        )
@app.get("/patients/{patient_id}", response_model=PatientProfile)
async def get_patient_profile(patient_id: int, current_doctor = Depends(get_current_doctor)):
    patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found"
        )
    
    return PatientProfile(**patient)

@app.put("/patients/{patient_id}", response_model=dict)
async def update_patient_profile(
    patient_id: int,
    patient_update: PatientUpdate,
    current_doctor = Depends(get_current_doctor)
):
    # Check if patient exists and belongs to current doctor
    existing_patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
    if not existing_patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found"
        )
    
    # Get only the fields that were provided
    update_data = patient_update.model_dump(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )
    
    # Handle prior_medical_history - unpack into individual columns
    if "prior_medical_history" in update_data:
        pmh = update_data.pop("prior_medical_history")
        if pmh:
            update_data["consulted_other_doctor"] = pmh.get("consulted_other_doctor", False)
            
            if pmh.get("previous_doctor_name"):
                update_data["previous_doctor_name"] = pmh["previous_doctor_name"]
            if pmh.get("previous_doctor_specialization"):
                update_data["previous_doctor_specialization"] = pmh["previous_doctor_specialization"]
            if pmh.get("previous_clinic_hospital"):
                update_data["previous_clinic_hospital"] = pmh["previous_clinic_hospital"]
            if pmh.get("previous_consultation_date"):
                update_data["previous_consultation_date"] = pmh["previous_consultation_date"]
            if pmh.get("previous_symptoms"):
                update_data["previous_symptoms"] = pmh["previous_symptoms"]
            if pmh.get("previous_diagnosis"):
                update_data["previous_diagnosis"] = pmh["previous_diagnosis"]
            if pmh.get("previous_medications"):
                update_data["previous_medications"] = pmh["previous_medications"]
            if pmh.get("previous_medications_duration"):
                update_data["previous_medications_duration"] = pmh["previous_medications_duration"]
            if pmh.get("medication_response"):
                # Normalize to lowercase to match database check constraint
                update_data["medication_response"] = pmh["medication_response"].lower()
            if pmh.get("previous_tests_done"):
                update_data["previous_tests_done"] = pmh["previous_tests_done"]
            if pmh.get("previous_test_results"):
                update_data["previous_test_results"] = pmh["previous_test_results"]
            if pmh.get("reason_for_new_consultation"):
                update_data["reason_for_new_consultation"] = pmh["reason_for_new_consultation"]
            
            update_data["ongoing_treatment"] = pmh.get("ongoing_treatment", False)
            if pmh.get("current_medications"):
                update_data["current_medications"] = pmh["current_medications"]
    
    # Validate gender if provided
    if "gender" in update_data:
        valid_genders = ["Male", "Female", "Other"]
        if update_data["gender"] not in valid_genders:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gender must be Male, Female, or Other"
            )
    
    # Add updated timestamp
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    success = await db.update_patient(patient_id, current_doctor["firebase_uid"], update_data)
    if success:
        return {"message": "Patient profile updated successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update patient profile"
        )
       

@app.get(
    "/patients/{patient_id}/with-visits", 
    response_model=PatientWithVisits,
    tags=["Patients"],
    summary="Get patient with all visits",
    description="Get complete patient profile including all their visits. Use GET /patients/{id} for basic profile only."
)
async def get_patient_complete_profile(patient_id: int, current_doctor = Depends(get_current_doctor)):
    # Get patient basic info
    patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found"
        )
    
    # Get patient visits and active cases in parallel
    visits_task = db.get_visits_by_patient_id(patient_id, current_doctor["firebase_uid"])
    cases_task = db.get_cases_by_patient(patient_id, current_doctor["firebase_uid"], status="active")
    
    visits, active_cases = await asyncio.gather(visits_task, cases_task)
    
    # Convert cases to summary format
    case_summaries = []
    for case in active_cases:
        case_summaries.append(CaseSummary(
            id=case["id"],
            patient_id=case["patient_id"],
            case_number=case.get("case_number", ""),
            case_title=case.get("case_title", ""),
            case_type=case.get("case_type", "acute"),
            status=case.get("status", "active"),
            severity=case.get("severity", "moderate"),
            started_at=case.get("started_at", ""),
            resolved_at=case.get("resolved_at"),
            last_visit_date=case.get("last_visit_date"),
            total_visits=case.get("total_visits", 0),
            total_photos=case.get("total_photos", 0),
            has_before_photo=False,
            has_after_photo=False
        ))
    
    return PatientWithVisits(
        patient=PatientProfile(**patient),
        visits=[Visit(**visit) for visit in visits],
        active_cases=case_summaries if case_summaries else None
    )

# Visit Routes
@app.post("/patients/{patient_id}/visits", response_model=dict)
async def create_visit(
    patient_id: int,
    visit: VisitCreate,
    current_doctor = Depends(get_current_doctor)
):
    try:
        # Check if patient exists and belongs to current doctor
        existing_patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not existing_patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Validate that patient_id in URL matches patient_id in body
        if visit.patient_id != patient_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient ID in URL must match patient ID in request body"
            )
        
        # Validate note input type
        if visit.note_input_type and visit.note_input_type not in ["typed", "handwritten"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="note_input_type must be either 'typed' or 'handwritten'"
            )
        
        # If handwritten is selected, validate template is provided
        if visit.note_input_type == "handwritten" and not visit.selected_template_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="selected_template_id is required when note_input_type is 'handwritten'"
            )
        
        # If template is selected, verify it exists and belongs to the doctor
        if visit.selected_template_id:
            template = await db.get_pdf_template_by_id(visit.selected_template_id, current_doctor["firebase_uid"])
            if not template:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Selected PDF template not found"
                )
            if not template.get("is_active"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Selected PDF template is not active"
                )
        
        # Validate case_id if provided (case-based architecture)
        case_context = None
        if visit.case_id:
            case = await db.get_case_by_id(visit.case_id, current_doctor["firebase_uid"])
            if not case:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Case not found or does not belong to this doctor"
                )
            # Verify the case belongs to the same patient
            if case["patient_id"] != patient_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Case must belong to the same patient"
                )
            case_context = case
            print(f"Creating visit for case: {visit.case_id}")
        
        # Prepare visit data for Supabase
        visit_data = {
            "patient_id": patient_id,
            "doctor_firebase_uid": current_doctor["firebase_uid"],
            "visit_date": visit.visit_date,
            "visit_type": visit.visit_type,
            "chief_complaint": visit.chief_complaint,
            "note_input_type": visit.note_input_type or "typed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add case reference if provided
        if visit.case_id:
            visit_data["case_id"] = visit.case_id
            visit_data["is_case_opener"] = visit.is_case_opener
        
        # Add optional fields
        optional_fields = ["visit_time", "symptoms", "clinical_examination", "diagnosis", 
                          "treatment_plan", "medications", "tests_recommended", 
                          "follow_up_date", "notes", "selected_template_id"]
        
        for field in optional_fields:
            value = getattr(visit, field)
            if value:
                visit_data[field] = value
        
        # Handle vitals separately as JSON
        if visit.vitals:
            visit_data["vitals"] = visit.vitals.model_dump(exclude_unset=True)
        
        # Handle billing fields
        billing_fields = ["consultation_fee", "additional_charges", "discount", 
                         "payment_status", "payment_method", "payment_date", "notes_billing"]
        
        for field in billing_fields:
            value = getattr(visit, field)
            if value is not None:
                visit_data[field] = value
        
        # Calculate total amount if billing fields are provided
        if visit.consultation_fee is not None or visit.additional_charges is not None:
            consultation_fee = visit.consultation_fee or 0
            additional_charges = visit.additional_charges or 0
            discount = visit.discount or 0
            visit_data["total_amount"] = max(0, consultation_fee + additional_charges - discount)
        
        # Set default payment status if not provided
        if "payment_status" not in visit_data:
            visit_data["payment_status"] = "unpaid"
        
        # Create visit using database manager
        created_visit = await db.create_visit(visit_data)
        if created_visit:
            visit_id = created_visit["id"]
            print(f"Visit created successfully. ID: {visit_id}")
            
            # Clean up outdated patient history analyses since we added new data
            await db.cleanup_outdated_patient_history_analyses(patient_id, current_doctor["firebase_uid"])
            
            # AUTO-CREATE LAB REPORT REQUESTS if tests are recommended
            lab_requests_created = []
            if visit.tests_recommended and visit.tests_recommended.strip():
                try:
                    # Get doctor profile to check for lab contacts
                    doctor_profile = await db.get_doctor_by_firebase_uid(current_doctor["firebase_uid"])
                    
                    # Get patient details for the request
                    patient = await db.get_patient_by_id(visit.patient_id, current_doctor["firebase_uid"])
                    
                    if doctor_profile and patient:
                        # Parse the tests_recommended field to identify individual tests
                        tests_recommended = visit.tests_recommended.strip()
                        
                        # Try different common delimiters to split tests
                        test_list = []
                        for delimiter in [',', ';', '\n', '|']:
                            if delimiter in tests_recommended:
                                test_list = [test.strip() for test in tests_recommended.split(delimiter)]
                                break
                        
                        # If no delimiter found, treat as single test
                        if not test_list:
                            test_list = [tests_recommended]
                        
                        # Remove empty entries
                        test_list = [test for test in test_list if test.strip()]
                        
                        # Automatically determine lab type based on test keywords
                        pathology_keywords = ['blood', 'urine', 'stool', 'cbc', 'complete blood count', 'glucose', 'cholesterol', 'bilirubin', 'creatinine', 'urea', 'hemoglobin', 'culture', 'sensitivity', 'liver', 'kidney', 'thyroid', 'hormone', 'enzyme', 'protein', 'electrolyte', 'lipid', 'serum', 'plasma', 'wbc', 'rbc', 'platelet', 'hematocrit', 'biochemistry', 'microbiology', 'pathology', 'histopathology']
                        radiology_keywords = ['xray', 'x-ray', 'ct', 'scan', 'mri', 'ultrasound', 'echo', 'mammogram', 'bone', 'chest', 'abdomen', 'pelvis', 'spine', 'brain', 'cardiac', 'doppler', 'angiogram', 'radiolog', 'imaging', 'sonography', 'ecg', 'ekg', 'fluoroscopy']
                        
                        for test_name in test_list:
                            test_lower = test_name.lower()
                            
                            # Determine report type based on test keywords
                            report_type = None
                            if any(keyword in test_lower for keyword in pathology_keywords):
                                report_type = "pathology"
                            elif any(keyword in test_lower for keyword in radiology_keywords):
                                report_type = "radiology"
                            else:
                                # Default to pathology for unknown tests
                                report_type = "pathology"
                            
                            # Check if doctor has lab contact for this type
                            lab_phone = None
                            lab_name = None
                            
                            if report_type == "pathology" and doctor_profile.get("pathology_lab_phone"):
                                lab_phone = doctor_profile.get("pathology_lab_phone")
                                lab_name = doctor_profile.get("pathology_lab_name", "Pathology Lab")
                            elif report_type == "radiology" and doctor_profile.get("radiology_lab_phone"):
                                lab_phone = doctor_profile.get("radiology_lab_phone")
                                lab_name = doctor_profile.get("radiology_lab_name", "Radiology Lab")
                            
                            # Create lab report request if lab contact exists
                            if lab_phone:
                                # Ensure we have a valid lab_contact_id from the table
                                lab_contact_id = await db.ensure_lab_contact_exists(
                                    current_doctor["firebase_uid"], 
                                    lab_phone, 
                                    lab_name, 
                                    report_type
                                )
                                
                                request_token = str(uuid.uuid4())
                                request_data = {
                                    "visit_id": visit_id,
                                    "patient_id": visit.patient_id,
                                    "doctor_firebase_uid": current_doctor["firebase_uid"],
                                    "lab_contact_id": lab_contact_id,  # Link to actual lab contact
                                    "patient_name": f"{patient['first_name']} {patient['last_name']}",
                                    "report_type": report_type,
                                    "test_name": test_name.strip(),
                                    "instructions": f"Auto-generated request for test: {test_name.strip()}",
                                    "status": "pending",
                                    "request_token": request_token,
                                    "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                                    "created_at": datetime.now(timezone.utc).isoformat(),
                                    "updated_at": datetime.now(timezone.utc).isoformat()
                                }
                                
                                created_request = await db.create_lab_report_request(request_data)
                                if created_request:
                                    lab_requests_created.append({
                                        "request_id": created_request["id"],
                                        "test_name": test_name.strip(),
                                        "report_type": report_type,
                                        "lab_name": lab_name,
                                        "lab_phone": lab_phone,
                                        "request_token": request_token
                                    })
                                    print(f"Auto-created lab request for {test_name} -> {lab_name} ({lab_phone})")
                                else:
                                    print(f"Failed to create lab request for: {test_name}")
                            else:
                                print(f"No lab contact configured for {report_type} test: {test_name}")
                        
                except Exception as lab_error:
                    print(f"Error auto-creating lab requests: {lab_error}")
                    print(f"Traceback: {traceback.format_exc()}")
                    # Don't fail the visit creation if lab request creation fails
            
            response_data = {
                "message": "Visit created successfully", 
                "visit_id": visit_id,
                "total_amount": visit_data.get("total_amount", 0),
                "payment_status": visit_data.get("payment_status", "unpaid"),
                "note_input_type": visit_data.get("note_input_type", "typed"),
                "lab_requests_created": len(lab_requests_created),
                "lab_requests": lab_requests_created
            }
            
            # Add case info to response if visit is part of a case
            if visit.case_id and case_context:
                response_data["case_info"] = {
                    "case_id": visit.case_id,
                    "case_title": case_context.get("case_title"),
                    "case_status": case_context.get("status"),
                    "is_case_opener": visit.is_case_opener
                }

            try:
                print(f"🔍 DEBUG: About to sync pharmacy prescription for visit {visit_id}")
                print(f"🔍 DEBUG: Visit medications: {created_visit.get('medications')}")
                print(f"🔍 DEBUG: Doctor hospital: {current_doctor.get('hospital_name')}")
                await sync_pharmacy_prescription_from_visit(created_visit, current_doctor, existing_patient)
            except Exception as pharmacy_sync_error:
                print(f"❌ ERROR: Could not sync pharmacy prescription for visit {visit_id}: {pharmacy_sync_error}")
                print(f"Traceback: {traceback.format_exc()}")
            
            # If handwritten is selected, add template info to response
            if visit.note_input_type == "handwritten" and visit.selected_template_id:
                template = await db.get_pdf_template_by_id(visit.selected_template_id, current_doctor["firebase_uid"])
                if template:
                    response_data.update({
                        "handwriting_enabled": True,
                        "selected_template": {
                            "id": template["id"],
                            "name": template["template_name"],
                            "file_url": template["file_url"]
                        },
                        "next_step": "Please use the handwriting interface to complete your notes on the selected template."
                    })
            
            return response_data
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create visit in database"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected visit creation error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Visit creation error: {str(e)}"
        )

@app.get("/patients/{patient_id}/visits", response_model=list[Visit])
async def get_patient_visits(patient_id: int, current_doctor = Depends(get_current_doctor)):
    # Check if patient exists and belongs to current doctor
    existing_patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
    if not existing_patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found"
        )
    
    visits = await db.get_visits_by_patient_id(patient_id, current_doctor["firebase_uid"])
    return [Visit(**visit) for visit in visits]

@app.get("/visits/{visit_id}", response_model=dict)
async def get_visit_details(visit_id: int, current_doctor = Depends(get_current_doctor)):
    """
    Get visit details with remote prescriptions sent from this visit.
    Includes all prescription PDFs so they can be displayed in the visit screen.
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        # Get visit
        visit = await db.get_visit_by_id(visit_id, doctor_uid)
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get handwritten notes (prescriptions) for this visit in parallel
        notes = await db.get_handwritten_visit_notes_by_visit_id(visit_id, doctor_uid)
        
        # Extract remote prescriptions (notes that were sent or are remote type)
        remote_prescriptions = [
            {
                "id": n["id"],
                "file_url": n.get("handwritten_pdf_url"),
                "file_name": n.get("handwritten_pdf_filename"),
                "prescription_type": n.get("prescription_type", "general"),
                "note_type": n.get("note_type"),
                "sent_via_whatsapp": n.get("sent_via_whatsapp", False),
                "whatsapp_sent_at": n.get("whatsapp_sent_at"),
                "created_at": n.get("created_at"),
                "resend_endpoint": f"/handwritten-notes/{n['id']}/resend-whatsapp"
            }
            for n in (notes or [])
        ]
        
        # Sort by created_at descending
        remote_prescriptions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        # Build visit response with all fields
        visit_data = {
            "id": visit["id"],
            "patient_id": visit["patient_id"],
            "doctor_firebase_uid": visit["doctor_firebase_uid"],
            "visit_date": visit["visit_date"],
            "visit_time": visit.get("visit_time"),
            "visit_type": visit["visit_type"],
            "chief_complaint": visit["chief_complaint"],
            "symptoms": visit.get("symptoms"),
            "vitals": visit.get("vitals"),
            "clinical_examination": visit.get("clinical_examination"),
            "diagnosis": visit.get("diagnosis"),
            "treatment_plan": visit.get("treatment_plan"),
            "medications": visit.get("medications"),
            "tests_recommended": visit.get("tests_recommended"),
            "follow_up_date": visit.get("follow_up_date"),
            "notes": visit.get("notes"),
            "created_at": visit.get("created_at"),
            "updated_at": visit.get("updated_at"),
            "note_input_type": visit.get("note_input_type", "typed"),
            "selected_template_id": visit.get("selected_template_id"),
            "handwritten_pdf_url": visit.get("handwritten_pdf_url"),
            "handwritten_pdf_filename": visit.get("handwritten_pdf_filename"),
            # Billing fields
            "consultation_fee": visit.get("consultation_fee"),
            "additional_charges": visit.get("additional_charges"),
            "total_amount": visit.get("total_amount"),
            "payment_status": visit.get("payment_status"),
            "payment_method": visit.get("payment_method"),
            "payment_date": visit.get("payment_date"),
            "discount": visit.get("discount"),
            "notes_billing": visit.get("notes_billing"),
            # Case-based architecture (replaces deprecated parent_visit_id)
            "case_id": visit.get("case_id"),
            "is_case_opener": visit.get("is_case_opener", False),
            # Prescription status
            "prescription_status": visit.get("prescription_status"),
            "prescription_resolution_type": visit.get("prescription_resolution_type"),
            "prescription_resolution_note": visit.get("prescription_resolution_note"),
            # Remote prescriptions sent from this visit
            "remote_prescriptions": remote_prescriptions,
            "remote_prescriptions_count": len(remote_prescriptions),
            "has_whatsapp_prescription": any(rp["sent_via_whatsapp"] for rp in remote_prescriptions)
        }
        
        return visit_data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting visit details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get visit details: {str(e)}"
        )

@app.get("/visits/{visit_id}/linked-visits", response_model=dict, deprecated=True)
async def get_linked_visits(visit_id: int, current_doctor = Depends(get_current_doctor)):
    """
    DEPRECATED: This endpoint no longer works. Use case-based endpoints instead.
    
    - To get visits for a case: GET /cases/{case_id}/visits
    - To get case details with visits: GET /cases/{case_id}/details
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="This endpoint is deprecated. Use case-based endpoints instead: GET /cases/{case_id}/details or GET /patients/{patient_id}/cases"
    )

@app.post("/visits/{visit_id}/link-to-visit", response_model=dict, deprecated=True)
async def link_visit_to_parent(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    DEPRECATED: This endpoint no longer works. Use /visits/{visit_id}/assign-to-case instead.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="This endpoint is deprecated. Use POST /visits/{visit_id}/assign-to-case instead to assign visits to cases."
    )

@app.delete("/visits/{visit_id}/unlink", response_model=dict, deprecated=True)
async def unlink_visit(visit_id: int, current_doctor = Depends(get_current_doctor)):
    """
    DEPRECATED: This endpoint no longer works. Use /visits/{visit_id}/remove-from-case instead.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="This endpoint is deprecated. Use POST /visits/{visit_id}/remove-from-case instead."
    )

@app.get("/visits/{visit_id}/context-for-analysis", response_model=dict)
async def get_visit_context_for_analysis(visit_id: int, current_doctor = Depends(get_current_doctor)):
    """
    Get comprehensive context for AI analysis including linked visit history.
    This is used when analyzing reports to provide full context to the AI.
    """
    try:
        # Check if visit exists and belongs to current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get patient info
        patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Build the visit chain (previous visits from the same case)
        visit_chain = []
        if visit.get("case_id"):
            # Get all visits in this case
            case_visits = await db.get_visits_by_case(visit["case_id"], current_doctor["firebase_uid"])
            # Filter to visits before current one
            for v in case_visits:
                if v["id"] != visit["id"] and v.get("visit_date") and v["visit_date"] < visit.get("visit_date", ""):
                    # Get reports for this visit
                    v_reports = await db.get_reports_by_visit_id(v["id"], current_doctor["firebase_uid"])
                    # Get AI analyses
                    v_analyses = await db.get_ai_analyses_by_visit_id(v["id"], current_doctor["firebase_uid"])
                    
                    visit_chain.append({
                        "visit_id": v["id"],
                        "visit_date": v["visit_date"],
                        "visit_type": v["visit_type"],
                        "chief_complaint": v["chief_complaint"],
                        "symptoms": v.get("symptoms"),
                        "diagnosis": v.get("diagnosis"),
                        "treatment_plan": v.get("treatment_plan"),
                        "medications": v.get("medications"),
                        "tests_recommended": v.get("tests_recommended"),
                        "clinical_examination": v.get("clinical_examination"),
                        "reports": [{
                            "id": r["id"],
                            "file_name": r["file_name"],
                            "test_type": r.get("test_type"),
                            "uploaded_at": r["uploaded_at"]
                        } for r in v_reports],
                        "ai_analyses_summary": [{
                            "report_id": a.get("report_id"),
                            "document_summary": a.get("document_summary", "")[:200],
                            "key_findings": a.get("key_findings", [])
                        } for a in (v_analyses or [])[:3]]  # Limit to 3 most recent
                    })
        
        return {
            "current_visit": {
                "id": visit["id"],
                "visit_date": visit["visit_date"],
                "visit_type": visit["visit_type"],
                "chief_complaint": visit["chief_complaint"],
                "symptoms": visit.get("symptoms"),
                "diagnosis": visit.get("diagnosis"),
                "treatment_plan": visit.get("treatment_plan"),
                "medications": visit.get("medications"),
                "tests_recommended": visit.get("tests_recommended"),
                "clinical_examination": visit.get("clinical_examination"),
                "vitals": visit.get("vitals"),
                "case_id": visit.get("case_id")
            },
            "patient": {
                "id": patient["id"],
                "name": f"{patient['first_name']} {patient['last_name']}",
                "age": patient.get("date_of_birth"),
                "gender": patient.get("gender"),
                "blood_group": patient.get("blood_group"),
                "allergies": patient.get("allergies"),
                "medical_history": patient.get("medical_history")
            },
            "visit_history_chain": visit_chain,
            "context_summary": {
                "is_part_of_case": visit.get("case_id") is not None,
                "chain_length": len(visit_chain),
                "total_previous_visits": len(visit_chain),
                "has_previous_reports": any(len(v.get("reports", [])) > 0 for v in visit_chain),
                "has_previous_analyses": any(len(v.get("ai_analyses_summary", [])) > 0 for v in visit_chain)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting visit context: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get visit context: {str(e)}"
        )

@app.put("/visits/{visit_id}", response_model=dict)
async def update_visit(
    visit_id: int,
    visit_update: VisitUpdate,
    current_doctor = Depends(get_current_doctor)
):
    # Check if visit exists and belongs to current doctor
    existing_visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
    if not existing_visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visit not found"
        )
    
    # Get only the fields that were provided
    update_data = visit_update.model_dump(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )
    
    # Handle vitals separately - convert Vitals object to dict if it exists
    if "vitals" in update_data and update_data["vitals"]:
        vitals_obj = update_data["vitals"]
        if hasattr(vitals_obj, 'model_dump'):
            # It's a Pydantic model, convert to dict
            update_data["vitals"] = vitals_obj.model_dump(exclude_unset=True)
        elif isinstance(vitals_obj, dict):
            # It's already a dict, use as is
            update_data["vitals"] = vitals_obj
    
    # Add updated timestamp
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    success = await db.update_visit(visit_id, current_doctor["firebase_uid"], update_data)
    if success:
        if "medications" in update_data:
            try:
                updated_visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
                patient = await db.get_patient_by_id(existing_visit["patient_id"], current_doctor["firebase_uid"])
                if updated_visit and patient:
                    await sync_pharmacy_prescription_from_visit(updated_visit, current_doctor, patient)
            except Exception as pharmacy_sync_error:
                print(f"Warning: could not sync pharmacy prescription after update for visit {visit_id}: {pharmacy_sync_error}")
                print(f"Traceback: {traceback.format_exc()}")
        return {"message": "Visit updated successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update visit"
        )

@app.delete("/visits/{visit_id}", response_model=dict)
async def delete_visit(visit_id: int, current_doctor = Depends(get_current_doctor)):
    """Delete a specific visit and all associated files (reports, handwritten notes, PDFs, AI analysis)"""
    try:
        # Check if visit exists and belongs to current doctor
        existing_visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not existing_visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Initialize counters for cleanup summary
        cleanup_summary = {
            "deleted_reports": 0,
            "deleted_handwritten_notes": 0,
            "deleted_visit_reports": 0,
            "deleted_ai_analyses": 0,
            "total_files_deleted": 0,
            "storage_cleanup_errors": []
        }
        
        # Helper function to safely delete files from storage
        async def safe_delete_file(storage_path: str, file_type: str) -> bool:
            try:
                await supabase.storage.from_("medical-reports").remove([storage_path])
                print(f"✅ Deleted {file_type} file: {storage_path}")
                return True
            except Exception as storage_error:
                error_msg = f"Failed to delete {file_type} file {storage_path}: {str(storage_error)}"
                print(f"⚠️  {error_msg}")
                cleanup_summary["storage_cleanup_errors"].append(error_msg)
                return False
        
        print(f"🗑️  Starting comprehensive cleanup for visit {visit_id}")
        
        # 1. Delete regular reports and their files
        try:
            reports = await db.get_reports_by_visit_id(visit_id, current_doctor["firebase_uid"])
            cleanup_summary["deleted_reports"] = len(reports)
            
            for report in reports:
                if report.get("storage_path"):
                    if await safe_delete_file(report["storage_path"], "report"):
                        cleanup_summary["total_files_deleted"] += 1
        except Exception as reports_error:
            print(f"📄 Note: Could not fetch reports for cleanup: {reports_error}")
        
        # 2. Delete handwritten notes and their PDF files
        try:
            handwritten_notes = await db.get_handwritten_visit_notes_by_visit_id(visit_id, current_doctor["firebase_uid"])
            cleanup_summary["deleted_handwritten_notes"] = len(handwritten_notes)
            
            for note in handwritten_notes:
                if note.get("storage_path"):
                    if await safe_delete_file(note["storage_path"], "handwritten note"):
                        cleanup_summary["total_files_deleted"] += 1
        except Exception as notes_error:
            print(f"✏️  Note: Could not fetch handwritten notes for cleanup: {notes_error}")
        
        # 3. Delete visit-specific PDF files from visit record itself
        if existing_visit.get("handwritten_pdf_storage_path"):
            if await safe_delete_file(existing_visit["handwritten_pdf_storage_path"], "visit PDF"):
                cleanup_summary["total_files_deleted"] += 1
        
        # 4. Delete generated visit reports/PDFs
        try:
            visit_reports = await db.get_visit_reports_by_visit_id(visit_id, current_doctor["firebase_uid"])
            cleanup_summary["deleted_visit_reports"] = len(visit_reports)
            
            for visit_report in visit_reports:
                if visit_report.get("storage_path"):
                    if await safe_delete_file(visit_report["storage_path"], "visit report"):
                        cleanup_summary["total_files_deleted"] += 1
        except Exception as visit_reports_error:
            print(f"📋 Note: Could not fetch visit reports for cleanup: {visit_reports_error}")
        
        # 5. Clean up AI analysis data (database records only - no files)
        try:
            cleanup_summary["deleted_ai_analyses"] = await db.delete_ai_analyses_for_visit(visit_id, current_doctor["firebase_uid"])
        except Exception as ai_cleanup_error:
            print(f"🤖 Note: Could not cleanup AI analyses: {ai_cleanup_error}")
        
        # 6. Try to clean up empty folders (optional - storage will handle automatically)
        try:
            # Check if there's a dedicated folder for this visit
            visit_folder_patterns = [
                f"visits/{current_doctor['firebase_uid']}/visit_{visit_id}",
                f"handwritten_notes/{current_doctor['firebase_uid']}/visit_{visit_id}",
                f"reports/{current_doctor['firebase_uid']}/visit_{visit_id}"
            ]
            
            for folder_path in visit_folder_patterns:
                try:
                    folder_contents = await supabase.storage.from_("medical-reports").list(folder_path)
                    
                    if not folder_contents:
                        print(f"📁 Visit folder {folder_path} is empty (will be cleaned up automatically)")
                    elif len(folder_contents) <= 2:  # Often contains . and .. entries
                        print(f"📁 Visit folder {folder_path} contains {len(folder_contents)} items (minimal)")
                    else:
                        print(f"📁 Visit folder {folder_path} still contains {len(folder_contents)} items")
                except Exception:
                    pass  # Folder doesn't exist or can't be accessed - that's fine
                    
        except Exception as folder_error:
            print(f"📁 Note: Could not check visit folders: {folder_error}")
        
        # 7. Finally, delete the visit record from database (this handles remaining DB cleanup)
        print(f"🗑️  Deleting visit {visit_id} from database...")
        success = await db.delete_visit(visit_id, current_doctor["firebase_uid"])
        
        if success:
            # Log summary
            print(f"✅ Visit {visit_id} deleted successfully!")
            print(f"📊 Cleanup Summary:")
            print(f"   - Reports: {cleanup_summary['deleted_reports']}")
            print(f"   - Handwritten Notes: {cleanup_summary['deleted_handwritten_notes']}")
            print(f"   - Visit Reports: {cleanup_summary['deleted_visit_reports']}")
            print(f"   - AI Analyses: {cleanup_summary['deleted_ai_analyses']}")
            print(f"   - Total Files: {cleanup_summary['total_files_deleted']}")
            if cleanup_summary["storage_cleanup_errors"]:
                print(f"   - Storage Errors: {len(cleanup_summary['storage_cleanup_errors'])}")
            
            return {
                "message": "Visit and all associated files deleted successfully", 
                "visit_id": visit_id,
                "cleanup_summary": cleanup_summary
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete visit from database"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Unexpected visit deletion error: {type(e).__name__}: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Visit deletion error: {str(e)}"
        )

# Handwritten Notes Routes
@app.get("/visits/{visit_id}/handwriting-template", response_model=dict)
async def get_handwriting_template_for_visit(
    visit_id: int, 
    current_doctor = Depends(get_current_doctor)
):
    """Get the PDF template for handwriting for ANY visit (supports remote prescriptions)"""
    try:
        # Check if visit exists and belongs to current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # First try to get visit-specific template if set
        template = None
        template_id = visit.get("selected_template_id")
        if template_id:
            template = await db.get_pdf_template_by_id(template_id, current_doctor["firebase_uid"])
        
        # If no visit-specific template, get doctor's default template
        if not template:
            template = await db.get_doctor_prescription_template(current_doctor["firebase_uid"])
        
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No prescription template found. Please upload a template first."
            )
        
        # Get patient info for context
        patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
        
        return {
            "visit_id": visit_id,
            "template": {
                "id": template["id"],
                "name": template["template_name"],
                "file_url": template["file_url"],
                "file_name": template["file_name"]
            },
            "patient": {
                "name": f"{patient['first_name']} {patient['last_name']}" if patient else "Unknown",
                "id": visit["patient_id"]
            },
            "visit_info": {
                "date": visit["visit_date"],
                "type": visit["visit_type"],
                "chief_complaint": visit["chief_complaint"]
            },
            "upload_endpoint": f"/visits/{visit_id}/send-remote-prescription",
            "instructions": "Use a PDF editor or handwriting app to fill in the template, then upload the completed PDF."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting handwriting template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get handwriting template: {str(e)}"
        )

@app.post(
    "/visits/{visit_id}/upload-handwritten-pdf", 
    response_model=dict,
    tags=["Visits", "Prescriptions"],
    summary="Upload a handwritten prescription/note",
    description="""Upload a handwritten PDF prescription or note for a visit.

### Prescription Types:
- **general** (default): Standard prescription
- **empirical**: Initial prescription before test results (includes disclaimer)
- **follow_up**: Prescription after reviewing test results

### Form Data:
- **file**: PDF file (required)
- **send_whatsapp**: Send via WhatsApp (default: true)
- **custom_message**: Custom message for WhatsApp
- **prescription_type**: Type of prescription (default: general)

### Empirical Prescriptions:
When `prescription_type=empirical`, the prescription includes a disclaimer that it may be 
modified based on test results. The WhatsApp message will include this disclaimer.
"""
)
async def upload_handwritten_pdf(
    visit_id: int,
    request: Request,
    current_doctor = Depends(get_current_doctor)
):
    """Upload the completed handwritten PDF for a visit with optional prescription type"""
    try:
        # Check if visit exists and belongs to current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Parse multipart form data
        form = await request.form()
        files = form.getlist("file")
        send_whatsapp = form.get("send_whatsapp", "true").lower() == "true"
        custom_message = form.get("custom_message", "")
        prescription_type = form.get("prescription_type", "general")  # general, empirical, follow_up
        
        if not files or len(files) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF file is required"
            )
        
        file = files[0]  # Take the first file
        
        if not hasattr(file, 'filename') or not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Valid PDF file is required"
            )
        
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only PDF files are allowed"
            )
        
        # Read file content
        file_content = await file.read()
        file_size = len(file_content)
        
        # Validate file size (50MB limit)
        if file_size > 50 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File is too large. Maximum size is 50MB."
            )
        
        # Generate unique filename based on prescription type
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if prescription_type == "empirical":
            unique_filename = f"empirical_prescription_{visit_id}_{timestamp}.pdf"
            storage_folder = "empirical_prescriptions"
        elif prescription_type == "follow_up":
            unique_filename = f"followup_prescription_{visit_id}_{timestamp}.pdf"
            storage_folder = "followup_prescriptions"
        else:  # general
            unique_filename = f"handwritten_visit_{visit_id}_{timestamp}.pdf"
            storage_folder = "handwritten_notes"
        
        # Upload file to Supabase Storage
        storage_path = f"{storage_folder}/{current_doctor['firebase_uid']}/{unique_filename}"
        
        try:
            # Use async storage methods directly (not run_in_executor)
            await supabase.storage.from_("medical-reports").upload(
                path=storage_path,
                file=file_content,
                file_options={
                    "content-type": "application/pdf",
                    "x-upsert": "true"
                }
            )
            
            # get_public_url is async in the async client
            file_url = await supabase.storage.from_("medical-reports").get_public_url(storage_path)
            
            print(f"Handwritten PDF uploaded to storage: {storage_path}")
            
        except Exception as storage_error:
            print(f"Error uploading file to storage: {storage_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload file to storage: {str(storage_error)}"
            )
        
        # Update visit record with handwritten PDF info
        visit_update_data = {
            "handwritten_pdf_url": file_url,
            "handwritten_pdf_filename": unique_filename,
            "handwritten_pdf_size": file_size,
            "handwritten_pdf_storage_path": storage_path,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        await db.update_visit(visit_id, current_doctor["firebase_uid"], visit_update_data)
        
        # Get template info
        template = None
        if visit.get("selected_template_id"):
            template = await db.get_pdf_template_by_id(visit["selected_template_id"], current_doctor["firebase_uid"])
        
        # Create handwritten note record
        handwritten_note_data = {
            "visit_id": visit_id,
            "patient_id": visit["patient_id"],
            "doctor_firebase_uid": current_doctor["firebase_uid"],
            "template_id": visit.get("selected_template_id"),
            "original_template_url": template["file_url"] if template else "",
            "handwritten_pdf_url": file_url,
            "handwritten_pdf_filename": unique_filename,
            "handwritten_pdf_size": file_size,
            "storage_path": storage_path,
            "note_type": "handwritten",
            "prescription_type": prescription_type if prescription_type != "general" else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        created_note = await db.create_handwritten_visit_note(handwritten_note_data)
        if not created_note:
            print("Warning: Failed to create handwritten note record, but file was uploaded successfully")
        
        response_data = {
            "message": f"{prescription_type.capitalize()} prescription uploaded successfully" if prescription_type != "general" else "Handwritten PDF uploaded successfully",
            "visit_id": visit_id,
            "file_url": file_url,
            "file_name": unique_filename,
            "file_size": file_size,
            "prescription_type": prescription_type,
            "template_used": template["template_name"] if template else "Unknown",
            "note_id": created_note["id"] if created_note else None,
            "whatsapp_sent": False,
            "whatsapp_error": None,
            "disclaimer_included": prescription_type == "empirical",
            "ai_analysis_available": True,
            "ai_analysis_endpoint": f"/handwritten-notes/{created_note['id']}/analyze" if created_note else None
        }
        
        # Initialize patient variable for WhatsApp
        patient = None
        
        # Send WhatsApp message if requested
        if send_whatsapp:
            patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
            if patient and patient.get("phone"):
                try:
                    # Use appropriate WhatsApp method based on prescription type
                    if prescription_type == "empirical":
                        whatsapp_result = await whatsapp_service.send_empirical_prescription(
                            patient_name=f"{patient['first_name']} {patient['last_name']}",
                            doctor_name=f"Dr. {current_doctor['first_name']} {current_doctor['last_name']}",
                            phone_number=patient["phone"],
                            pdf_url=file_url,
                            visit_date=visit["visit_date"],
                            custom_message=custom_message
                        )
                    else:
                        whatsapp_result = await whatsapp_service.send_handwritten_visit_note(
                            patient_name=f"{patient['first_name']} {patient['last_name']}",
                            doctor_name=f"Dr. {current_doctor['first_name']} {current_doctor['last_name']}",
                            phone_number=patient["phone"],
                            pdf_url=file_url,
                            visit_date=visit["visit_date"],
                            custom_message=custom_message
                        )
                    
                    if whatsapp_result["success"]:
                        response_data["whatsapp_sent"] = True
                        response_data["whatsapp_message_id"] = whatsapp_result.get("message_id")
                        
                        # Update handwritten note record with WhatsApp info
                        if created_note:
                            await db.update_handwritten_visit_note(
                                created_note["id"], 
                                current_doctor["firebase_uid"], 
                                {
                                    "sent_via_whatsapp": True,
                                    "whatsapp_message_id": whatsapp_result.get("message_id"),
                                    "updated_at": datetime.now(timezone.utc).isoformat()
                                }
                            )
                    else:
                        response_data["whatsapp_error"] = whatsapp_result.get("error", "Unknown WhatsApp error")
                        
                except Exception as whatsapp_error:
                    print(f"WhatsApp sending error: {whatsapp_error}")
                    response_data["whatsapp_error"] = str(whatsapp_error)
            else:
                response_data["whatsapp_error"] = "Patient phone number not available"
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error uploading handwritten PDF: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload handwritten PDF: {str(e)}"
        )


@app.get(
    "/visits/{visit_id}/handwritten-notes", 
    response_model=List[HandwrittenVisitNote],
    tags=["Visits", "Prescriptions"],
    summary="Get handwritten notes for a visit",
    description="""Get all handwritten notes/prescriptions for a specific visit.

Use the `prescription_type` filter to get specific types:
- `empirical` - Initial prescriptions before test results
- `general` - Standard prescriptions
- `follow_up` - Follow-up prescriptions after test results
"""
)
async def get_visit_handwritten_notes(
    visit_id: int,
    prescription_type: Optional[str] = Query(
        default=None,
        description="Filter by prescription type: 'empirical', 'general', or 'follow_up'"
    ),
    current_doctor = Depends(get_current_doctor)
):
    """Get all handwritten notes for a specific visit with optional filtering"""
    try:
        # Check if visit exists and belongs to current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        notes = await db.get_handwritten_visit_notes_by_visit_id(visit_id, current_doctor["firebase_uid"])
        
        # Filter by prescription_type if provided
        if prescription_type:
            notes = [n for n in notes if n.get("prescription_type") == prescription_type]
        
        return [HandwrittenVisitNote(**note) for note in notes]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting handwritten notes: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get handwritten notes: {str(e)}"
        )


@app.get("/patients/{patient_id}/handwritten-notes", response_model=List[HandwrittenVisitNote])
async def get_patient_handwritten_notes(
    patient_id: int, 
    current_doctor = Depends(get_current_doctor)
):
    """Get all handwritten notes for a specific patient"""
    try:
        # Check if patient exists and belongs to current doctor
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        notes = await db.get_handwritten_visit_notes_by_patient_id(patient_id, current_doctor["firebase_uid"])
        return [HandwrittenVisitNote(**note) for note in notes]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting patient handwritten notes: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get patient handwritten notes: {str(e)}"
        )


@app.get(
    "/visits/{visit_id}/prescriptions/empirical",
    response_model=List[HandwrittenVisitNote],
    tags=["Prescriptions", "Visits"],
    summary="Get empirical prescriptions for a visit",
    description="Get all empirical (initial) prescriptions for a visit - prescriptions given before test results"
)
async def get_visit_empirical_prescriptions(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get empirical prescriptions for a specific visit"""
    try:
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        notes = await db.get_handwritten_visit_notes_by_visit_id(visit_id, current_doctor["firebase_uid"])
        empirical_notes = [n for n in notes if n.get("prescription_type") == "empirical"]
        
        return [HandwrittenVisitNote(**note) for note in empirical_notes]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting empirical prescriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get empirical prescriptions: {str(e)}"
        )


@app.get(
    "/visits/{visit_id}/prescriptions/general",
    response_model=List[HandwrittenVisitNote],
    tags=["Prescriptions", "Visits"],
    summary="Get general prescriptions for a visit",
    description="Get all general (standard) prescriptions for a visit"
)
async def get_visit_general_prescriptions(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get general prescriptions for a specific visit"""
    try:
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        notes = await db.get_handwritten_visit_notes_by_visit_id(visit_id, current_doctor["firebase_uid"])
        # General prescriptions have prescription_type as None or "general"
        general_notes = [n for n in notes if n.get("prescription_type") in (None, "general")]
        
        return [HandwrittenVisitNote(**note) for note in general_notes]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting general prescriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get general prescriptions: {str(e)}"
        )


@app.get(
    "/visits/{visit_id}/prescriptions/remote",
    response_model=List[dict],
    tags=["Prescriptions", "Visits"],
    summary="Get remote prescriptions for a visit",
    description="Get all prescriptions sent remotely (via WhatsApp without in-person visit)"
)
async def get_visit_remote_prescriptions(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get remote prescriptions sent for a specific visit"""
    try:
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get all notes that were sent via WhatsApp
        notes = await db.get_handwritten_visit_notes_by_visit_id(visit_id, current_doctor["firebase_uid"])
        remote_notes = [n for n in notes if n.get("sent_via_whatsapp") is True]
        
        # Format response with focus on WhatsApp delivery info
        remote_prescriptions = []
        for note in remote_notes:
            remote_prescriptions.append({
                "id": note["id"],
                "visit_id": note["visit_id"],
                "prescription_type": note.get("prescription_type") or "general",
                "file_url": note["handwritten_pdf_url"],
                "file_name": note["handwritten_pdf_filename"],
                "sent_via_whatsapp": True,
                "whatsapp_message_id": note.get("whatsapp_message_id"),
                "sent_at": note.get("updated_at"),
                "created_at": note["created_at"]
            })
        
        return remote_prescriptions
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting remote prescriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get remote prescriptions: {str(e)}"
        )


@app.get(
    "/patients/{patient_id}/prescriptions/empirical",
    response_model=List[HandwrittenVisitNote],
    tags=["Prescriptions"],
    summary="Get all empirical prescriptions for a patient",
    description="Get all empirical prescriptions across all patient visits"
)
async def get_patient_empirical_prescriptions(
    patient_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get all empirical prescriptions for a patient"""
    try:
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        notes = await db.get_handwritten_visit_notes_by_patient_id(patient_id, current_doctor["firebase_uid"])
        empirical_notes = [n for n in notes if n.get("prescription_type") == "empirical"]
        
        return [HandwrittenVisitNote(**note) for note in empirical_notes]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting patient empirical prescriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get patient empirical prescriptions: {str(e)}"
        )


@app.get(
    "/patients/{patient_id}/prescriptions/general",
    response_model=List[HandwrittenVisitNote],
    tags=["Prescriptions"],
    summary="Get all general prescriptions for a patient",
    description="Get all general prescriptions across all patient visits"
)
async def get_patient_general_prescriptions(
    patient_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get all general prescriptions for a patient"""
    try:
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        notes = await db.get_handwritten_visit_notes_by_patient_id(patient_id, current_doctor["firebase_uid"])
        general_notes = [n for n in notes if n.get("prescription_type") in (None, "general")]
        
        return [HandwrittenVisitNote(**note) for note in general_notes]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting patient general prescriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get patient general prescriptions: {str(e)}"
        )


@app.get(
    "/patients/{patient_id}/prescriptions/remote",
    response_model=List[dict],
    tags=["Prescriptions"],
    summary="Get all remote prescriptions for a patient",
    description="Get all remote prescriptions sent via WhatsApp across all patient visits"
)
async def get_patient_remote_prescriptions(
    patient_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get all remote prescriptions sent for a patient"""
    try:
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Get all notes for this patient that were sent via WhatsApp
        notes = await db.get_handwritten_visit_notes_by_patient_id(patient_id, current_doctor["firebase_uid"])
        remote_notes = [n for n in notes if n.get("sent_via_whatsapp") is True]
        
        # Format response with focus on WhatsApp delivery info
        remote_prescriptions = []
        for note in remote_notes:
            remote_prescriptions.append({
                "id": note["id"],
                "visit_id": note["visit_id"],
                "prescription_type": note.get("prescription_type") or "general",
                "file_url": note["handwritten_pdf_url"],
                "file_name": note["handwritten_pdf_filename"],
                "sent_via_whatsapp": True,
                "whatsapp_message_id": note.get("whatsapp_message_id"),
                "sent_at": note.get("updated_at"),
                "created_at": note["created_at"]
            })
        
        return remote_prescriptions
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting patient remote prescriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get patient remote prescriptions: {str(e)}"
        )

@app.get("/handwritten-notes/{note_id}/download")
async def download_handwritten_note(
    note_id: int, 
    current_doctor = Depends(get_current_doctor)
):
    """Download a specific handwritten note PDF"""
    try:
        # Get the handwritten note
        note = await db.get_handwritten_visit_note_by_id(note_id, current_doctor["firebase_uid"])
        if not note:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Handwritten note not found"
            )
        
        # Download file from Supabase Storage using async non-blocking download
        storage_path = note["storage_path"]
        if not storage_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File storage path not found"
            )
        
        try:
            # Use async downloader to prevent blocking during file download
            file_response = await file_downloader.download_from_supabase_storage(
                supabase_client=supabase,
                bucket_name="medical-reports",
                file_path=storage_path
            )
            
            if not file_response:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="File not found in storage"
                )
            
            return Response(
                content=file_response,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="{note["handwritten_pdf_filename"]}"'
                }
            )
            
        except Exception as download_error:
            print(f"Error downloading handwritten note: {download_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to download file: {str(download_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in download handwritten note: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download handwritten note: {str(e)}"
        )

@app.delete(
    "/handwritten-notes/{note_id}",
    response_model=dict,
    tags=["Prescriptions", "Visits"],
    summary="Delete a handwritten note or prescription",
    description="""Delete a handwritten note/prescription permanently.
    
This will:
- Delete the PDF from cloud storage
- Remove the database record
- Work for any prescription type (general, empirical, follow-up)

⚠️ **Warning**: This action cannot be undone.
"""
)
async def delete_handwritten_note(
    note_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Delete a handwritten note or prescription"""
    try:
        # Get the handwritten note
        note = await db.get_handwritten_visit_note_by_id(note_id, current_doctor["firebase_uid"])
        if not note:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Handwritten note not found"
            )
        
        # Delete file from storage if it exists
        if note.get("storage_path"):
            try:
                await supabase.storage.from_("medical-reports").remove([note["storage_path"]])
                print(f"Deleted file from storage: {note['storage_path']}")
            except Exception as storage_error:
                print(f"Warning: Failed to delete file from storage: {storage_error}")
                # Continue with deletion even if storage deletion fails
        
        # Delete from database
        success = await db.delete_handwritten_visit_note(note_id, current_doctor["firebase_uid"])
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete handwritten note from database"
            )
        
        # Handle prescription_type that might be None
        prescription_type = note.get("prescription_type") or "general"
        prescription_label = prescription_type.capitalize() if prescription_type else "General"
        
        return {
            "message": f"{prescription_label} prescription deleted successfully",
            "note_id": note_id,
            "file_deleted": True,
            "prescription_type": prescription_type
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting handwritten note: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete handwritten note: {str(e)}"
        )

@app.post("/handwritten-notes/{note_id}/resend-whatsapp", response_model=dict)
async def resend_handwritten_note_whatsapp(
    note_id: int, 
    custom_message: Optional[str] = None,
    current_doctor = Depends(get_current_doctor)
):
    """Resend a handwritten note via WhatsApp"""
    try:
        # Get the handwritten note
        note = await db.get_handwritten_visit_note_by_id(note_id, current_doctor["firebase_uid"])
        if not note:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Handwritten note not found"
            )
        
        # Get visit and patient information
        visit = await db.get_visit_by_id(note["visit_id"], current_doctor["firebase_uid"])
        patient = await db.get_patient_by_id(note["patient_id"], current_doctor["firebase_uid"])
        
        if not patient or not patient.get("phone"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient phone number not available"
            )
        
        # Send WhatsApp message
        whatsapp_result = await whatsapp_service.send_handwritten_visit_note(
            patient_name=f"{patient['first_name']} {patient['last_name']}",
            doctor_name=f"Dr. {current_doctor['first_name']} {current_doctor['last_name']}",
            phone_number=patient["phone"],
            pdf_url=note["handwritten_pdf_url"],
            visit_date=visit["visit_date"] if visit else "Unknown",
            custom_message=custom_message or ""
        )
        
        if whatsapp_result["success"]:
            # Update note with WhatsApp info
            await db.update_handwritten_visit_note(
                note_id, 
                current_doctor["firebase_uid"], 
                {
                    "sent_via_whatsapp": True,
                    "whatsapp_message_id": whatsapp_result.get("message_id"),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
            )
            
            return {
                "message": "Handwritten note sent via WhatsApp successfully",
                "whatsapp_message_id": whatsapp_result.get("message_id"),
                "patient_name": f"{patient['first_name']} {patient['last_name']}",
                "patient_phone": patient["phone"]
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to send WhatsApp message: {whatsapp_result.get('error', 'Unknown error')}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error resending handwritten note via WhatsApp: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resend handwritten note via WhatsApp: {str(e)}"
        )

@app.post("/handwritten-notes/{note_id}/analyze", response_model=dict)
async def analyze_handwritten_note(
    note_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Trigger AI analysis for a handwritten prescription PDF.
    Uses Gemini 3 Pro's multimodal capabilities to read and interpret handwriting.
    Can be used to re-analyze an existing handwritten note.
    """
    try:
        # Check if AI is enabled for this doctor
        check_ai_enabled(current_doctor)
        
        # Get the handwritten note
        note = await db.get_handwritten_visit_note_by_id(note_id, current_doctor["firebase_uid"])
        if not note:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Handwritten note not found"
            )
        
        if not ai_analysis_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI analysis service is not available"
            )
        
        # Download the PDF from storage
        storage_path = note["storage_path"]
        if not storage_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF file storage path not found"
            )
        
        # Download the file for analysis
        file_content = await file_downloader.download_from_supabase_storage(
            supabase_client=supabase,
            bucket_name="medical-reports",
            file_path=storage_path
        )
        
        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Could not download PDF file from storage"
            )
        
        # Get visit and patient context
        visit = await db.get_visit_by_id(note["visit_id"], current_doctor["firebase_uid"])
        patient = await db.get_patient_by_id(note["patient_id"], current_doctor["firebase_uid"])
        
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get case visit chain context for continuity of care
        visit_chain_context = []
        if visit.get("case_id"):
            print(f"📎 This visit is part of a case - fetching visit chain context for handwritten analysis")
            try:
                visit_chain_context = await db.get_visits_by_case(visit["case_id"], current_doctor["firebase_uid"])
                # Remove current visit from chain
                visit_chain_context = [v for v in visit_chain_context if v["id"] != note["visit_id"]]
                
                # Enrich with previous handwritten notes if available
                for chain_visit in visit_chain_context:
                    chain_notes = await db.get_handwritten_visit_notes_by_visit_id(chain_visit["id"], current_doctor["firebase_uid"])
                    if chain_notes:
                        chain_visit["handwritten_summary"] = chain_notes[0].get("ai_analysis_raw", "")[:300] if chain_notes[0].get("ai_analysis_raw") else ""
                
                print(f"✅ Found {len(visit_chain_context)} case visits for handwritten context")
            except Exception as chain_error:
                print(f"⚠️ Could not fetch visit chain context: {chain_error}")
                visit_chain_context = []
        
        print(f"🖊️ Starting AI analysis for handwritten note {note_id}")
        
        # Perform AI analysis with visit chain context
        ai_result = await ai_analysis_service.analyze_handwritten_prescription(
            file_content=file_content,
            file_name=note["handwritten_pdf_filename"],
            patient_context=patient,
            visit_context=visit,
            doctor_context=current_doctor,
            visit_chain_context=visit_chain_context if visit_chain_context else None
        )
        
        if ai_result["success"]:
            print(f"✅ AI analysis completed for handwritten note {note_id}")
            print(f"   Confidence: {ai_result['analysis'].get('confidence_score', 0):.2f}")
            
            # Update handwritten note record with AI analysis
            try:
                await db.update_handwritten_visit_note(
                    note_id,
                    current_doctor["firebase_uid"],
                    {
                        "ai_analysis_raw": ai_result["analysis"].get("raw_analysis", "")[:10000],
                        "ai_analysis_confidence": ai_result["analysis"].get("confidence_score", 0),
                        "ai_analysis_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                )
            except Exception as update_error:
                print(f"Warning: Could not save AI analysis to database: {update_error}")
            
            return {
                "success": True,
                "message": "AI analysis completed successfully",
                "note_id": note_id,
                "analysis": {
                    "raw_analysis": ai_result["analysis"].get("raw_analysis", ""),
                    "confidence_score": ai_result["analysis"].get("confidence_score", 0),
                    "extracted_medications": ai_result["analysis"].get("extracted_medications", []),
                    "extracted_diagnosis": ai_result["analysis"].get("extracted_diagnosis", ""),
                    "legibility_score": ai_result["analysis"].get("legibility_score", 7),
                    "structured_analysis": ai_result["analysis"].get("structured_analysis", {}),
                    "model_used": ai_result.get("model_used", "gemini-3-pro-preview"),
                    "processed_at": ai_result.get("processed_at")
                }
            }
        else:
            error_msg = ai_result.get("error", "Analysis failed")
            print(f"❌ AI analysis failed for handwritten note {note_id}: {error_msg}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"AI analysis failed: {error_msg}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error analyzing handwritten note: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze handwritten note: {str(e)}"
        )

@app.get("/handwritten-notes/{note_id}/analysis", response_model=dict)
async def get_handwritten_note_analysis(
    note_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get the AI analysis for a specific handwritten note"""
    try:
        # Get the handwritten note
        note = await db.get_handwritten_visit_note_by_id(note_id, current_doctor["firebase_uid"])
        if not note:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Handwritten note not found"
            )
        
        # Check if analysis exists
        if not note.get("ai_analysis_raw"):
            return {
                "has_analysis": False,
                "message": "No AI analysis available for this handwritten note. Use POST /handwritten-notes/{note_id}/analyze to generate analysis."
            }
        
        return {
            "has_analysis": True,
            "note_id": note_id,
            "analysis": {
                "raw_analysis": note.get("ai_analysis_raw", ""),
                "confidence_score": float(note.get("ai_analysis_confidence", 0)),
                "analyzed_at": note.get("ai_analysis_at"),
                "extracted_diagnosis": note.get("ai_extracted_diagnosis", ""),
                "extracted_medications": note.get("ai_extracted_medications", []),
                "legibility_score": note.get("ai_legibility_score", 7)
            },
            "note_details": {
                "visit_id": note["visit_id"],
                "patient_id": note["patient_id"],
                "file_name": note["handwritten_pdf_filename"],
                "file_url": note["handwritten_pdf_url"],
                "created_at": note.get("created_at")
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting handwritten note analysis: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get handwritten note analysis: {str(e)}"
        )

# ============================================================================
# REMOTE PRESCRIPTION FEATURE
# Allows doctors to send prescriptions to patients without requiring a new visit
# Useful when: patient uploads reports, doctor reviews them, and needs to send
# a prescription remotely without the patient coming back physically
# ============================================================================

@app.get("/doctor/pending-prescriptions", response_model=dict)
async def get_visits_pending_prescriptions(
    current_doctor = Depends(get_current_doctor)
):
    """
    Get all visits that have reports uploaded but no prescription sent yet.
    Helps doctors see which patients need remote prescriptions.
    OPTIMIZED: Uses parallel queries to avoid N+1 problem.
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        # Get all visits for this doctor (already filtered to recent)
        all_visits = await db.get_all_visits_by_doctor(doctor_uid)
        
        if not all_visits:
            return {
                "pending_count": 0,
                "visits": [],
                "message": "No pending prescriptions"
            }
        
        # Filter out already resolved visits first (before any DB calls)
        unresolved_visits = [v for v in all_visits if v.get("prescription_status") != "resolved"]
        
        if not unresolved_visits:
            return {
                "pending_count": 0,
                "visits": [],
                "message": "No pending prescriptions"
            }
        
        # Collect unique patient IDs and visit IDs
        visit_ids = [v["id"] for v in unresolved_visits]
        patient_ids = list(set(v["patient_id"] for v in unresolved_visits))
        
        # PARALLEL: Fetch all reports, notes, and patients in parallel batches
        reports_tasks = [db.get_reports_by_visit_id(vid, doctor_uid) for vid in visit_ids]
        notes_tasks = [db.get_handwritten_visit_notes_by_visit_id(vid, doctor_uid) for vid in visit_ids]
        patients_tasks = [db.get_patient_by_id(pid, doctor_uid) for pid in patient_ids]
        
        # Execute all queries in parallel
        all_results = await asyncio.gather(
            *reports_tasks,
            *notes_tasks,
            *patients_tasks,
            return_exceptions=True
        )
        
        # Split results
        num_visits = len(visit_ids)
        reports_results = all_results[:num_visits]
        notes_results = all_results[num_visits:num_visits*2]
        patients_results = all_results[num_visits*2:]
        
        # Build lookup maps
        reports_by_visit = {visit_ids[i]: (r if not isinstance(r, Exception) else []) for i, r in enumerate(reports_results)}
        notes_by_visit = {visit_ids[i]: (n if not isinstance(n, Exception) else []) for i, n in enumerate(notes_results)}
        patients_by_id = {patient_ids[i]: (p if not isinstance(p, Exception) else None) for i, p in enumerate(patients_results)}
        
        pending_visits = []
        
        for visit in unresolved_visits:
            reports = reports_by_visit.get(visit["id"], [])
            notes = notes_by_visit.get(visit["id"], [])
            
            # Visit needs attention if has reports but no WhatsApp prescription sent
            has_reports = reports and len(reports) > 0
            has_prescription_sent = notes and any(n.get("sent_via_whatsapp") for n in notes)
            
            if has_reports and not has_prescription_sent:
                patient = patients_by_id.get(visit["patient_id"])
                
                pending_visits.append({
                    "visit_id": visit["id"],
                    "visit_date": visit["visit_date"],
                    "patient_name": f"{patient['first_name']} {patient['last_name']}" if patient else "Unknown",
                    "patient_phone": patient.get("phone") if patient else None,
                    "chief_complaint": visit["chief_complaint"],
                    "reports_count": len(reports),
                    "reports_uploaded_at": max(r["uploaded_at"] for r in reports) if reports else None,
                    "prescription_needed": True,
                    "remote_prescription_url": f"/visits/{visit['id']}/remote-prescription-context"
                })
        
        # Sort by most recent report upload
        pending_visits.sort(key=lambda x: x.get("reports_uploaded_at", ""), reverse=True)
        
        return {
            "pending_count": len(pending_visits),
            "visits": pending_visits,
            "message": f"You have {len(pending_visits)} visit(s) with reports awaiting prescription"
        }
        
    except Exception as e:
        print(f"Error getting pending prescriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get pending prescriptions: {str(e)}"
        )

class ResolveVisitRequest(BaseModel):
    resolution_type: str = "in_person"  # "in_person", "no_prescription_needed", "referred", "patient_no_show", "other"
    resolution_note: Optional[str] = None

@app.patch(
    "/visits/{visit_id}/pending-status", 
    response_model=dict,
    tags=["Visits", "Prescriptions"],
    summary="Resolve or update pending visit status",
    description="Mark a visit as resolved without sending a remote prescription"
)
async def resolve_pending_visit(
    visit_id: int,
    resolution: ResolveVisitRequest = Body(default=ResolveVisitRequest()),
    current_doctor = Depends(get_current_doctor)
):
    """
    Mark a visit as resolved without sending a remote prescription.
    Use cases:
    - Patient will come in person for prescription
    - No prescription needed (reports are normal)
    - Patient referred to specialist
    - Patient didn't show up / cancelled
    """
    try:
        # Get visit
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        valid_types = ["in_person", "no_prescription_needed", "referred", "patient_no_show", "other"]
        if resolution.resolution_type not in valid_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid resolution_type. Must be one of: {', '.join(valid_types)}"
            )
        
        # Update visit with resolution status
        update_data = {
            "prescription_status": "resolved",
            "prescription_resolution_type": resolution.resolution_type,
            "prescription_resolution_note": resolution.resolution_note,
            "prescription_resolved_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        success = await db.update_visit(visit_id, current_doctor["firebase_uid"], update_data)
        
        if success:
            return {
                "message": "Visit marked as resolved",
                "visit_id": visit_id,
                "resolution_type": resolution.resolution_type,
                "resolution_note": resolution.resolution_note
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update visit"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error resolving pending visit: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve pending visit: {str(e)}"
        )

@app.patch(
    "/visits/{visit_id}/reopen-pending", 
    response_model=dict,
    tags=["Visits", "Prescriptions"],
    summary="Reopen a resolved pending visit"
)
async def reopen_pending_visit(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Reopen a previously resolved visit (undo resolve)"""
    try:
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Clear resolution status
        update_data = {
            "prescription_status": None,
            "prescription_resolution_type": None,
            "prescription_resolution_note": None,
            "prescription_resolved_at": None,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        success = await db.update_visit(visit_id, current_doctor["firebase_uid"], update_data)
        
        if success:
            return {
                "message": "Visit reopened",
                "visit_id": visit_id
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to reopen visit"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error reopening visit: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reopen visit: {str(e)}"
        )

@app.get("/visits/{visit_id}/remote-prescription-context", response_model=dict)
async def get_remote_prescription_context(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Get all context needed to create a remote prescription for an existing visit.
    Returns: visit details, patient info, uploaded reports, AI analyses, and prescription template.
    OPTIMIZED: Uses parallel queries for faster response.
    
    Use case: Patient visited, got tests ordered, uploaded reports. Doctor reviews and 
    can now send prescription remotely without patient coming back.
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        # Get visit first (needed for patient_id)
        visit = await db.get_visit_by_id(visit_id, doctor_uid)
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # PARALLEL: Fetch all related data in parallel
        patient_task = db.get_patient_by_id(visit["patient_id"], doctor_uid)
        reports_task = db.get_reports_by_visit_id(visit_id, doctor_uid)
        ai_analyses_task = db.get_ai_analyses_by_visit_id(visit_id, doctor_uid)
        notes_task = db.get_handwritten_visit_notes_by_visit_id(visit_id, doctor_uid)
        template_task = db.get_doctor_prescription_template(doctor_uid)
        
        patient, reports, ai_analyses, existing_notes, template = await asyncio.gather(
            patient_task, reports_task, ai_analyses_task, notes_task, template_task
        )
        
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        return {
            "visit": {
                "id": visit["id"],
                "date": visit["visit_date"],
                "type": visit["visit_type"],
                "chief_complaint": visit["chief_complaint"],
                "symptoms": visit.get("symptoms"),
                "diagnosis": visit.get("diagnosis"),
                "treatment_plan": visit.get("treatment_plan"),
                "medications": visit.get("medications"),
                "tests_recommended": visit.get("tests_recommended"),
                "clinical_examination": visit.get("clinical_examination")
            },
            "patient": {
                "id": patient["id"],
                "name": f"{patient['first_name']} {patient['last_name']}",
                "phone": patient.get("phone"),
                "whatsapp_available": bool(patient.get("phone")),
                "age": patient.get("date_of_birth"),
                "gender": patient.get("gender"),
                "allergies": patient.get("allergies"),
                "medical_history": patient.get("medical_history")
            },
            "reports": [{
                "id": r["id"],
                "file_name": r["file_name"],
                "file_url": r["file_url"],
                "test_type": r.get("test_type"),
                "uploaded_at": r["uploaded_at"],
                "has_ai_analysis": any(a["report_id"] == r["id"] for a in ai_analyses) if ai_analyses else False
            } for r in (reports or [])],
            "ai_analyses_summary": [{
                "report_id": a["report_id"],
                "key_findings": a.get("key_findings", []),
                "document_summary": a.get("document_summary", "")[:300],
                "clinical_correlation": a.get("clinical_correlation", "")[:300],
                "critical_findings": a.get("critical_findings", "")[:200]
            } for a in (ai_analyses or [])[:5]],
            "existing_prescriptions": [{
                "id": n["id"],
                "file_url": n["handwritten_pdf_url"],
                "created_at": n.get("created_at"),
                "sent_via_whatsapp": n.get("sent_via_whatsapp", False)
            } for n in (existing_notes or [])],
            "prescription_template": {
                "available": template is not None,
                "id": template["id"] if template else None,
                "name": template["template_name"] if template else None,
                "file_url": template["file_url"] if template else None
            },
            "remote_prescription_endpoint": f"/visits/{visit_id}/send-remote-prescription",
            "instructions": "Review the reports and AI analyses, then upload a handwritten prescription PDF to send to the patient via WhatsApp."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting remote prescription context: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get remote prescription context: {str(e)}"
        )

@app.post("/visits/{visit_id}/send-remote-prescription", response_model=dict)
async def send_remote_prescription(
    visit_id: int,
    request: Request,
    current_doctor = Depends(get_current_doctor)
):
    """
    Upload a prescription PDF and send it directly to the patient via WhatsApp.
    
    USE CASES:
    1. After reviewing uploaded lab reports (typical remote prescription flow)
    2. Directly from any visit - doctor writes prescription and sends it
    3. Follow-up prescriptions without requiring new lab reports
    4. Any situation where doctor wants to send a prescription remotely
    
    Form data:
    - file: PDF file (required)
    - custom_message: Custom WhatsApp message (optional)
    - prescription_type: Type of prescription - "medication", "follow_up", "report_review", "general" (optional)
    - send_whatsapp: Whether to send via WhatsApp, default true (optional)
    """
    try:
        # Get visit
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get patient for WhatsApp
        patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Parse form data
        form = await request.form()
        files = form.getlist("file")
        custom_message = form.get("custom_message", "")
        prescription_type = form.get("prescription_type", "report_review")
        send_whatsapp = form.get("send_whatsapp", "true").lower() == "true"
        
        if not files or len(files) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF file is required"
            )
        
        file = files[0]
        
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only PDF files are accepted"
            )
        
        # Read file content
        file_content = await file.read()
        file_size = len(file_content)
        
        # Validate file size (max 10MB)
        if file_size > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File size must be less than 10MB"
            )
        
        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"remote_prescription_{visit_id}_{timestamp}.pdf"
        storage_path = f"{current_doctor['firebase_uid']}/prescriptions/{unique_filename}"
        
        # Upload to Supabase Storage
        upload_response = await supabase.storage.from_("medical-reports").upload(
            storage_path,
            file_content,
            {"content-type": "application/pdf"}
        )
        
        # Get public URL
        file_url = await supabase.storage.from_("medical-reports").get_public_url(storage_path)
        
        print(f"📤 Remote prescription uploaded: {file_url}")
        
        # Save as handwritten note record
        note_data = {
            "visit_id": visit_id,
            "patient_id": visit["patient_id"],
            "doctor_firebase_uid": current_doctor["firebase_uid"],
            "handwritten_pdf_url": file_url,
            "handwritten_pdf_filename": unique_filename,
            "storage_path": storage_path,
            "note_type": "remote_prescription",
            "prescription_type": prescription_type,
            "sent_via_whatsapp": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        created_note = await db.create_handwritten_visit_note(note_data)
        
        response_data = {
            "message": "Remote prescription uploaded successfully",
            "visit_id": visit_id,
            "note_id": created_note["id"] if created_note else None,
            "file_url": file_url,
            "file_name": unique_filename,
            "prescription_type": prescription_type,
            "whatsapp_sent": False,
            "whatsapp_error": None,
            "ai_analysis_endpoint": f"/handwritten-notes/{created_note['id']}/analyze" if created_note else None
        }
        
        # Send via WhatsApp if requested and patient has phone
        if send_whatsapp:
            if patient.get("phone"):
                try:
                    # Build message based on prescription type
                    if prescription_type == "medication":
                        default_message = "Based on your test results, here is your prescription. Please follow the instructions carefully."
                    elif prescription_type == "follow_up":
                        default_message = "Please review the attached follow-up instructions based on your recent reports."
                    else:
                        default_message = "I have reviewed your reports. Please find the prescription attached."
                    
                    whatsapp_message = custom_message if custom_message else default_message
                    
                    whatsapp_result = await whatsapp_service.send_handwritten_visit_note(
                        patient_name=f"{patient['first_name']} {patient['last_name']}",
                        doctor_name=f"Dr. {current_doctor['first_name']} {current_doctor['last_name']}",
                        phone_number=patient["phone"],
                        pdf_url=file_url,
                        visit_date=visit["visit_date"],
                        custom_message=whatsapp_message
                    )
                    
                    if whatsapp_result["success"]:
                        response_data["whatsapp_sent"] = True
                        response_data["whatsapp_message_id"] = whatsapp_result.get("message_id")
                        print(f"✅ Remote prescription sent via WhatsApp to {patient['phone']}")
                        
                        # Update note record
                        if created_note:
                            await db.update_handwritten_visit_note(
                                created_note["id"],
                                current_doctor["firebase_uid"],
                                {
                                    "sent_via_whatsapp": True,
                                    "whatsapp_message_id": whatsapp_result.get("message_id"),
                                    "whatsapp_sent_at": datetime.now(timezone.utc).isoformat()
                                }
                            )
                    else:
                        response_data["whatsapp_error"] = whatsapp_result.get("error", "Unknown error")
                        
                except Exception as wa_error:
                    print(f"WhatsApp error: {wa_error}")
                    response_data["whatsapp_error"] = str(wa_error)
            else:
                response_data["whatsapp_error"] = "Patient phone number not available"
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error sending remote prescription: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send remote prescription: {str(e)}"
        )

# NOTE: ResendPrescriptionRequest and resend-whatsapp endpoint moved earlier in the file
# See POST /handwritten-notes/{note_id}/resend-whatsapp around line 6101

@app.get("/visits/{visit_id}/handwriting-interface", response_class=HTMLResponse)
async def show_handwriting_interface(visit_id: int):
    """Display the handwriting interface for completing visit notes"""
    try:
        # Read the HTML template
        html_file_path = Path(__file__).parent / "handwriting_interface.html"
        with open(html_file_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        # Replace the visit ID in the HTML if needed
        html_content = html_content.replace("{{visit_id}}", str(visit_id))
        
        return HTMLResponse(content=html_content)
        
    except FileNotFoundError:
        return HTMLResponse(
            content="""
            <html>
                <body>
                    <h1>Error</h1>
                    <p>Handwriting interface template not found.</p>
                </body>
            </html>
            """,
            status_code=404
        )
    except Exception as e:
        print(f"Error serving handwriting interface: {e}")
        return HTMLResponse(
            content=f"""
            <html>
                <body>
                    <h1>Error</h1>
                    <p>Failed to load handwriting interface: {str(e)}</p>
                </body>
            </html>
            """,
            status_code=500
        )

# Report Management Routes
@app.post("/visits/{visit_id}/generate-report-link", response_model=dict)
async def generate_report_upload_link(
    visit_id: int,
    link_data: ReportLinkCreate,
    current_doctor = Depends(get_current_doctor)
):
    """Generate a secure upload link for patients to upload reports"""
    try:
        # Verify the visit exists and belongs to the current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get patient information
        patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Generate secure upload token
        upload_token = secrets.token_urlsafe(32)
        
        # Calculate expiration time
        expires_at = datetime.now(timezone.utc) + timedelta(hours=link_data.expires_in_hours)
        
        # Prepare link data
        link_record = {
            "visit_id": visit_id,
            "patient_id": visit["patient_id"],
            "doctor_firebase_uid": current_doctor["firebase_uid"],
            "upload_token": upload_token,
            "expires_at": expires_at.isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Create the upload link record
        created_link = await db.create_report_upload_link(link_record)
        if not created_link:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create upload link"
            )
        
        # Generate the full upload URL (use env var or default localhost)
        base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")
        upload_url = f"{base_url.rstrip('/')}/upload-reports/{upload_token}"
        
        return {
            "message": "Report upload link generated successfully",
            "upload_url": upload_url,
            "upload_token": upload_token,
            "patient_name": f"{patient['first_name']} {patient['last_name']}",
            "doctor_name": f"{current_doctor['first_name']} {current_doctor['last_name']}",
            "tests_recommended": visit.get("tests_recommended", "General reports"),
            "expires_at": expires_at.isoformat(),
            "expires_in_hours": link_data.expires_in_hours
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generating report upload link: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate upload link"
        )

@app.post("/visits/{visit_id}/send-whatsapp-report-link", response_model=dict)
async def send_whatsapp_report_link(
    visit_id: int,
    request_data: WhatsAppReportRequest,
    current_doctor = Depends(get_current_doctor)
):
    """Generate upload link and send it via WhatsApp to the patient"""
    try:
        # Verify the visit exists and belongs to the current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get patient information
        patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Check if patient has a phone number
        if not patient.get("phone"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient phone number not found. Please update patient profile with phone number."
            )
        
        # Check if tests are recommended in the visit
        tests_recommended = visit.get("tests_recommended")
        if not tests_recommended:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No tests recommended in this visit. Please update the visit with recommended tests."
            )
        
        # Generate secure upload token
        upload_token = secrets.token_urlsafe(32)
        
        # Calculate expiration time
        expires_at = datetime.now(timezone.utc) + timedelta(hours=request_data.expires_in_hours)
        
        # Prepare link data
        link_record = {
            "visit_id": visit_id,
            "patient_id": visit["patient_id"],
            "doctor_firebase_uid": current_doctor["firebase_uid"],
            "upload_token": upload_token,
            "expires_at": expires_at.isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Create the upload link record
        created_link = await db.create_report_upload_link(link_record)
        if not created_link:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create upload link"
            )
        
        # Generate the full upload URL
        base_url = os.getenv("PUBLIC_BASE_URL", "")
        upload_url = f"{base_url.rstrip('/')}/upload-reports/{upload_token}"
        
        # Prepare response data
        response_data = {
            "message": "Report upload link generated successfully",
            "upload_url": upload_url,
            "upload_token": upload_token,
            "patient_name": f"{patient['first_name']} {patient['last_name']}",
            "patient_phone": patient["phone"],
            "doctor_name": f"Dr. {current_doctor['first_name']} {current_doctor['last_name']}",
            "tests_recommended": tests_recommended,
            "expires_at": expires_at.isoformat(),
            "expires_in_hours": request_data.expires_in_hours,
            "whatsapp_sent": False,
            "whatsapp_error": None
        }
        
        # Send WhatsApp message if requested
        if request_data.send_whatsapp:
            try:
                whatsapp_result = await whatsapp_service.send_report_upload_link(
                    patient_name=f"{patient['first_name']} {patient['last_name']}",
                    doctor_name=f"Dr. {current_doctor['first_name']} {current_doctor['last_name']}",
                    phone_number=patient["phone"],
                    upload_url=upload_url,
                    tests_recommended=tests_recommended,
                    expires_at=expires_at.isoformat()
                )
                
                if whatsapp_result["success"]:
                    response_data["whatsapp_sent"] = True
                    response_data["whatsapp_message_id"] = whatsapp_result.get("message_id")
                    response_data["message"] = "Report upload link generated and sent via WhatsApp successfully"
                else:
                    response_data["whatsapp_error"] = whatsapp_result.get("error")
                    response_data["message"] = "Report upload link generated but WhatsApp sending failed"
                    
            except Exception as whatsapp_error:
                print(f"WhatsApp sending error: {whatsapp_error}")
                response_data["whatsapp_error"] = str(whatsapp_error)
                response_data["message"] = "Report upload link generated but WhatsApp sending failed"
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generating and sending report upload link: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate and send upload link"
        )

@app.get("/upload-reports/{upload_token}", response_class=HTMLResponse)
async def show_upload_page(upload_token: str):
    """Display the report upload page for patients"""
    try:
        # Verify the upload token exists and is not expired
        link_data = await db.get_report_upload_link(upload_token)
        if not link_data:
            return HTMLResponse(
                content="""
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Invalid Link</title>
                    <style>
                        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
                        .error-container { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 20px 40px rgba(0,0,0,0.1); text-align: center; max-width: 500px; }
                        .error-icon { font-size: 64px; margin-bottom: 20px; }
                        h1 { color: #e74c3c; margin-bottom: 10px; }
                        p { color: #666; font-size: 16px; }
                    </style>
                </head>
                <body>
                    <div class="error-container">
                        <div class="error-icon">❌</div>
                        <h1>Invalid or Expired Link</h1>
                        <p>This upload link is not valid or has expired. Please contact your doctor for a new link.</p>
                    </div>
                </body>
                </html>
                """,
                status_code=404
            )
        
        # Check if link has expired
        expires_at = datetime.fromisoformat(link_data["expires_at"].replace('Z', '+00:00'))
        if datetime.now(timezone.utc) > expires_at:
            return HTMLResponse(
                content="""
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Expired Link</title>
                    <style>
                        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
                        .error-container { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 20px 40px rgba(0,0,0,0.1); text-align: center; max-width: 500px; }
                        .error-icon { font-size: 64px; margin-bottom: 20px; }
                        h1 { color: #f39c12; margin-bottom: 10px; }
                        p { color: #666; font-size: 16px; }
                    </style>
                </head>
                <body>
                    <div class="error-container">
                        <div class="error-icon">⏰</div>
                        <h1>Expired Link</h1>
                        <p>This upload link has expired. Please contact your doctor for a new link.</p>
                    </div>
                </body>
                </html>
                """,
                status_code=410
            )
        
        # Get visit and patient information for display
        visit = await db.get_visit_by_id(link_data["visit_id"], link_data["doctor_firebase_uid"])
        patient = await db.get_patient_by_id(link_data["patient_id"], link_data["doctor_firebase_uid"])
        doctor = await db.get_doctor_by_firebase_uid(link_data["doctor_firebase_uid"])
        
        # Parse tests recommended into individual tests
        tests_recommended = visit.get('tests_recommended', 'General reports')
        individual_tests = []
        
        if tests_recommended and tests_recommended.strip():
            # Split by common delimiters and clean up
            test_list = []
            for delimiter in [',', ';', '&', ' and ', '\n']:
                if delimiter in tests_recommended:
                    test_list = [test.strip() for test in tests_recommended.split(delimiter)]
                    break
            
            # If no delimiters found, treat as single test
            if not test_list:
                test_list = [tests_recommended.strip()]
            
            # Clean and filter tests
            for test in test_list:
                test = test.strip()
                if test and len(test) > 0:
                    individual_tests.append(test)
        
        # If no tests found, add a general category
        if not individual_tests:
            individual_tests = ["General Medical Reports"]
        
        # Generate HTML page with modern design
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Upload Medical Reports - {patient['first_name']} {patient['last_name']}</title>
            <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
            <style>
                :root {{
                    --primary-color: #667eea;
                    --primary-dark: #5a6fd8;
                    --secondary-color: #764ba2;
                    --success-color: #27ae60;
                    --danger-color: #e74c3c;
                    --warning-color: #f39c12;
                    --info-color: #3498db;
                    --light-bg: #f8f9fa;
                    --white: #ffffff;
                    --text-dark: #2c3e50;
                    --text-muted: #7f8c8d;
                    --border-color: #e9ecef;
                    --shadow: 0 10px 30px rgba(0,0,0,0.1);
                    --border-radius: 12px;
                    --transition: all 0.3s ease;
                }}

                * {{
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }}

                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: var(--text-dark);
                    background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
                    min-height: 100vh;
                    padding: 20px;
                }}

                .container {{
                    max-width: 1000px;
                    margin: 0 auto;
                    background: var(--white);
                    border-radius: 20px;
                    box-shadow: var(--shadow);
                    overflow: hidden;
                    animation: slideUp 0.6s ease-out;
                }}

                @keyframes slideUp {{
                    from {{
                        opacity: 0;
                        transform: translateY(30px);
                    }}
                    to {{
                        opacity: 1;
                        transform: translateY(0);
                    }}
                }}

                .header {{
                    background: linear-gradient(135deg, var(--primary-color), var(--primary-dark));
                    color: var(--white);
                    padding: 40px;
                    text-align: center;
                    position: relative;
                    overflow: hidden;
                }}

                .header::before {{
                    content: '';
                    position: absolute;
                    top: -50%;
                    left: -50%;
                    width: 200%;
                    height: 200%;
                    background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 70%);
                    animation: float 6s ease-in-out infinite;
                }}

                @keyframes float {{
                    0%, 100% {{ transform: translate(-50%, -50%) rotate(0deg); }}
                    50% {{ transform: translate(-50%, -50%) rotate(180deg); }}
                }}

                .header-icon {{
                    font-size: 48px;
                    margin-bottom: 20px;
                    position: relative;
                    z-index: 1;
                }}

                .header h1 {{
                    font-size: 32px;
                    font-weight: 700;
                    margin-bottom: 10px;
                    position: relative;
                    z-index: 1;
                }}

                .header p {{
                    font-size: 18px;
                    opacity: 0.9;
                    position: relative;
                    z-index: 1;
                }}

                .content {{
                    padding: 40px;
                }}

                .info-card {{
                    background: linear-gradient(145deg, #f8f9fa, #e9ecef);
                    border-radius: var(--border-radius);
                    padding: 30px;
                    margin-bottom: 30px;
                    border-left: 5px solid var(--info-color);
                }}

                .info-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 20px;
                    margin-top: 20px;
                }}

                .info-item {{
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }}

                .info-icon {{
                    color: var(--info-color);
                    font-size: 20px;
                    width: 24px;
                }}

                .info-label {{
                    font-weight: 600;
                    color: var(--text-dark);
                    min-width: 100px;
                }}

                .info-value {{
                    color: var(--text-muted);
                }}

                .upload-section {{
                    margin-top: 40px;
                }}

                .section-title {{
                    font-size: 24px;
                    font-weight: 700;
                    color: var(--text-dark);
                    margin-bottom: 30px;
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }}

                .test-card {{
                    background: var(--white);
                    border: 2px solid var(--border-color);
                    border-radius: var(--border-radius);
                    margin-bottom: 25px;
                    overflow: hidden;
                    transition: var(--transition);
                    box-shadow: 0 4px 6px rgba(0,0,0,0.05);
                }}

                .test-card:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                }}

                .test-header {{
                    background: linear-gradient(145deg, var(--light-bg), #e9ecef);
                    padding: 20px;
                    border-bottom: 1px solid var(--border-color);
                }}

                .test-title {{
                    font-size: 18px;
                    font-weight: 600;
                    color: var(--primary-color);
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }}

                .test-body {{
                    padding: 25px;
                }}

                .file-input-wrapper {{
                    position: relative;
                    margin-bottom: 20px;
                }}

                .file-input {{
                    display: none;
                }}

                .file-input-label {{
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 12px;
                    padding: 25px;
                    border: 2px dashed var(--primary-color);
                    border-radius: var(--border-radius);
                    background: rgba(102, 126, 234, 0.05);
                    cursor: pointer;
                    transition: var(--transition);
                    color: var(--primary-color);
                    font-weight: 500;
                }}

                .file-input-label:hover {{
                    background: rgba(102, 126, 234, 0.1);
                    border-color: var(--primary-dark);
                }}

                .file-input-label.has-files {{
                    border-color: var(--success-color);
                    background: rgba(39, 174, 96, 0.05);
                    color: var(--success-color);
                }}

                .selected-files {{
                    margin-top: 15px;
                    display: none;
                }}

                .selected-files.show {{
                    display: block;
                }}

                .file-item {{
                    display: flex;
                    align-items: center;
                    justify-content: between;
                    gap: 10px;
                    padding: 10px 15px;
                    background: var(--light-bg);
                    border-radius: 8px;
                    margin-bottom: 8px;
                    font-size: 14px;
                }}

                .file-name {{
                    flex: 1;
                    font-weight: 500;
                }}

                .file-size {{
                    color: var(--text-muted);
                    font-size: 12px;
                }}

                .remove-file {{
                    color: var(--danger-color);
                    cursor: pointer;
                    padding: 4px;
                    border-radius: 4px;
                    transition: var(--transition);
                }}

                .remove-file:hover {{
                    background: rgba(231, 76, 60, 0.1);
                }}

                .notes-input {{
                    width: 100%;
                    min-height: 100px;
                    padding: 15px;
                    border: 2px solid var(--border-color);
                    border-radius: var(--border-radius);
                    font-family: inherit;
                    font-size: 14px;
                    resize: vertical;
                    transition: var(--transition);
                    margin-bottom: 20px;
                }}

                .notes-input:focus {{
                    outline: none;
                    border-color: var(--primary-color);
                    box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
                }}

                .upload-btn {{
                    background: linear-gradient(145deg, var(--success-color), #229954);
                    color: var(--white);
                    border: none;
                    padding: 12px 24px;
                    border-radius: var(--border-radius);
                    font-weight: 600;
                    cursor: pointer;
                    transition: var(--transition);
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-size: 14px;
                }}

                .upload-btn:hover {{
                    transform: translateY(-1px);
                    box-shadow: 0 4px 12px rgba(39, 174, 96, 0.3);
                }}

                .upload-btn:disabled {{
                    background: var(--text-muted);
                    cursor: not-allowed;
                    transform: none;
                    box-shadow: none;
                }}

                .upload-all-btn {{
                    background: linear-gradient(145deg, var(--primary-color), var(--primary-dark));
                    color: var(--white);
                    border: none;
                    padding: 18px 36px;
                    border-radius: var(--border-radius);
                    font-size: 16px;
                    font-weight: 700;
                    cursor: pointer;
                    transition: var(--transition);
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    margin: 40px auto;
                    box-shadow: 0 6px 20px rgba(102, 126, 234, 0.3);
                }}

                .upload-all-btn:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
                }}

                .message {{
                    margin-top: 15px;
                    padding: 12px 16px;
                    border-radius: 8px;
                    font-weight: 500;
                    display: none;
                }}

                .message.show {{
                    display: block;
                    animation: fadeIn 0.3s ease-out;
                }}

                @keyframes fadeIn {{
                    from {{ opacity: 0; transform: translateY(10px); }}
                    to {{ opacity: 1; transform: translateY(0); }}
                }}

                .message.success {{
                    background: rgba(39, 174, 96, 0.1);
                    color: var(--success-color);
                    border: 1px solid rgba(39, 174, 96, 0.2);
                }}

                .message.error {{
                    background: rgba(231, 76, 60, 0.1);
                    color: var(--danger-color);
                    border: 1px solid rgba(231, 76, 60, 0.2);
                }}

                .progress-bar {{
                    width: 100%;
                    height: 8px;
                    background: var(--border-color);
                    border-radius: 4px;
                    overflow: hidden;
                    margin: 15px 0;
                    display: none;
                }}

                .progress-bar.show {{
                    display: block;
                }}

                .progress-fill {{
                    height: 100%;
                    background: linear-gradient(90deg, var(--primary-color), var(--success-color));
                    width: 0%;
                    transition: width 0.3s ease;
                    position: relative;
                }}

                .progress-fill::after {{
                    content: '';
                    position: absolute;
                    top: 0;
                    left: 0;
                    bottom: 0;
                    right: 0;
                    background: linear-gradient(
                        90deg,
                        transparent,
                        rgba(255, 255, 255, 0.6),
                        transparent
                    );
                    animation: shimmer 1.5s infinite;
                }}

                @keyframes shimmer {{
                    0% {{ transform: translateX(-100%); }}
                    100% {{ transform: translateX(100%); }}
                }}

                .uploaded-files {{
                    margin-top: 40px;
                    display: none;
                }}

                .uploaded-files.show {{
                    display: block;
                    animation: slideUp 0.5s ease-out;
                }}

                .uploaded-file-item {{
                    background: rgba(39, 174, 96, 0.05);
                    border: 1px solid rgba(39, 174, 96, 0.2);
                    border-radius: var(--border-radius);
                    padding: 15px;
                    margin-bottom: 10px;
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }}

                .file-icon {{
                    color: var(--success-color);
                    font-size: 20px;
                }}

                .important-notes {{
                    background: linear-gradient(145deg, rgba(243, 156, 18, 0.05), rgba(243, 156, 18, 0.1));
                    border: 1px solid rgba(243, 156, 18, 0.2);
                    border-radius: var(--border-radius);
                    padding: 25px;
                    margin-top: 40px;
                }}

                .important-notes h4 {{
                    color: var(--warning-color);
                    margin-bottom: 15px;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }}

                .important-notes ul {{
                    margin-left: 20px;
                }}

                .important-notes li {{
                    margin-bottom: 8px;
                    color: var(--text-dark);
                }}

                .countdown {{
                    background: linear-gradient(145deg, rgba(231, 76, 60, 0.05), rgba(231, 76, 60, 0.1));
                    border: 1px solid rgba(231, 76, 60, 0.2);
                    border-radius: var(--border-radius);
                    padding: 20px;
                    margin-bottom: 30px;
                    text-align: center;
                }}

                .countdown-timer {{
                    font-size: 24px;
                    font-weight: 700;
                    color: var(--danger-color);
                    margin-bottom: 5px;
                }}

                .countdown-label {{
                    color: var(--text-muted);
                    font-size: 14px;
                }}

                @media (max-width: 768px) {{
                    .container {{
                        margin: 10px;
                        border-radius: 15px;
                    }}
                    
                    .header {{
                        padding: 30px 20px;
                    }}
                    
                    .header h1 {{
                        font-size: 24px;
                    }}
                    
                    .content {{
                        padding: 20px;
                    }}
                    
                    .info-grid {{
                        grid-template-columns: 1fr;
                    }}
                    
                    .upload-all-btn {{
                        width: 100%;
                        justify-content: center;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="header-icon">
                        <i class="fas fa-file-medical"></i>
                    </div>
                    <h1>Medical Report Upload</h1>
                    <p>Secure portal for uploading your medical test results</p>
                </div>
                
                <div class="content">
                    <!-- Countdown Timer -->
                    <div class="countdown">
                        <div class="countdown-timer" id="countdown">
                            <i class="fas fa-clock"></i> Calculating...
                        </div>
                        <div class="countdown-label">Time remaining to upload</div>
                    </div>

                    <!-- Patient Information -->
                    <div class="info-card">
                        <h3 style="color: var(--info-color); margin-bottom: 20px; display: flex; align-items: center; gap: 10px;">
                            <i class="fas fa-info-circle"></i> Visit Information
                        </h3>
                        <div class="info-grid">
                            <div class="info-item">
                                <i class="fas fa-user info-icon"></i>
                                <span class="info-label">Patient:</span>
                                <span class="info-value">{patient['first_name']} {patient['last_name']}</span>
                            </div>
                            <div class="info-item">
                                <i class="fas fa-user-md info-icon"></i>
                                <span class="info-label">Doctor:</span>
                                <span class="info-value">Dr. {doctor['first_name']} {doctor['last_name']}</span>
                            </div>
                            <div class="info-item">
                                <i class="fas fa-calendar info-icon"></i>
                                <span class="info-label">Visit Date:</span>
                                <span class="info-value">{visit['visit_date']}</span>
                            </div>
                            <div class="info-item">
                                <i class="fas fa-stethoscope info-icon"></i>
                                <span class="info-label">Tests Required:</span>
                                <span class="info-value">{visit.get('tests_recommended', 'General reports')}</span>
                            </div>
                        </div>
                    </div>

                    <!-- Upload Section -->
                    <div class="upload-section">
                        <h2 class="section-title">
                            <i class="fas fa-cloud-upload-alt"></i>
                            Upload Your Test Reports
                        </h2>
                        
                        <div id="uploadSections">"""

        # Generate upload sections for each test
        for i, test in enumerate(individual_tests):
            html_content += f"""
                            <div class="test-card">
                                <div class="test-header">
                                    <div class="test-title">
                                        <i class="fas fa-clipboard-list"></i>
                                        {test}
                                    </div>
                                </div>
                                <div class="test-body">
                                    <form class="uploadForm" data-test-type="{test}" enctype="multipart/form-data">
                                        <div class="file-input-wrapper">
                                            <input type="file" class="file-input" id="fileInput{i}" multiple accept=".pdf,.jpg,.jpeg,.png,.doc,.docx">
                                            <label for="fileInput{i}" class="file-input-label">
                                                <i class="fas fa-plus-circle"></i>
                                                <span>Choose files for {test}</span>
                                                <small style="opacity: 0.7;">(PDF, Images, Word docs)</small>
                                            </label>
                                            <div class="selected-files" id="selectedFiles{i}"></div>
                                        </div>
                                        
                                        <textarea class="notes-input" placeholder="Add any notes about these {test} reports (optional)..."></textarea>
                                        
                                        <button type="submit" class="upload-btn" disabled>
                                            <i class="fas fa-upload"></i>
                                            Upload {test} Reports
                                        </button>
                                        
                                        <div class="progress-bar">
                                            <div class="progress-fill"></div>
                                        </div>
                                        
                                        <div class="message"></div>
                                    </form>
                                </div>
                            </div>"""

        html_content += f"""
                        </div>
                        
                        <button type="button" class="upload-all-btn" id="uploadAllBtn" disabled>
                            <i class="fas fa-rocket"></i>
                            Upload All Selected Files
                        </button>
                    </div>
                    
                    <!-- Uploaded Files Display -->
                    <div class="uploaded-files" id="uploadedFiles">
                        <h3 style="color: var(--success-color); margin-bottom: 20px; display: flex; align-items: center; gap: 10px;">
                            <i class="fas fa-check-circle"></i> Successfully Uploaded Files
                        </h3>
                        <div id="fileListContainer"></div>
                    </div>
                    
                    <!-- Important Notes -->
                    <div class="important-notes">
                        <h4>
                            <i class="fas fa-exclamation-triangle"></i>
                            Important Guidelines
                        </h4>
                        <ul>
                            <li><strong>File Types:</strong> PDF, Images (JPG, PNG), Word documents (.doc, .docx)</li>
                            <li><strong>File Size:</strong> Maximum 10MB per file</li>
                            <li><strong>Security:</strong> All files are encrypted and only accessible to your doctor</li>
                            <li><strong>Expiration:</strong> This link expires on {expires_at.strftime('%B %d, %Y at %I:%M %p UTC')}</li>
                            <li><strong>Support:</strong> Contact your doctor if you experience any issues</li>
                        </ul>
                    </div>
                </div>
            </div>
            
            <script>
                // Countdown timer
                function updateCountdown() {{
                    const expireTime = new Date('{expires_at.isoformat()}').getTime();
                    const now = new Date().getTime();
                    const distance = expireTime - now;
                    
                    if (distance < 0) {{
                        document.getElementById('countdown').innerHTML = '<i class="fas fa-exclamation-triangle"></i> EXPIRED';
                        return;
                    }}
                    
                    const days = Math.floor(distance / (1000 * 60 * 60 * 24));
                    const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
                    const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
                    const seconds = Math.floor((distance % (1000 * 60)) / 1000);
                    
                    let countdown = '';
                    if (days > 0) countdown += days + 'd ';
                    countdown += hours.toString().padStart(2, '0') + ':' + 
                               minutes.toString().padStart(2, '0') + ':' + 
                               seconds.toString().padStart(2, '0');
                    
                    document.getElementById('countdown').innerHTML = '<i class="fas fa-clock"></i> ' + countdown;
                }}
                
                updateCountdown();
                setInterval(updateCountdown, 1000);
                
                // File input handling
                document.querySelectorAll('.file-input').forEach((input, index) => {{
                    input.addEventListener('change', function() {{
                        const label = this.nextElementSibling;
                        const selectedFiles = document.getElementById('selectedFiles' + index);
                        const uploadBtn = this.closest('.uploadForm').querySelector('.upload-btn');
                        
                        if (this.files.length > 0) {{
                            label.classList.add('has-files');
                            label.innerHTML = `
                                <i class="fas fa-check-circle"></i>
                                <span>${{this.files.length}} file(s) selected</span>
                                <small style="opacity: 0.7;">Click to change</small>
                            `;
                            
                            // Show selected files
                            selectedFiles.innerHTML = '';
                            Array.from(this.files).forEach((file, fileIndex) => {{
                                const fileItem = document.createElement('div');
                                fileItem.className = 'file-item';
                                fileItem.innerHTML = `
                                    <i class="fas fa-file file-icon"></i>
                                    <span class="file-name">${{file.name}}</span>
                                    <span class="file-size">${{(file.size / 1024 / 1024).toFixed(2)}} MB</span>
                                    <i class="fas fa-times remove-file" onclick="removeFile(this, ${{index}}, ${{fileIndex}})"></i>
                                `;
                                selectedFiles.appendChild(fileItem);
                            }});
                            selectedFiles.classList.add('show');
                            uploadBtn.disabled = false;
                        }} else {{
                            label.classList.remove('has-files');
                            label.innerHTML = `
                                <i class="fas fa-plus-circle"></i>
                                <span>Choose files for ${{this.closest('.uploadForm').dataset.testType}}</span>
                                <small style="opacity: 0.7;">(PDF, Images, Word docs)</small>
                            `;
                            selectedFiles.classList.remove('show');
                            uploadBtn.disabled = true;
                        }}
                        
                        updateUploadAllButton();
                    }});
                }});
                
                function removeFile(element, inputIndex, fileIndex) {{
                    const input = document.getElementById('fileInput' + inputIndex);
                    const dt = new DataTransfer();
                    
                    Array.from(input.files).forEach((file, index) => {{
                        if (index !== fileIndex) {{
                            dt.items.add(file);
                        }}
                    }});
                    
                    input.files = dt.files;
                    input.dispatchEvent(new Event('change'));
                }}
                
                function updateUploadAllButton() {{
                    const uploadAllBtn = document.getElementById('uploadAllBtn');
                    const hasFiles = Array.from(document.querySelectorAll('.file-input')).some(input => input.files.length > 0);
                    uploadAllBtn.disabled = !hasFiles;
                }}
                
                // Form submission handling
                document.querySelectorAll('.uploadForm').forEach(form => {{
                    form.addEventListener('submit', async function(e) {{
                        e.preventDefault();
                        await uploadFiles(this);
                    }});
                }});
                
                document.getElementById('uploadAllBtn').addEventListener('click', async function() {{
                    const forms = document.querySelectorAll('.uploadForm');
                    
                    for (const form of forms) {{
                        const fileInput = form.querySelector('.file-input');
                        if (fileInput.files.length > 0) {{
                            await uploadFiles(form);
                        }}
                    }}
                }});
                
                async function uploadFiles(form) {{
                    const fileInput = form.querySelector('.file-input');
                    const notes = form.querySelector('.notes-input').value;
                    const testType = form.dataset.testType;
                    const messageDiv = form.querySelector('.message');
                    const progressBar = form.querySelector('.progress-bar');
                    const progressFill = form.querySelector('.progress-fill');
                    const uploadBtn = form.querySelector('.upload-btn');
                    
                    if (!fileInput.files.length) {{
                        showMessage(messageDiv, 'Please select at least one file for ' + testType, 'error');
                        return;
                                       }}
                    
                    // Show progress
                    progressBar.classList.add('show');
                    uploadBtn.disabled = true;
                    uploadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uploading...';
                    
                    const formData = new FormData();
                    for (let file of fileInput.files) {{
                        formData.append('files', file);
                    }}
                    formData.append('notes', notes);
                    formData.append('test_type', testType);
                    formData.append('upload_token', '{upload_token}');
                    
                    try {{
                        const response = await fetch('/api/upload-reports', {{
                            method: 'POST',
                            body: formData
                        }});
                        
                        const result = await response.json();
                        
                        if (response.ok) {{
                            progressFill.style.width = '100%';
                            showMessage(messageDiv, '✅ ' + testType + ' files uploaded successfully!', 'success');
                            
                            // Show uploaded files
                            const uploadedDiv = document.getElementById('uploadedFiles');
                            const fileListContainer = document.getElementById('fileListContainer');
                            
                            if (result.uploaded_files) {{
                                result.uploaded_files.forEach(file => {{
                                    const fileItem = document.createElement('div');
                                    fileItem.className = 'uploaded-file-item';
                                    fileItem.innerHTML = `
                                        <i class="fas fa-file-check file-icon"></i>
                                        <div>
                                            <div class="file-name">${{file.file_name}}</div>
                                            <small style="color: var(--text-muted);">${{file.test_type}} • ${{(file.file_size / 1024 / 1024).toFixed(2)}} MB</small>
                                        </div>
                                    `;
                                    fileListContainer.appendChild(fileItem);
                                }});
                                uploadedDiv.classList.add('show');
                            }}
                            
                           
                            // Reset form
                            form.reset();
                            fileInput.dispatchEvent(new Event('change'));
                        }} else {{
                            showMessage(messageDiv, '❌ Error uploading ' + testType + ': ' + (result.detail || 'Unknown error'), 'error');
                        }}
                    }} catch (error) {{
                        showMessage(messageDiv, '❌ Upload failed for ' + testType + '. Please try again.', 'error');
                        console.error('Upload error:', error);
                    }} finally {{
                        progressBar.classList.remove('show');
                        progressFill.style.width = '0%';
                        uploadBtn.disabled = false;
                        uploadBtn.innerHTML = '<i class="fas fa-upload"></i> Upload ' + testType + ' Reports';
                        updateUploadAllButton();
                    }}
                }}
                
                function showMessage(messageDiv, text, type) {{
                    messageDiv.className = 'message show ' + type;
                    messageDiv.textContent = text;
                    setTimeout(() => {{
                        messageDiv.classList.remove('show');
                    }}, 5000);
                }}
            </script>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        print(f"Error showing upload page: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Error</title>
                <style>
                    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
                    .error-container { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 20px 40px rgba(0,0,0,0.1); text-align: center; max-width: 500px; }
                    .error-icon { font-size: 64px; margin-bottom: 20px; }
                    h1 { color: #e74c3c; margin-bottom: 10px; }
                    p { color: #666; font-size: 16px; }
                </style>
            </head>
            <body>
                <div class="error-container">
                    <div class="error-icon">⚠️</div>
                    <h1>Something went wrong</h1>
                    <p>An error occurred while loading the upload page. Please contact your doctor for assistance.</p>
                </div>
            </body>
            </html>
            """,
            status_code=500
        )

@app.post("/api/upload-reports", response_model=dict)
async def upload_reports(request: Request):
    """Handle report file uploads from patients"""
    try:
        # Parse multipart form data
        form = await request.form()
        upload_token = form.get("upload_token")
        notes = form.get("notes", "")
        test_type = form.get("test_type", "General Report")
        files = form.getlist("files")
        
        if not upload_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Upload token is required"
            )
        
        if not files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No files provided"
            )
        
        # Verify the upload token
        link_data = await db.get_report_upload_link(upload_token)
        if not link_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid upload token"
            )
        
        # Check if link has expired
        expires_at = datetime.fromisoformat(link_data["expires_at"].replace('Z', '+00:00'))
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Upload link has expired"
            )
        
        uploaded_files = []
        
        # Reuse the global service-role supabase client created at startup
        # service_supabase = create_client(SUPABASE_URL, os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
        loop = asyncio.get_event_loop()
        
        for file in files:
            if hasattr(file, 'filename') and file.filename:
                # Read file content
                file_content = await file.read()
                file_size = len(file_content)
                
                # Validate file size (10MB limit)
                if file_size > 10 * 1024 * 1024:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File {file.filename} is too large. Maximum size is 10MB."
                    )
                
                # Generate unique filename
                file_extension = file.filename.split('.')[-1] if '.' in file.filename else ''
                unique_filename = f"{uuid.uuid4()}.{file_extension}" if file_extension else str(uuid.uuid4())
                
                # Upload file to Supabase Storage using service role
                try:
                    bucket_path = f"reports/visit_{link_data['visit_id']}/{unique_filename}"
                    
                    # Use async storage methods directly
                    await supabase.storage.from_("medical-reports").upload(
                        path=bucket_path,
                        file=file_content,
                        file_options={
                            "content-type": file.content_type or "application/octet-stream",
                            "x-upsert": "false"
                        }
                    )
                    
                    file_url = await supabase.storage.from_("medical-reports").get_public_url(bucket_path)
                    
                    print(f"File uploaded to Supabase Storage: {file.filename} -> {bucket_path}")
                except Exception as storage_error:
                    print(f"Error uploading to Supabase Storage: {storage_error}")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to upload file to storage: {str(storage_error)}"
                    )
                
                # Create report record using regular client
                report_data = {
                    "visit_id": link_data["visit_id"],
                    "patient_id": link_data["patient_id"],
                    "doctor_firebase_uid": link_data["doctor_firebase_uid"],
                    "file_name": file.filename,
                    "file_size": file_size,
                    "file_type": file.content_type or "application/octet-stream",
                    "file_url": file_url,
                    "storage_path": bucket_path,
                    "test_type": test_type,
                    "notes": notes,
                    "upload_token": upload_token,
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "created_at": datetime.now(timezone.utc).isoformat()
                };
                
                created_report = await db.create_report(report_data)
                if created_report:
                    uploaded_files.append({
                        "file_name": file.filename,
                        "file_size": file_size,
                        "file_type": file.content_type or "application/octet-stream",
                        "file_url": file_url,
                        "storage_path": bucket_path,
                        "test_type": test_type,
                        "report_id": created_report["id"]
                    })
                    print(f"Report record created in database for: {file.filename}")
                    
                    # Automatically queue AI analysis for the uploaded report
                    try:
                        queue_data = {
                            "report_id": created_report["id"],
                            "visit_id": link_data["visit_id"],
                            "patient_id": link_data["patient_id"],
                            "doctor_firebase_uid": link_data["doctor_firebase_uid"],
                            "priority": 1,  # Normal priority
                            "status": "pending",
                            "queued_at": datetime.now(timezone.utc).isoformat()
                        }
                        
                        queued_analysis = await db.queue_ai_analysis(queue_data)
                        if queued_analysis:
                            print(f"AI analysis queued for report: {file.filename}")
                        else:
                            print(f"Failed to queue AI analysis for: {file.filename}")
                    except Exception as ai_queue_error:
                        print(f"Error queuing AI analysis for {file.filename}: {ai_queue_error}")
                        # Don't fail the upload if AI queuing fails
                    
                    # Create notification for the doctor about the new report upload
                    try:
                        # Get patient information for the notification
                        patient_info = await db.get_patient_by_id(link_data["patient_id"])
                        patient_name = f"{patient_info.get('first_name', 'Unknown')} {patient_info.get('last_name', 'Patient')}" if patient_info else "Unknown Patient"
                        
                        notification_data = {
                            "doctor_firebase_uid": link_data["doctor_firebase_uid"],
                            "title": "New Report Uploaded",
                            "message": f"{patient_name} has uploaded a new {test_type} report: {file.filename}",
                            "notification_type": "report_upload",
                            "priority": 1,  # Normal priority
                            "is_read": False,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "metadata": {
                                "report_id": created_report["id"],
                                "visit_id": link_data["visit_id"],
                                "patient_id": link_data["patient_id"],
                                "patient_name": patient_name,
                                "file_name": file.filename,
                                "file_size": file_size,
                                "test_type": test_type,
                                "upload_token": upload_token
                            }
                        }
                        
                        created_notification = await db.create_notification(notification_data)
                        if created_notification:
                            print(f"Notification created for doctor about report: {file.filename}")
                        else:
                            print(f"Failed to create notification for report: {file.filename}")
                    except Exception as notification_error:
                        print(f"Error creating notification for {file.filename}: {notification_error}")
                        # Don't fail the upload if notification creation fails
                        
                else:
                    # If database insert failed, clean up the file from storage
                    try:
                        await supabase.storage.from_("medical-reports").remove([bucket_path])
                        print(f"Cleaned up storage file after database failure: {bucket_path}")
                    except Exception as cleanup_error:
                        print(f"Failed to cleanup storage file: {cleanup_error}")
                    print(f"Failed to create report record for: {file.filename}")
        
        if not uploaded_files:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload any files"
            )
        
        # Clean up outdated patient history analyses since we added new reports
        await db.cleanup_outdated_patient_history_analyses(link_data["patient_id"], link_data["doctor_firebase_uid"])
        
        return {
            "message": f"Successfully uploaded {len(uploaded_files)} file(s)",
            "uploaded_files": uploaded_files,
            "upload_count": len(uploaded_files)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error uploading reports: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload reports"
        )

@app.get("/visits/{visit_id}/reports", response_model=list[dict])
async def get_visit_reports(visit_id: int, current_doctor = Depends(get_current_doctor)):
    """Get all reports for a specific visit"""
    try:
        # Verify the visit exists and belongs to the current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get reports for this visit
        reports = await db.get_reports_by_visit_id(visit_id, current_doctor["firebase_uid"])
        
        # Create safe report data for response
        safe_reports = []
        for report in reports:
            safe_report = {
                "id": report.get("id"),
                "visit_id": report.get("visit_id"),
                "patient_id": report.get("patient_id"),
                "doctor_firebase_uid": report.get("doctor_firebase_uid"),
                "file_name": report.get("file_name", ""),
                "file_url": report.get("file_url", ""),
                "file_type": report.get("file_type", ""),
                "file_size": report.get("file_size", 0),
                "storage_path": report.get("storage_path", ""),
                "test_type": report.get("test_type", ""),
                "notes": report.get("notes", ""),
                "uploaded_at": report.get("uploaded_at", ""),
                "created_at": report.get("created_at", "")
            }
            safe_reports.append(safe_report)
        
        return safe_reports
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching visit reports: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch reports"
        )

@app.get("/visits/{visit_id}/reports/grouped", response_model=dict)
async def get_visit_reports_grouped_by_test(visit_id: int, current_doctor = Depends(get_current_doctor)):
    """Get all reports for a specific visit grouped by test type"""
    try:
        # Verify the visit exists and belongs to the current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get reports for this visit
        reports = await db.get_reports_by_visit_id(visit_id, current_doctor["firebase_uid"])
        
        # Group reports by test type
        grouped_reports = {}
        for report in reports:
            test_type = report.get("test_type", "General Report")
            if not test_type or test_type.strip() == "":
                test_type = "General Report"
            
            if test_type not in grouped_reports:
                grouped_reports[test_type] = []
            
            # Create safe report data without using Pydantic model to avoid validation errors
            safe_report = {
                "id": report.get("id"),
                "visit_id": report.get("visit_id"),
                "patient_id": report.get("patient_id"),
                "doctor_firebase_uid": report.get("doctor_firebase_uid"),
                "file_name": report.get("file_name", ""),
                "file_url": report.get("file_url", ""),
                "file_type": report.get("file_type", ""),
                "file_size": report.get("file_size", 0),
                "storage_path": report.get("storage_path", ""),
                "test_type": test_type,
                "notes": report.get("notes", ""),
                "uploaded_at": report.get("uploaded_at", ""),
                "created_at": report.get("created_at", "")
            }
            
            grouped_reports[test_type].append(safe_report)
        
        return {
            "visit_id": visit_id,
            "total_reports": len(reports),
            "test_types": list(grouped_reports.keys()),
            "reports_by_test": grouped_reports
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching grouped visit reports: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch grouped reports"
        )


@app.get("/patients/{patient_id}/reports", response_model=list[dict])
async def get_patient_reports(patient_id: int, current_doctor = Depends(get_current_doctor)):
    """Get all reports for a specific patient"""
    try:
        # Verify the patient exists and belongs to the current doctor
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Get reports for this patient
        reports = await db.get_reports_by_patient_id(patient_id, current_doctor["firebase_uid"])
        
        # Create safe report data for response
        safe_reports = []
        for report in reports:
            safe_report = {
                "id": report.get("id"),
                "visit_id": report.get("visit_id"),
                "patient_id": report.get("patient_id"),
                "doctor_firebase_uid": report.get("doctor_firebase_uid"),
                "file_name": report.get("file_name", ""),
                "file_url": report.get("file_url", ""),
                "file_type": report.get("file_type", ""),
                "file_size": report.get("file_size", 0),
                "storage_path": report.get("storage_path", ""),
                "test_type": report.get("test_type", ""),
                "notes": report.get("notes", ""),
                "uploaded_at": report.get("uploaded_at", ""),
                "created_at": report.get("created_at", "")
            }
            safe_reports.append(safe_report)
        
        return safe_reports
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching patient reports: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch patient reports"
        )

@app.get("/patients/{patient_id}/reports/grouped", response_model=dict)
async def get_patient_reports_grouped_by_test(patient_id: int, current_doctor = Depends(get_current_doctor)):
    """Get all reports for a specific patient grouped by test type and visit"""
    try:
        # Verify the patient exists and belongs to the current doctor
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Get reports for this patient
        reports = await db.get_reports_by_patient_id(patient_id, current_doctor["firebase_uid"])
        
        # Group reports by visit and then by test type
        grouped_reports = {}
        for report in reports:
            visit_id = report["visit_id"]
            test_type = report.get("test_type", "General Report")
            if not test_type or test_type.strip() == "":
                test_type = "General Report"
            
            if visit_id not in grouped_reports:
                grouped_reports[visit_id] = {}
            
            if test_type not in grouped_reports[visit_id]:
                grouped_reports[visit_id][test_type] = []
            
            # Create safe report data
            safe_report = {
                "id": report.get("id"),
                "visit_id": report.get("visit_id"),
                "patient_id": report.get("patient_id"),
                "doctor_firebase_uid": report.get("doctor_firebase_uid"),
                "file_name": report.get("file_name", ""),
                "file_url": report.get("file_url", ""),
                "file_type": report.get("file_type", ""),
                "file_size": report.get("file_size", 0),
                "storage_path": report.get("storage_path", ""),
                "test_type": test_type,
                "notes": report.get("notes", ""),
                "uploaded_at": report.get("uploaded_at", ""),
                "created_at": report.get("created_at", "")
            }
            
            grouped_reports[visit_id][test_type].append(safe_report)
        
        return {
            "patient_id": patient_id,
            "patient_name": f"{patient['first_name']} {patient['last_name']}",
            "total_reports": len(reports),
            "visits_with_reports": list(grouped_reports.keys()),
            "reports_by_visit_and_test": grouped_reports
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching grouped patient reports: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch grouped patient reports"
        )

@app.post("/test-whatsapp", response_model=dict)
async def test_whatsapp_message(
    phone_number: str,
    current_doctor = Depends(get_current_doctor)  # Add this dependency
):
    """Test WhatsApp message sending (for debugging)"""
    try:
        test_message = f"""🏥 *Test Message from Dr. {current_doctor['first_name']} {current_doctor['last_name']}*

This is a test message from your doctor's app to verify WhatsApp connectivity.

If you receive this message, the WhatsApp integration is working correctly!

Thank you."""

        result = await whatsapp_service.send_message(phone_number, test_message)
        
        if result["success"]:
            return {
                "message": "Test WhatsApp message sent successfully",
                "phone_number": result["phone_number"],
                "message_id": result.get("message_id")
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to send WhatsApp message: {result.get('error')}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error sending test WhatsApp message: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send test message"
        )

@app.get("/reports/{report_id}/download")
async def download_report(report_id: int, current_doctor = Depends(get_current_doctor)):
    """Download a specific report file from Supabase Storage"""
    try:
        # Get report details
        report = await db.get_report_by_id(report_id, current_doctor["firebase_uid"])
        if not report:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

        file_url = report.get("file_url")
        if file_url:
            # Redirect client to the file URL
            return RedirectResponse(url=file_url)

        # Fallback: serve from local filesystem if available
        file_path = report.get("storage_path")
        if file_path and os.path.exists(file_path):
            return FileResponse(
                path=file_path,
                filename=report.get("file_name", "report"),
                media_type=report.get("file_type", "application/octet-stream"),
                headers={
                    "Content-Disposition": f"inline; filename={report.get('file_name', 'report')}",
                    "Cache-Control": "no-cache",
                },
            )

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found in storage")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Download error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Download error: {str(e)}"
        )

@app.get("/visits/{visit_id}/whatsapp-status", response_model=dict)
async def get_whatsapp_status_for_visit(
    visit_id: int, 
    current_doctor = Depends(get_current_doctor)
):
    """Get WhatsApp message status for a visit"""
    try:
        # Verify the visit exists and belongs to the current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get patient information
        patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Check for existing upload links for this visit
        # This would require a new database method to get upload links by visit_id
        # For now, we'll return basic status
        
        return {
            "visit_id": visit_id,
            "patient_name": f"{patient['first_name']} {patient['last_name']}",
            "patient_phone": patient.get("phone"),
            "has_phone": bool(patient.get("phone")),
            "tests_recommended": visit.get("tests_recommended"),
            "has_tests_recommended": bool(visit.get("tests_recommended")),
            "can_send_whatsapp": bool(patient.get("phone")) and bool(visit.get("tests_recommended")),
            "whatsapp_configured": (await whatsapp_service.test_connection())["success"] and whatsapp_service.access_token and whatsapp_service.phone_number_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting WhatsApp status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get WhatsApp status"
        )

@app.post("/patients/{patient_id}/send-profile", response_model=dict)
async def send_patient_profile_pdf(
    patient_id: int,
    request_data: PatientProfileSendRequest,
    current_doctor = Depends(get_current_doctor)
):
    """Generate and send complete patient profile PDF via WhatsApp"""
    try:
        # Verify the patient exists and belongs to the current doctor
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Check if patient has a phone number
        if not patient.get("phone"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient phone number not found. Please update patient profile with phone number."
            )
        
        # Get patient visits if requested
        visits = []
        if request_data.include_visits:
            visits = await db.get_visits_by_patient_id(patient_id, current_doctor["firebase_uid"])
        
        # Get patient reports if requested
        reports = []
        if request_data.include_reports:
            reports = await db.get_reports_by_patient_id(patient_id, current_doctor["firebase_uid"])
        
        # Generate PDF
        pdf_generator = PatientProfilePDFGenerator()
        pdf_bytes = pdf_generator.generate_patient_profile_pdf(
            patient=patient,
            visits=visits,
            reports=reports,
            doctor=current_doctor
        )
        
        # Create temporary file for the PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            temp_file.write(pdf_bytes)
            temp_file_path = temp_file.name
        
        try:
            # Upload PDF to Supabase Storage
            loop = asyncio.get_event_loop()

            # Generate unique filename for storage
            pdf_filename = f"patient_profile_{patient_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            storage_path = f"patient_profiles/{current_doctor['firebase_uid']}/{pdf_filename}"

            # Upload to storage using async methods
            await supabase.storage.from_("medical-reports").upload(
                path=storage_path,
                file=pdf_bytes,
                file_options={
                    "content-type": "application/pdf",
                    "x-upsert": "true",
                },
            )

            # Try to get a public URL; fall back to signed URL
            def _extract_url(res):
                if isinstance(res, str):
                    return res
                if isinstance(res, dict):
                    # supabase-py may return {"publicUrl": str} or {"data": {"publicUrl": str}}
                    if "publicUrl" in res:
                        return res["publicUrl"]
                    data = res.get("data") if isinstance(res.get("data"), dict) else None
                    if data and "publicUrl" in data:
                        return data["publicUrl"]
                    if "signedURL" in res:
                        return res["signedURL"]
                    if data and "signedURL" in data:
                        return data["signedURL"]
                return None

            public_res = await supabase.storage.from_("medical-reports").get_public_url(storage_path)
            pdf_url = _extract_url(public_res)

            if not pdf_url:
                signed_res = await supabase.storage.from_("medical-reports").create_signed_url(storage_path, 60 * 60 * 24 * 7)
                pdf_url = _extract_url(signed_res)

            if not pdf_url:
                raise RuntimeError("Failed to obtain PDF URL from storage")

            # Prepare response data
            response_data = {
                "message": "Patient profile PDF generated successfully",
                "patient_name": f"{patient['first_name']} {patient['last_name']}",
                "patient_phone": patient["phone"],
                "doctor_name": f"Dr. {current_doctor['first_name']} {current_doctor['last_name']}",
                "pdf_url": pdf_url,
                "pdf_filename": pdf_filename,
                "includes_visits": request_data.include_visits,
                "includes_reports": request_data.include_reports,
                "visits_count": len(visits),
                "reports_count": len(reports),
                "whatsapp_sent": False,
                "whatsapp_error": None
            }
            
            # Send WhatsApp message if requested (send the link)
            if request_data.send_whatsapp:
                try:
                    msg = (
                        "🏥 Patient Profile PDF\n\n"
                        f"Patient: {patient['first_name']} {patient['last_name']}\n"
                        f"Doctor: Dr. {current_doctor['first_name']} {current_doctor['last_name']}\n\n"
                        "Download your medical profile PDF:\n"
                        f"{pdf_url}"
                    )
                    wa_result = await whatsapp_service.send_message(patient["phone"], msg)
                    response_data["whatsapp_sent"] = bool(wa_result and wa_result.get("success"))
                    if not response_data["whatsapp_sent"]:
                        response_data["whatsapp_error"] = (wa_result or {}).get("error") or "Unknown WhatsApp error"
                        response_data["message"] = "PDF generated and uploaded, WhatsApp sending failed"
                except Exception as werr:
                    response_data["whatsapp_error"] = str(werr)
                    response_data["message"] = "PDF generated and uploaded, WhatsApp sending failed"
            
            return response_data
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generating and sending patient profile PDF: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate and send patient profile PDF"
        )

@app.get("/patients/{patient_id}/download-profile")
async def download_patient_profile_pdf(
    patient_id: int,
    include_visits: bool = True,
    include_reports: bool = True,
    current_doctor = Depends(get_current_doctor)
):
    """Download patient profile PDF directly"""
    try:
        # Verify the patient exists and belongs to the current doctor
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Get patient visits if requested
        visits = []
        if include_visits:
            visits = await db.get_visits_by_patient_id(patient_id, current_doctor["firebase_uid"])
        
        # Get patient reports if requested
        reports = []
        if include_reports:
            reports = await db.get_reports_by_patient_id(patient_id, current_doctor["firebase_uid"])
        
        # Generate PDF
        pdf_generator = PatientProfilePDFGenerator()
        pdf_bytes = pdf_generator.generate_patient_profile_pdf(
            patient=patient,
            visits=visits,
            reports=reports,
            doctor=current_doctor
        )
        
        # Generate filename
        filename = f"Patient_Profile_{patient['first_name']}_{patient['last_name']}_{datetime.now().strftime('%Y%m%d')}.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "application/pdf",
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error downloading patient profile PDF: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate patient profile PDF"
        )

# Calendar Management Routes
@app.get(
    "/calendar/{year}/{month}", 
    response_model=MonthlyCalendar,
    tags=["Calendar"],
    summary="Get monthly calendar"
)
async def get_monthly_calendar(
    year: int, 
    month: int, 
    current_doctor = Depends(get_current_doctor)
):
    """Get all follow-up appointments for a specific month"""
    try:
        # Validate year and month
        if year < 2020 or year > 2030:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Year must be between 2020 and 2030"
            )
        
        if month < 1 or month > 12:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Month must be between 1 and 12"
            )
        
        # Get appointments from database
        appointments_data = await db.get_follow_up_appointments_by_month(
            current_doctor["firebase_uid"], year, month
        )
        
        # Process appointments data
        appointments = []
        appointments_by_date = {}
        
        for appointment in appointments_data:
            calendar_appointment = CalendarAppointment(
                visit_id=appointment["visit_id"],
                patient_id=appointment["patient_id"],
                patient_name=f"{appointment['patient_first_name']} {appointment['patient_last_name']}",
                follow_up_date=appointment["follow_up_date"],
                follow_up_time=appointment.get("follow_up_time"),
                original_visit_date=appointment["visit_date"],
                visit_type=appointment["visit_type"],
                chief_complaint=appointment["chief_complaint"],
                phone=appointment.get("patient_phone"),
                notes=appointment.get("notes")
            )
            
            appointments.append(calendar_appointment)
            
            # Group by date
            follow_up_date = appointment["follow_up_date"]
            if follow_up_date not in appointments_by_date:
                appointments_by_date[follow_up_date] = []
            appointments_by_date[follow_up_date].append(calendar_appointment)
        
        return MonthlyCalendar(
            year=year,
            month=month,
            doctor_name=f"Dr. {current_doctor['first_name']} {current_doctor['last_name']}",
            appointments=appointments,
            total_appointments=len(appointments),
            appointments_by_date=appointments_by_date
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting monthly calendar: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get monthly calendar"
        )

@app.get("/calendar/current", response_model=MonthlyCalendar, tags=["Calendar"])
async def get_current_month_calendar(current_doctor = Depends(get_current_doctor)):
    """Get follow-up appointments for the current month"""
    try:
        from datetime import datetime
        now = datetime.now()
        return await get_monthly_calendar(now.year, now.month, current_doctor)
        
    except Exception as e:
        print(f"Error getting current month calendar: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get current month calendar"
        )

@app.get("/calendar/summary", response_model=CalendarSummary, tags=["Calendar"])
async def get_calendar_summary(current_doctor = Depends(get_current_doctor)):
    """Get summary of upcoming appointments"""
    try:
        from datetime import datetime, date, timedelta
        
        today = date.today()
        
        # Get appointment counts
        summary_data = await db.get_follow_up_appointments_summary(current_doctor["firebase_uid"])
        
        return CalendarSummary(
            today=summary_data.get("today", 0),
            this_week=summary_data.get("this_week", 0),
            this_month=summary_data.get("this_month", 0),
            next_month=summary_data.get("next_month", 0),
            overdue=summary_data.get("overdue", 0)
        )
        
    except Exception as e:
        print(f"Error getting calendar summary: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get calendar summary"
        )

@app.get("/calendar/debug/appointments/{date}", tags=["Calendar"])
async def debug_appointments_for_date(
    date: str,
    current_doctor = Depends(get_current_doctor)
):
    """Debug endpoint to see raw appointment data"""
    try:
        doctor_firebase_uid = current_doctor.firebase_uid
        
        # Get raw data from database
        appointments_raw = await db.get_follow_up_appointments_by_date(doctor_firebase_uid, date)
        
        return {
            "date": date,
            "doctor_firebase_uid": doctor_firebase_uid,
            "raw_appointments_count": len(appointments_raw),
            "raw_appointments_data": appointments_raw,
        }
        
    except Exception as e:
        print(f"Debug endpoint error: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Debug error: {str(e)}"
        )

@app.get("/calendar/appointments/{date}", response_model=List[CalendarAppointment], tags=["Calendar"])
async def get_appointments_by_date(
    date: str,  # Format: YYYY-MM-DD
    current_doctor = Depends(get_current_doctor)
):
    """Get all follow-up appointments for a specific date"""
    try:
        # Validate date format
        from datetime import datetime
        try:
            parsed_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Date must be in YYYY-MM-DD format"
            )
        
        print(f"Getting appointments for date: {date}, doctor: {current_doctor['firebase_uid']}")
        
        # Get appointments for the date
        appointments_data = await db.get_follow_up_appointments_by_date(
            current_doctor["firebase_uid"], date
        )
        
        print(f"Raw appointments data: {appointments_data}")
        
        appointments = []
        for appointment in appointments_data:
            try:
                # Calculate if overdue and days until
                follow_up_date = datetime.strptime(appointment["follow_up_date"], "%Y-%m-%d").date()
                today = datetime.now().date()
                is_overdue = follow_up_date < today
                days_until = (follow_up_date - today).days
                
                calendar_appointment = CalendarAppointment(
                    visit_id=appointment["visit_id"],
                    patient_id=appointment["patient_id"],
                    patient_name=f"{appointment.get('patient_first_name', '')} {appointment.get('patient_last_name', '')}".strip(),
                    follow_up_date=appointment["follow_up_date"],
                    follow_up_time=appointment.get("follow_up_time"),
                    original_visit_date=appointment["visit_date"],
                    visit_type=appointment["visit_type"],
                    chief_complaint=appointment.get("chief_complaint") or "",
                    phone=appointment.get("patient_phone"),
                    notes=appointment.get("notes"),
                    is_overdue=is_overdue,
                    days_until_appointment=days_until
                )
                appointments.append(calendar_appointment)
                
            except Exception as model_error:
                print(f"Error creating CalendarAppointment model: {model_error}")
                print(f"Problematic appointment data: {appointment}")
                # Skip this appointment but continue with others
                continue
        
        print(f"Successfully created {len(appointments)} calendar appointments")
        return appointments
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting appointments by date: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get appointments for the specified date: {str(e)}"
        )

@app.get("/calendar/upcoming", response_model=List[CalendarAppointment], tags=["Calendar"])
async def get_upcoming_appointments(
    days: int = 7,  # Number of days to look ahead
    current_doctor = Depends(get_current_doctor)
):
    """Get upcoming follow-up appointments for the next N days"""
    try:
        if days < 1 or days > 365:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Days must be between 1 and 365"
            )
        
        # Get upcoming appointments
        appointments_data = await db.get_upcoming_follow_up_appointments(
            current_doctor["firebase_uid"], days
        )
        
        appointments = []
        for appointment in appointments_data:
            appointments.append(CalendarAppointment(
                visit_id=appointment["visit_id"],
                patient_id=appointment["patient_id"],
                patient_name=f"{appointment['patient_first_name']} {appointment['patient_last_name']}",
                follow_up_date=appointment["follow_up_date"],
                follow_up_time=appointment.get("follow_up_time"),
                original_visit_date=appointment["visit_date"],
                visit_type=appointment["visit_type"],
                chief_complaint=appointment["chief_complaint"],
                phone=appointment.get("patient_phone"),
                notes=appointment.get("notes")
            ))
        
        return appointments
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting upcoming appointments: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get upcoming appointments"
        )

@app.get("/calendar/overdue", response_model=List[CalendarAppointment], tags=["Calendar"])
async def get_overdue_appointments(current_doctor = Depends(get_current_doctor)):
    """Get all overdue follow-up appointments"""
    try:
        # Get overdue appointments
        appointments_data = await db.get_overdue_follow_up_appointments(
            current_doctor["firebase_uid"]
        )
        
        appointments = []
        for appointment in appointments_data:
            appointments.append(CalendarAppointment(
                visit_id=appointment["visit_id"],
                patient_id=appointment["patient_id"],
                patient_name=f"{appointment['patient_first_name']} {appointment['patient_last_name']}",
                follow_up_date=appointment["follow_up_date"],
                follow_up_time=appointment.get("follow_up_time"),
                original_visit_date=appointment["visit_date"],
                visit_type=appointment["visit_type"],
                chief_complaint=appointment["chief_complaint"],
                phone=appointment.get("patient_phone"),
                notes=appointment.get("notes")
            ))
        
        return appointments
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting overdue appointments: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get overdue appointments"
        )

@app.put("/visits/{visit_id}/follow-up-date", response_model=dict, tags=["Calendar", "Visits"])
async def update_follow_up_date(
    visit_id: int,
    follow_up_date: str,  # YYYY-MM-DD format
    follow_up_time: Optional[str] = None,  # HH:MM format
    current_doctor = Depends(get_current_doctor)
):
    """Update the follow-up date for a visit"""
    try:
        # Validate date format
        from datetime import datetime
        try:
            datetime.strptime(follow_up_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Follow-up date must be in YYYY-MM-DD format"
            )
        
        # Validate time format if provided
        if follow_up_time:
            try:
                datetime.strptime(follow_up_time, "%H:%M")
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Follow-up time must be in HH:MM format"
                )
        
        # Check if visit exists and belongs to current doctor
        existing_visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not existing_visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Update follow-up date
        update_data = {
            "follow_up_date": follow_up_date,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        if follow_up_time:
            update_data["follow_up_time"] = follow_up_time
        
        success = await db.update_visit(visit_id, current_doctor["firebase_uid"], update_data)
        if success:
            return {
                "message": "Follow-up date updated successfully",
                "visit_id": visit_id,
                "follow_up_date": follow_up_date,
                "follow_up_time": follow_up_time
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update follow-up date"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating follow-up date: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update follow-up date"
        )

class AppointmentReminderRequest(BaseModel):
    custom_message: Optional[str] = None

@app.post("/visits/{visit_id}/send-appointment-reminder", response_model=dict)
async def send_appointment_reminder(
    visit_id: int,
    request_data: AppointmentReminderRequest = Body(default=AppointmentReminderRequest()),
    current_doctor = Depends(get_current_doctor)
):
    """
    Send appointment reminder to patient via WhatsApp.
    Used from calendar view to remind patients of upcoming appointments.
    """
    try:
        # Get visit details
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Check if visit has a follow-up date
        follow_up_date = visit.get("follow_up_date")
        if not follow_up_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This visit does not have a follow-up appointment scheduled"
            )
        
        # Get patient details
        patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Check if patient has phone number
        if not patient.get("phone"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient does not have a phone number registered"
            )
        
        # Format the appointment date nicely
        try:
            from datetime import datetime
            appointment_date = datetime.strptime(follow_up_date, "%Y-%m-%d")
            formatted_date = appointment_date.strftime("%d %B %Y")  # e.g., "07 December 2025"
            day_name = appointment_date.strftime("%A")  # e.g., "Sunday"
        except:
            formatted_date = follow_up_date
            day_name = ""
        
        # Get follow-up time if available
        follow_up_time = visit.get("follow_up_time", "")
        time_str = f" at {follow_up_time}" if follow_up_time else ""
        
        # Build the reminder message
        patient_name = f"{patient['first_name']} {patient['last_name']}"
        doctor_name = f"Dr. {current_doctor['first_name']} {current_doctor['last_name']}"
        hospital_name = current_doctor.get("hospital_name", "our clinic")
        
        # Custom message from doctor (if provided)
        doctor_note = ""
        if request_data.custom_message:
            doctor_note = f"""

💬 *Message from {doctor_name}:*
"{request_data.custom_message}"
"""
        
        message = f"""Dear {patient_name},

This is a friendly reminder about your upcoming appointment.

📅 *Appointment Details:*
• Date: {day_name}, {formatted_date}{time_str}
• Doctor: {doctor_name}
• Location: {hospital_name}{doctor_note}

Please arrive 10-15 minutes before your scheduled time. If you need to reschedule, please contact us in advance.

Thank you for choosing us for your healthcare needs.

Best regards,
{hospital_name}"""
        
        # Send WhatsApp message
        try:
            whatsapp_result = await whatsapp_service.send_message(
                to_phone=patient["phone"],
                message=message
            )
            
            if whatsapp_result.get("success"):
                return {
                    "message": "Appointment reminder sent successfully",
                    "visit_id": visit_id,
                    "patient_name": patient_name,
                    "patient_phone": patient["phone"],
                    "appointment_date": follow_up_date,
                    "appointment_time": follow_up_time,
                    "whatsapp_message_id": whatsapp_result.get("message_id"),
                    "sent_at": datetime.now(timezone.utc).isoformat()
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to send WhatsApp message: {whatsapp_result.get('error', 'Unknown error')}"
                )
                
        except HTTPException:
            raise
        except Exception as wa_error:
            print(f"WhatsApp error: {wa_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"WhatsApp service error: {str(wa_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error sending appointment reminder: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send appointment reminder: {str(e)}"
        )


# ============================================================
# AUTOMATIC APPOINTMENT REMINDER ENDPOINTS
# ============================================================

class ReminderSettingsUpdate(BaseModel):
    """Model for updating reminder settings"""
    enabled: bool = True
    hours_before: int = Field(default=24, ge=1, le=72, description="Hours before appointment to send reminder")
    
    class Config:
        json_schema_extra = {
            "example": {
                "enabled": True,
                "hours_before": 24
            }
        }

class ReminderHistoryItem(BaseModel):
    """Model for reminder history item"""
    id: int
    patient_name: str
    patient_phone: str
    appointment_date: str
    appointment_time: Optional[str] = None
    reminder_type: str
    status: str
    sent_at: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str

class ReminderStats(BaseModel):
    """Model for reminder statistics"""
    weekly_total: int
    monthly_sent: int
    monthly_failed: int
    pending: int

class ReminderServiceStatus(BaseModel):
    """Model for reminder service status"""
    running: bool
    check_interval_minutes: int
    default_hours_before: int
    pending_reminders: int
    sent_today: int
    failed_today: int


@app.get("/reminders/settings", response_model=dict, tags=["Appointment Reminders"])
async def get_reminder_settings(current_doctor = Depends(get_current_doctor)):
    """
    Get the current automatic reminder settings for the doctor.
    
    Returns whether automatic reminders are enabled and how many hours
    before appointments the reminders should be sent.
    """
    try:
        settings = await db.get_doctor_reminder_settings(current_doctor["firebase_uid"])
        return {
            "doctor_firebase_uid": current_doctor["firebase_uid"],
            "enabled": settings.get("enabled", True),
            "hours_before": settings.get("hours_before", 24),
            "description": "Automatic WhatsApp reminders will be sent to patients before their appointments"
        }
    except Exception as e:
        print(f"Error getting reminder settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get reminder settings: {str(e)}"
        )


@app.put("/reminders/settings", response_model=dict, tags=["Appointment Reminders"])
async def update_reminder_settings(
    settings: ReminderSettingsUpdate,
    current_doctor = Depends(get_current_doctor)
):
    """
    Update the automatic reminder settings for the doctor.
    
    - **enabled**: Whether to send automatic reminders
    - **hours_before**: How many hours before the appointment to send the reminder (1-72)
    """
    try:
        success = await db.update_doctor_reminder_settings(
            current_doctor["firebase_uid"],
            settings.enabled,
            settings.hours_before
        )
        
        if success:
            return {
                "message": "Reminder settings updated successfully",
                "enabled": settings.enabled,
                "hours_before": settings.hours_before
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update reminder settings"
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating reminder settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update reminder settings: {str(e)}"
        )


@app.get("/reminders/history", response_model=List[ReminderHistoryItem], tags=["Appointment Reminders"])
async def get_reminder_history(
    days: int = Query(default=7, ge=1, le=30, description="Number of days of history to retrieve"),
    current_doctor = Depends(get_current_doctor)
):
    """
    Get the history of sent appointment reminders.
    
    Returns a list of reminders sent in the last N days (default 7, max 30).
    """
    try:
        history = await db.get_reminder_history(current_doctor["firebase_uid"], days)
        
        return [
            ReminderHistoryItem(
                id=item["id"],
                patient_name=item["patient_name"],
                patient_phone=item["patient_phone"],
                appointment_date=item["appointment_date"],
                appointment_time=item.get("appointment_time"),
                reminder_type=item["reminder_type"],
                status=item["status"],
                sent_at=item.get("sent_at"),
                error_message=item.get("error_message"),
                created_at=item["created_at"]
            )
            for item in history
        ]
    except Exception as e:
        print(f"Error getting reminder history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get reminder history: {str(e)}"
        )


@app.get("/reminders/stats", response_model=ReminderStats, tags=["Appointment Reminders"])
async def get_reminder_stats(current_doctor = Depends(get_current_doctor)):
    """
    Get statistics about appointment reminders.
    
    Returns counts of sent, failed, and pending reminders.
    """
    try:
        stats = await db.get_reminder_stats(current_doctor["firebase_uid"])
        return ReminderStats(**stats)
    except Exception as e:
        print(f"Error getting reminder stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get reminder stats: {str(e)}"
        )


@app.get("/reminders/service-status", response_model=ReminderServiceStatus, tags=["Appointment Reminders"])
async def get_reminder_service_status(current_doctor = Depends(get_current_doctor)):
    """
    Get the current status of the automatic reminder service.
    
    Shows whether the service is running and basic statistics.
    """
    try:
        if appointment_reminder_service:
            status_data = await appointment_reminder_service.get_service_status()
            return ReminderServiceStatus(**status_data)
        else:
            return ReminderServiceStatus(
                running=False,
                check_interval_minutes=15,
                default_hours_before=24,
                pending_reminders=0,
                sent_today=0,
                failed_today=0
            )
    except Exception as e:
        print(f"Error getting service status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get service status: {str(e)}"
        )


@app.post("/reminders/send-now/{visit_id}", response_model=dict, tags=["Appointment Reminders"])
async def send_reminder_now(
    visit_id: int,
    custom_message: Optional[str] = Body(default=None, embed=True),
    current_doctor = Depends(get_current_doctor)
):
    """
    Immediately send a reminder for a specific appointment.
    
    This bypasses the automatic scheduling and sends a reminder right away.
    Useful for urgent reminders or re-sending failed reminders.
    
    - **visit_id**: The ID of the visit with the follow-up appointment
    - **custom_message**: Optional custom message to send instead of the default
    """
    try:
        # Verify the visit belongs to this doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        if not visit.get("follow_up_date"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This visit does not have a follow-up appointment scheduled"
            )
        
        if appointment_reminder_service:
            result = await appointment_reminder_service.send_immediate_reminder(
                visit_id=visit_id,
                custom_message=custom_message
            )
            
            if result.get("success"):
                return {
                    "message": "Reminder sent successfully",
                    "reminder_id": result.get("reminder_id"),
                    "patient_name": result.get("patient_name"),
                    "appointment_date": result.get("appointment_date")
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=result.get("error", "Failed to send reminder")
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Reminder service is not available"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error sending immediate reminder: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send reminder: {str(e)}"
        )


@app.put("/visits/{visit_id}/billing", response_model=dict, tags=["Billing", "Visits"])
async def update_visit_billing(
    visit_id: int,
    billing_data: BillingUpdate,
    current_doctor = Depends(get_current_doctor)
):
    """Update billing information for a visit"""
    try:
        # Check if visit exists and belongs to current doctor
        existing_visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not existing_visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Validate payment status
        valid_statuses = ["unpaid", "paid", "partially_paid"]
        if billing_data.payment_status not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment status must be one of: unpaid, paid, partially_paid"
            )
        
        # If marking as paid, set payment_date to today if not provided
        update_data = billing_data.model_dump(exclude_unset=True)
        if billing_data.payment_status == "paid" and not billing_data.payment_date:
            update_data["payment_date"] = datetime.now(timezone.utc).date().isoformat()
        
        # Calculate total amount
        consultation_fee = update_data.get("consultation_fee") or existing_visit.get("consultation_fee", 0) or 0
        additional_charges = update_data.get("additional_charges") or existing_visit.get("additional_charges", 0) or 0
        discount = update_data.get("discount") or existing_visit.get("discount", 0) or 0
        update_data["total_amount"] = max(0, consultation_fee + additional_charges - discount)
        
        success = await db.update_visit_billing(visit_id, current_doctor["firebase_uid"], update_data)
        if success:
            return {
                "message": "Billing information updated successfully",
                "total_amount": update_data["total_amount"],
                "payment_status": billing_data.payment_status
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update billing information"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating visit billing: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update billing information"
        )

@app.get(
    "/earnings/daily/{date}", 
    response_model=EarningsReport,
    tags=["Billing"],
    summary="Get daily earnings report"
)
async def get_daily_earnings(
    date: str,  # Format: YYYY-MM-DD
    current_doctor = Depends(get_current_doctor)
):
    """Get earnings report for a specific date"""
    try:
        # Validate date format
        datetime.strptime(date, "%Y-%m-%d")
        
        report_data = await db.get_daily_earnings(current_doctor["firebase_uid"], date)
        
        return EarningsReport(
            period=f"Daily - {date}",
            total_consultations=report_data["total_consultations"],
            paid_consultations=report_data["paid_consultations"],
            unpaid_consultations=report_data["unpaid_consultations"],
            total_amount=report_data["total_amount"],
            paid_amount=report_data["paid_amount"],
            unpaid_amount=report_data["unpaid_amount"],
            average_per_consultation=report_data["average_per_consultation"],
            breakdown_by_payment_method=report_data["breakdown_by_payment_method"],
            breakdown_by_visit_type=report_data["breakdown_by_visit_type"]
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Use YYYY-MM-DD"
        )
    except Exception as e:
        print(f"Error getting daily earnings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get daily earnings"
        )

@app.get("/earnings/monthly/{year}/{month}", response_model=EarningsReport, tags=["Billing"])
async def get_monthly_earnings(
    year: int,
    month: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get earnings report for a specific month"""
    try:
        if month < 1 or month > 12:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Month must be between 1 and 12"
            )
        
        report_data = await db.get_monthly_earnings(current_doctor["firebase_uid"], year, month)
        
        return EarningsReport(
            period=f"Monthly - {year}-{month:02d}",
            total_consultations=report_data["total_consultations"],
            paid_consultations=report_data["paid_consultations"],
            unpaid_consultations=report_data["unpaid_consultations"],
            total_amount=report_data["total_amount"],
            paid_amount=report_data["paid_amount"],
            unpaid_amount=report_data["unpaid_amount"],
            average_per_consultation=report_data["average_per_consultation"],
            breakdown_by_payment_method=report_data["breakdown_by_payment_method"],
            breakdown_by_visit_type=report_data["breakdown_by_visit_type"]
        )
    except Exception as e:
        print(f"Error getting monthly earnings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get monthly earnings"
        )

@app.get("/earnings/yearly/{year}", response_model=EarningsReport, tags=["Billing"])
async def get_yearly_earnings(
    year: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get earnings report for a specific year"""
    try:
        report_data = await db.get_yearly_earnings(current_doctor["firebase_uid"], year)
        
        return EarningsReport(
            period=f"Yearly - {year}",
            total_consultations=report_data["total_consultations"],
            paid_consultations=report_data["paid_consultations"],
            unpaid_consultations=report_data["unpaid_consultations"],
            total_amount=report_data["total_amount"],
            paid_amount=report_data["paid_amount"],
            unpaid_amount=report_data["unpaid_amount"],
            average_per_consultation=report_data["average_per_consultation"],
            breakdown_by_payment_method=report_data["breakdown_by_payment_method"],
            breakdown_by_visit_type=report_data["breakdown_by_visit_type"]
        )
    except Exception as e:
        print(f"Error getting yearly earnings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get yearly earnings"
        )

@app.post("/earnings/custom", response_model=EarningsReport, tags=["Billing"])
async def get_custom_earnings_report(
    filters: EarningsFilter,
    current_doctor = Depends(get_current_doctor)
):
    """Get custom earnings report with filters"""
    try:
        report_data = await db.get_earnings_report(
            current_doctor["firebase_uid"],
            filters.start_date,
            filters.end_date,
            filters.payment_status,
            filters.visit_type
        )
        
        period_desc = "Custom Period"
        if filters.start_date and filters.end_date:
            period_desc = f"Custom - {filters.start_date} to {filters.end_date}"
        elif filters.start_date:
            period_desc = f"From {filters.start_date}"
        elif filters.end_date:
            period_desc = f"Until {filters.end_date}"
        
        return EarningsReport(
            period=period_desc,
            total_consultations=report_data["total_consultations"],
            paid_consultations=report_data["paid_consultations"],
            unpaid_consultations=report_data["unpaid_consultations"],
            total_amount=report_data["total_amount"],
            paid_amount=report_data["paid_amount"],
            unpaid_amount=report_data["unpaid_amount"],
            average_per_consultation=report_data["average_per_consultation"],
            breakdown_by_payment_method=report_data["breakdown_by_payment_method"],
            breakdown_by_visit_type=report_data["breakdown_by_visit_type"]
        )
    except Exception as e:
        print(f"Error getting custom earnings report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get custom earnings report"
        )

@app.get("/earnings/pending-payments", response_model=list[Visit], tags=["Billing"])
async def get_pending_payments(current_doctor = Depends(get_current_doctor)):
    """Get all visits with pending payments"""
    try:
        pending = await db.get_pending_payments(current_doctor["firebase_uid"])
        return [Visit(**visit) for visit in pending]
    except Exception as e:
        print(f"Error getting pending payments: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get pending payments"
        )

@app.get("/earnings/dashboard", response_model=dict, tags=["Billing"])
async def get_earnings_dashboard(current_doctor = Depends(get_current_doctor)):
    """Get earnings dashboard with today, this month, and this year statistics"""
    try:
        from datetime import datetime, date
        today = date.today()
        
        # Get today's earnings
        today_earnings = await db.get_daily_earnings(current_doctor["firebase_uid"], today.isoformat())
        
        # Get this month's earnings
        month_earnings = await db.get_monthly_earnings(current_doctor["firebase_uid"], today.year, today.month)
        
        # Get this year's earnings
        year_earnings = await db.get_yearly_earnings(current_doctor["firebase_uid"], today.year)
        
        # Get pending payments count
        pending_payments = await db.get_pending_payments(current_doctor["firebase_uid"])
        
        return {
            "today": {
                "consultations": today_earnings["total_consultations"],
                "amount": today_earnings["total_amount"],
                "paid_amount": today_earnings["paid_amount"]
            },
            "this_month": {
                "consultations": month_earnings["total_consultations"],
                "amount": month_earnings["total_amount"],
                "paid_amount": month_earnings["paid_amount"]
            },
            "this_year": {
                "consultations": year_earnings["total_consultations"],
                "amount": year_earnings["total_amount"],
                "paid_amount": year_earnings["paid_amount"]
            },
            "pending_payments": {
                "count": len(pending_payments),
                "amount": sum(float(p.get("total_amount", 0) or 0) for p in pending_payments)
            }
        }
    except Exception as e:
        print(f"Error getting earnings dashboard: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get earnings dashboard"
        )

# PDF Template Management Routes
@app.post(
    "/pdf-templates/upload", 
    response_model=dict,
    tags=["Templates"],
    summary="Upload a prescription template"
)
async def upload_pdf_template(request: Request, current_doctor = Depends(get_current_doctor)):
    """Upload a PDF template for the doctor's clinic"""
    try:
        # Parse multipart form data
        form = await request.form()
        template_name = form.get("template_name")
        is_active = form.get("is_active", "true").lower() == "true"
        files = form.getlist("file")
        
        if not template_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Template name is required"
            )
        
        if not files or len(files) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF file is required"
            )
        
        file = files[0]  # Take the first file
        
        if not hasattr(file, 'filename') or not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Valid PDF file is required"
            )
        
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only PDF files are allowed"
            )
        
        # Read file content
        file_content = await file.read()
        file_size = len(file_content)
        
        # Validate file size (50MB limit)
        if file_size > 50 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File is too large. Maximum size is 50MB."
            )
        
        # Generate unique filename
        file_extension = file.filename.split('.')[-1] if '.' in file.filename else 'pdf'
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        
        # Upload file to Supabase Storage
        bucket_path = f"pdf_templates/{current_doctor['firebase_uid']}/{unique_filename}"
        
        try:
            # Use async storage methods directly
            await supabase.storage.from_("medical-reports").upload(
                path=bucket_path,
                file=file_content,
                file_options={
                    "content-type": "application/pdf",
                    "x-upsert": "false"
                }
            )
            
            # get_public_url is async in the async client
            file_url = await supabase.storage.from_("medical-reports").get_public_url(bucket_path)
            
            print(f"PDF template uploaded to storage: {file.filename} -> {bucket_path}")
        except Exception as storage_error:
            print(f"Error uploading PDF template to storage: {storage_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload file to storage: {str(storage_error)}"
            )
        
        # Create template record in database
        template_data = {
            "doctor_firebase_uid": current_doctor["firebase_uid"],
            "template_name": template_name,
            "file_name": file.filename,
            "file_url": file_url,
            "file_size": file_size,
            "storage_path": bucket_path,
            "is_active": is_active,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        created_template = await db.create_pdf_template(template_data)
        if not created_template:
            # Clean up storage if database insert fails
            try:
                await supabase.storage.from_("medical-reports").remove([bucket_path])
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create template record"
            )
        
        return {
            "message": "PDF template uploaded successfully",
            "template_id": created_template["id"],
            "template_name": template_name,
            "file_name": file.filename,
            "file_url": file_url,
            "file_size": file_size,
            "is_active": is_active
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error uploading PDF template: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload PDF template"
        )

@app.get("/pdf-templates", response_model=list[PDFTemplate], tags=["Templates"])
async def get_pdf_templates(current_doctor = Depends(get_current_doctor)):
    """Get all PDF templates for the current doctor"""
    try:
        templates = await db.get_pdf_templates_by_doctor(current_doctor["firebase_uid"])
        return [PDFTemplate(**template) for template in templates]
    except Exception as e:
        print(f"Error fetching PDF templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch PDF templates"
        )

@app.get("/pdf-templates/{template_id}", response_model=PDFTemplate, tags=["Templates"])
async def get_pdf_template(template_id: int, current_doctor = Depends(get_current_doctor)):
    """Get a specific PDF template"""
    try:
        template = await db.get_pdf_template_by_id(template_id, current_doctor["firebase_uid"])
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="PDF template not found"
            )
        return PDFTemplate(**template)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching PDF template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch PDF template"
        )

@app.put("/pdf-templates/{template_id}", response_model=dict, tags=["Templates"])
async def update_pdf_template(
    template_id: int,
    template_update: PDFTemplateUpload,
    current_doctor = Depends(get_current_doctor)
):
    """Update PDF template information"""
    try:
        # Check if template exists and belongs to current doctor
        existing_template = await db.get_pdf_template_by_id(template_id, current_doctor["firebase_uid"])
        if not existing_template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="PDF template not found"
            )
        
        # Prepare update data
        update_data = {
            "template_name": template_update.template_name,
            "is_active": template_update.is_active,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        success = await db.update_pdf_template(template_id, current_doctor["firebase_uid"], update_data)
        if success:
            return {"message": "PDF template updated successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update PDF template"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating PDF template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update PDF template"
        )

@app.delete("/pdf-templates/{template_id}", response_model=dict, tags=["Templates"])
async def delete_pdf_template(template_id: int, current_doctor = Depends(get_current_doctor)):
    """Delete a PDF template"""
    try:
        # Check if template exists and belongs to current doctor
        existing_template = await db.get_pdf_template_by_id(template_id, current_doctor["firebase_uid"])
        if not existing_template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="PDF template not found"
            )
        
        # Delete file from storage
        if existing_template.get("storage_path"):
            try:
                await supabase.storage.from_("medical-reports").remove([existing_template["storage_path"]])
                print(f"Deleted template file from storage: {existing_template['storage_path']}")
            except Exception as storage_error:
                print(f"Warning: Failed to delete template file from storage: {storage_error}")
        
        # Delete template record
        success = await db.delete_pdf_template(template_id, current_doctor["firebase_uid"])
        if success:
            return {"message": "PDF template deleted successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete PDF template"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting PDF template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete PDF template"
        )

@app.get("/pdf-templates/{template_id}/download", tags=["Templates"])
async def download_pdf_template(template_id: int, current_doctor = Depends(get_current_doctor)):
    """Download a PDF template"""
    try:
        template = await db.get_pdf_template_by_id(template_id, current_doctor["firebase_uid"])
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="PDF template not found"
            )
        
        file_url = template.get("file_url")
        if file_url:
            return RedirectResponse(url=file_url)
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template file not found in storage"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error downloading PDF template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to download PDF template"
        )

# Visit Report Generation Routes
@app.post("/visits/{visit_id}/generate-report", response_model=dict)
async def generate_visit_report(
    visit_id: int,
    request_data: GenerateVisitReportRequest,
    current_doctor = Depends(get_current_doctor)
):
    """Generate a customized visit report using PDF template and send via WhatsApp"""
    try:
        # Verify the visit exists and belongs to the current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get patient information
        patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Get PDF template if specified
        template = None
        if request_data.template_id:
            template = await db.get_pdf_template_by_id(request_data.template_id, current_doctor["firebase_uid"])
            if not template:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="PDF template not found"
                )
            if not template.get("is_active"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="PDF template is not active"
                )
        
        # Import the visit report generator
        from visit_report_generator import VisitReportGenerator
        
        # Generate the customized visit report
        report_generator = VisitReportGenerator()
        pdf_bytes = await report_generator.generate_visit_report(
            visit=visit,
            patient=patient,
            doctor=current_doctor,
            template=template
        )
        
        # Generate filename for the report
        report_filename = f"visit_report_{visit_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        storage_path = f"visit_reports/{current_doctor['firebase_uid']}/{report_filename}"
        
        # Upload report to Supabase Storage using async methods
        try:
            await supabase.storage.from_("medical-reports").upload(
                path=storage_path,
                file=pdf_bytes,
                file_options={
                    "content-type": "application/pdf",
                    "x-upsert": "true"
                }
            )
            
            file_url = await supabase.storage.from_("medical-reports").get_public_url(storage_path)
            
            print(f"Visit report uploaded to storage: {storage_path}")
        except Exception as storage_error:
            print(f"Error uploading visit report to storage: {storage_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload report to storage: {str(storage_error)}"
            )
        
        # Create visit report record
        report_data = {
            "visit_id": visit_id,
            "patient_id": visit["patient_id"],
            "doctor_firebase_uid": current_doctor["firebase_uid"],
            "template_id": request_data.template_id,
            "file_name": report_filename,
            "file_url": file_url,
            "file_size": len(pdf_bytes),
            "storage_path": storage_path,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sent_via_whatsapp": False,
            "whatsapp_message_id": None
        }
        
        created_report = await db.create_visit_report(report_data)
        if not created_report:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create visit report record"
            )
        
        # Prepare response data
        response_data = {
            "message": "Visit report generated successfully",
            "report_id": created_report["id"],
            "visit_id": visit_id,
            "patient_name": f"{patient['first_name']} {patient['last_name']}",
            "patient_phone": patient.get("phone"),
            "doctor_name": f"Dr. {current_doctor['first_name']} {current_doctor['last_name']}",
            "report_url": file_url,
            "report_filename": report_filename,
            "template_used": template["template_name"] if template else "Default Template",
            "whatsapp_sent": False,
            "whatsapp_error": None
        }
        
        # Send WhatsApp message if requested and patient has phone number
        if request_data.send_whatsapp and patient.get("phone"):
            try:
                custom_message = request_data.custom_message or ""
                whatsapp_result = await whatsapp_service.send_visit_report(
                    patient_name=f"{patient['first_name']} {patient['last_name']}",
                    doctor_name=f"Dr. {current_doctor['first_name']} {current_doctor['last_name']}",
                    phone_number=patient["phone"],
                    report_url=file_url,
                    visit_date=visit["visit_date"],
                    custom_message=custom_message
                )
                
                if whatsapp_result["success"]:
                    # Update report record with WhatsApp info
                    await db.update_visit_report(created_report["id"], {
                        "sent_via_whatsapp": True,
                        "whatsapp_message_id": whatsapp_result.get("message_id")
                    })
                    
                    response_data["whatsapp_sent"] = True
                    response_data["whatsapp_message_id"] = whatsapp_result.get("message_id")
                    response_data["message"] = "Visit report generated and sent via WhatsApp successfully"
                else:
                    response_data["whatsapp_error"] = whatsapp_result.get("error")
                    response_data["message"] = "Visit report generated but WhatsApp sending failed"
                    
            except Exception as whatsapp_error:
                print(f"WhatsApp sending error: {whatsapp_error}")
                response_data["whatsapp_error"] = str(whatsapp_error)
                response_data["message"] = "Visit report generated but WhatsApp sending failed"
        elif request_data.send_whatsapp and not patient.get("phone"):
            response_data["whatsapp_error"] = "Patient phone number not found"
            response_data["message"] = "Visit report generated but patient has no phone number for WhatsApp"
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generating visit report: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate visit report"
        )

@app.get("/visits/{visit_id}/generated-reports", response_model=list[VisitReport])
async def get_visit_reports_generated(visit_id: int, current_doctor = Depends(get_current_doctor)):
    """Get all generated visit reports (PDF summaries) for a specific visit.
    
    Note: For uploaded medical/lab reports, use GET /visits/{visit_id}/reports instead.
    """
    try:
        # Verify the visit exists and belongs to the current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get visit reports
        reports = await db.get_visit_reports_by_visit_id(visit_id, current_doctor["firebase_uid"])
        return [VisitReport(**report) for report in reports]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching visit reports: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch visit reports"
        )

@app.get("/patients/{patient_id}/visit-reports", response_model=list[VisitReport])
async def get_patient_visit_reports(patient_id: int, current_doctor = Depends(get_current_doctor)):
    """Get all generated visit reports for a specific patient"""
    try:
        # Verify the patient exists and belongs to the current doctor
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Get visit reports for this patient
        reports = await db.get_visit_reports_by_patient_id(patient_id, current_doctor["firebase_uid"])
        return [VisitReport(**report) for report in reports]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching patient visit reports: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch patient visit reports"
        )

@app.get("/visit-reports/{report_id}/download")
async def download_visit_report(report_id: int, current_doctor = Depends(get_current_doctor)):
    """Download a generated visit report"""
    try:
        report = await db.get_visit_report_by_id(report_id, current_doctor["firebase_uid"])
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit report not found"
            )
        
        file_url = report.get("file_url")
        if file_url:
            return RedirectResponse(url=file_url)
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report file not found in storage"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error downloading visit report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to download visit report"
        )

@app.post("/visit-reports/{report_id}/resend-whatsapp", response_model=dict)
async def resend_visit_report_whatsapp(
    report_id: int, 
    custom_message: Optional[str] = None,
    current_doctor = Depends(get_current_doctor)
):
    """Resend a visit report via WhatsApp"""
    try:
        # Get the visit report
        report = await db.get_visit_report_by_id(report_id, current_doctor["firebase_uid"])
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit report not found"
            )
        
        # Get visit and patient information
        visit = await db.get_visit_by_id(report["visit_id"], current_doctor["firebase_uid"])
        patient = await db.get_patient_by_id(report["patient_id"], current_doctor["firebase_uid"])
        
        if not patient.get("phone"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient phone number not found"
            )
        
        # Send WhatsApp message
        whatsapp_result = await whatsapp_service.send_visit_report(
            patient_name=f"{patient['first_name']} {patient['last_name']}",
            doctor_name=f"Dr. {current_doctor['first_name']} {current_doctor['last_name']}",
            phone_number=patient["phone"],
            report_url=report["file_url"],
            visit_date=visit["visit_date"],
            custom_message=custom_message or ""
        )
        
        if whatsapp_result["success"]:
            # Update report record
            await db.update_visit_report(report_id, {
                "sent_via_whatsapp": True,
                "whatsapp_message_id": whatsapp_result.get("message_id")
            })
            
            return {
                "message": "Visit report sent via WhatsApp successfully",
                "whatsapp_message_id": whatsapp_result.get("message_id"),
                "patient_phone": patient["phone"]
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to send WhatsApp message: {whatsapp_result.get('error')}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error resending visit report via WhatsApp: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resend visit report via WhatsApp"
        )

# Test endpoint for simple WhatsApp messages (Twilio)
@app.post("/test-whatsapp-simple", response_model=dict)
async def test_whatsapp_simple_message(
    phone_number: str,
    message: str = "Hello! This is a test message from your doctor's app using Twilio WhatsApp API.",
    current_doctor = Depends(get_current_doctor)
):
    """Send a simple WhatsApp message using Twilio (no templates needed)"""
    try:
        test_message = f"""🏥 *Test Message from Dr. {current_doctor['first_name']} {current_doctor['last_name']}*

{message}

✅ Sent via Twilio WhatsApp API
📱 Phone: {phone_number}
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Thank you!"""

        result = await whatsapp_service.send_message(phone_number, test_message)
        
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result)
        
        return {
            "success": True,
            "message": "Twilio WhatsApp message sent successfully",
            "message_id": result.get("message_id"),
            "phone_number": result.get("phone_number"),
            "status": result.get("status"),
            "service": "twilio"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error sending WhatsApp message: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"WhatsApp message error: {str(e)}"
        )

# AI Document Analysis Routes
@app.post("/reports/{report_id}/analyze", response_model=dict)
async def analyze_report_with_ai(
    report_id: int,
    request_data: AIAnalysisRequest,
    current_doctor = Depends(get_current_doctor)
):
    """Analyze a specific report using AI with patient and visit context"""
    try:
        # Check if AI is enabled for this doctor
        check_ai_enabled(current_doctor)
        
        start_time = datetime.now()
        
        # Get the report
        report = await db.get_report_by_id(report_id, current_doctor["firebase_uid"])
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report not found"
            )
        
        # Check if analysis already exists
        existing_analysis = await db.get_ai_analysis_by_report_id(report_id, current_doctor["firebase_uid"])
        if existing_analysis:
            return {
                "message": "Analysis already exists for this report",
                "analysis": AIAnalysisResult(**existing_analysis),
                "already_exists": True
            }
        
        # Get visit and patient context
        visit = await db.get_visit_by_id(report["visit_id"], current_doctor["firebase_uid"])
        patient = await db.get_patient_by_id(report["patient_id"], current_doctor["firebase_uid"])
        
        if not visit or not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit or patient information not found"
            )
        
        # Get case visit chain context for continuity of care
        visit_chain_context = []
        if visit.get("case_id"):
            print(f"📎 This visit is part of a case - fetching visit chain context for AI analysis")
            try:
                visit_chain_context = await db.get_visits_by_case(visit["case_id"], current_doctor["firebase_uid"])
                # Remove current visit from chain (we only want previous visits)
                visit_chain_context = [v for v in visit_chain_context if v["id"] != report["visit_id"]]
                
                # Enrich chain with reports and AI analyses for context
                for chain_visit in visit_chain_context:
                    chain_visit_id = chain_visit["id"]
                    # Get reports for this visit
                    chain_reports = await db.get_reports_by_visit_id(chain_visit_id, current_doctor["firebase_uid"])
                    chain_visit["reports"] = [{"file_name": r["file_name"], "test_type": r.get("test_type")} for r in (chain_reports or [])[:5]]
                    # Get AI analyses summary
                    chain_analyses = await db.get_ai_analyses_by_visit_id(chain_visit_id, current_doctor["firebase_uid"])
                    chain_visit["ai_analyses_summary"] = [{"document_summary": a.get("document_summary", "")[:150]} for a in (chain_analyses or [])[:3]]
                
                print(f"✅ Found {len(visit_chain_context)} case visits for context")
            except Exception as chain_error:
                print(f"⚠️ Could not fetch visit chain context: {chain_error}")
                visit_chain_context = []
        
        # Download the file from storage for analysis using async non-blocking download
        file_url = report["file_url"]
        try:
            # Use async file downloader to prevent blocking during download
            file_content = await file_downloader.download_file(
                url=file_url,
                stream=True  # Use streaming for large files
            )
            
            if not file_content:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Report file not accessible"
                )
                
        except Exception as download_error:
            print(f"Error downloading file for analysis: {download_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to download report file for analysis"
            )
        
        # Perform AI analysis with visit chain context
        analysis_result = await ai_analysis_service.analyze_document(
            file_content=file_content,
            file_name=report["file_name"],
            file_type=report["file_type"],
            patient_context=patient,
            visit_context=visit,
            doctor_context=current_doctor,
            visit_chain_context=visit_chain_context if visit_chain_context else None
        )
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        if analysis_result["success"]:
            # Store analysis in database with enhanced visit-contextual fields
            analysis_data = {
                "report_id": report_id,
                "visit_id": report["visit_id"],
                "patient_id": report["patient_id"],
                "doctor_firebase_uid": current_doctor["firebase_uid"],
                "analysis_type": "document_analysis",
                "model_used": analysis_result["model_used"],
                "confidence_score": analysis_result["analysis"]["confidence_score"],
                "raw_analysis": analysis_result["analysis"]["raw_analysis"],
                # Enhanced visit-contextual fields
                "clinical_correlation": analysis_result["analysis"]["structured_analysis"].get("clinical_correlation"),
                "detailed_findings": analysis_result["analysis"]["structured_analysis"].get("detailed_findings"),
                "critical_findings": analysis_result["analysis"]["structured_analysis"].get("critical_findings"),
                "treatment_evaluation": analysis_result["analysis"]["structured_analysis"].get("treatment_evaluation"),
                # Original fields (keeping for backward compatibility)
                "document_summary": analysis_result["analysis"]["structured_analysis"].get("document_summary"),
                "clinical_significance": analysis_result["analysis"]["structured_analysis"].get("clinical_significance"),
                "correlation_with_patient": analysis_result["analysis"]["structured_analysis"].get("correlation_with_patient"),
                "actionable_insights": analysis_result["analysis"]["structured_analysis"].get("actionable_insights"),
                "patient_communication": analysis_result["analysis"]["structured_analysis"].get("patient_communication"),
                "clinical_notes": analysis_result["analysis"]["structured_analysis"].get("clinical_notes"),
                "key_findings": analysis_result["analysis"]["key_findings"],
                "analysis_success": True,
                "analysis_error": None,
                "processing_time_ms": int(processing_time),
                "analyzed_at": analysis_result["processed_at"],
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            created_analysis = await db.create_ai_analysis(analysis_data)
            if created_analysis:
                return {
                    "message": "AI analysis completed successfully",
                    "analysis": AIAnalysisResult(**created_analysis),
                    "processing_time_ms": int(processing_time),
                    "already_exists": False
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to save analysis results"
                )
        else:
            # Store failed analysis
            analysis_data = {
                "report_id": report_id,
                "visit_id": report["visit_id"],
                "patient_id": report["patient_id"],
                "doctor_firebase_uid": current_doctor["firebase_uid"],
                "analysis_type": "document_analysis",
                "model_used": "gemini-2.0-flash-exp",
                "confidence_score": 0.0,
                "raw_analysis": "",
                "analysis_success": False,
                "analysis_error": analysis_result["error"],
                "processing_time_ms": int(processing_time),
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            await db.create_ai_analysis(analysis_data)
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"AI analysis failed: {analysis_result['error']}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in AI analysis: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to perform AI analysis"
        )

@app.post("/visits/{visit_id}/analyze-consolidated", response_model=dict)
async def analyze_visit_reports_consolidated(
    visit_id: int,
    request_data: ConsolidatedAnalysisRequest,
    current_doctor = Depends(get_current_doctor)
):
    """Analyze all reports for a visit with consolidated AI analysis"""
    try:
        # Check if AI is enabled for this doctor
        check_ai_enabled(current_doctor)
        
        start_time = datetime.now()
        
        # Verify the visit exists
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get patient information
        patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Get reports for the visit
        if request_data.report_ids:
            # Use specified reports
            reports = []
            for report_id in request_data.report_ids:
                report = await db.get_report_by_id(report_id, current_doctor["firebase_uid"])
                if report and report["visit_id"] == visit_id:
                    reports.append(report)
        else:
            # Use all reports for the visit
            reports = await db.get_reports_by_visit_id(visit_id, current_doctor["firebase_uid"])
        
        if not reports:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No reports found for this visit"
            )
        
        # Check if consolidated analysis already exists
        existing_analyses = await db.get_consolidated_analyses_by_visit_id(visit_id, current_doctor["firebase_uid"])
        report_ids = [report["id"] for report in reports]
        
        for existing in existing_analyses:
            if set(existing.get("report_ids", [])) == set(report_ids):
                return {
                    "message": "Consolidated analysis already exists for these reports",
                    "analysis": ConsolidatedAnalysisResult(**existing),
                    "already_exists": True
                }
        
        # Download and prepare documents for analysis using async non-blocking downloads
        documents = []
        
        # Use concurrent downloads to speed up multiple file downloads
        file_urls = [report["file_url"] for report in reports]
        downloaded_files = await file_downloader.download_multiple_files(
            urls=file_urls,
            concurrent_limit=5  # Download max 5 files at once
        )
        
        # Process downloaded files
        for report in reports:
            file_url = report["file_url"]
            file_content = downloaded_files.get(file_url)
            
            if file_content:
                documents.append({
                    "content": file_content,
                    "file_name": report["file_name"],
                    "file_type": report["file_type"],
                    "test_type": report.get("test_type", "General Report")
                })
            else:
                print(f"⚠️ Failed to download report {report['id']}")
        
        if not documents:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to download any report files for analysis"
            )
        
        # Perform consolidated AI analysis
        analysis_result = await ai_analysis_service.analyze_multiple_documents(
            documents=documents,
            patient_context=patient,
            visit_context=visit,
            doctor_context=current_doctor
        )
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        if analysis_result["success"]:
            # Store consolidated analysis in database
            analysis_data = {
                "visit_id": visit_id,
                "patient_id": visit["patient_id"],
                "doctor_firebase_uid": current_doctor["firebase_uid"],
                "report_ids": report_ids,
                "document_count": len(documents),
                "model_used": "gemini-2.0-flash-exp",
                "confidence_score": 0.85,  # Default confidence for consolidated analysis
                "raw_analysis": analysis_result["consolidated_analysis"],
                "overall_assessment": analysis_result["consolidated_analysis"][:500] + "..." if len(analysis_result["consolidated_analysis"]) > 500 else analysis_result["consolidated_analysis"],
                "clinical_picture": "",
                "integrated_recommendations": "",
                "patient_summary": "",
                "consolidated_findings": [],
                "priority_actions": [],
                "analysis_success": True,
                "analysis_error": None,
                "processing_time_ms": int(processing_time),
                "analyzed_at": analysis_result["processed_at"],
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            created_analysis = await db.create_consolidated_analysis(analysis_data)
            if created_analysis:
                return {
                    "message": "Consolidated AI analysis completed successfully",
                    "analysis": ConsolidatedAnalysisResult(**created_analysis),
                    "documents_analyzed": len(documents),
                    "processing_time_ms": int(processing_time),
                    "already_exists": False
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to save consolidated analysis results"
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Consolidated AI analysis failed: {analysis_result.get('error')}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in consolidated AI analysis: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to perform consolidated AI analysis"
        )

@app.get("/reports/{report_id}/analysis", response_model=AIAnalysisResult)
async def get_report_analysis(
    report_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get AI analysis results for a specific report"""
    try:
        analysis = await db.get_ai_analysis_by_report_id(report_id, current_doctor["firebase_uid"])
        if not analysis:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="AI analysis not found for this report"
            )
        
        return AIAnalysisResult(**analysis)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching AI analysis: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch AI analysis"
        )

@app.get("/visits/{visit_id}/analyses", response_model=List[AIAnalysisResult])
async def get_visit_analyses(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get all AI analyses for a visit"""
    try:
        # Verify the visit exists
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        analyses = await db.get_ai_analyses_by_visit_id(visit_id, current_doctor["firebase_uid"])
        return [AIAnalysisResult(**analysis) for analysis in analyses]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching visit analyses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch visit analyses"
        )

@app.get("/visits/{visit_id}/consolidated-analyses", response_model=List[ConsolidatedAnalysisResult])
async def get_visit_consolidated_analyses(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get all consolidated AI analyses for a visit"""
    try:
        # Verify the visit exists
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        analyses = await db.get_consolidated_analyses_by_visit_id(visit_id, current_doctor["firebase_uid"])
        return [ConsolidatedAnalysisResult(**analysis) for analysis in analyses]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching consolidated analyses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch consolidated analyses"
        )

@app.get("/patients/{patient_id}/analyses", response_model=List[AIAnalysisResult])
async def get_patient_analyses(
    patient_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get all AI analyses for a patient"""
    try:
        # Verify the patient exists
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        analyses = await db.get_ai_analyses_by_patient_id(patient_id, current_doctor["firebase_uid"])
        return [AIAnalysisResult(**analysis) for analysis in analyses]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching patient analyses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch patient analyses"
        )

@app.get("/visits/{visit_id}/reports-with-analysis", response_model=List[ReportWithAnalysis])
async def get_visit_reports_with_analysis(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get all reports for a visit along with their AI analysis status"""
    try:
        # Verify the visit exists
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get reports
        reports = await db.get_reports_by_visit_id(visit_id, current_doctor["firebase_uid"])
        
        # Get analyses for each report
        result = []
        for report in reports:
            analysis = await db.get_ai_analysis_by_report_id(report["id"], current_doctor["firebase_uid"])
            
            if analysis:
                if analysis["analysis_success"]:
                    status = "completed"
                else:
                    status = "failed"
                ai_analysis = AIAnalysisResult(**analysis)
            else:
                status = "not_requested"
                ai_analysis = None
            
            result.append(ReportWithAnalysis(
                report=Report(**report),
                ai_analysis=ai_analysis,
                analysis_status=status
            ))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching reports with analysis: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch reports with analysis"
        )

@app.get("/ai-analysis-summary", response_model=AIAnalysisSummary)
async def get_ai_analysis_summary_for_doctor(
    patient_id: Optional[int] = None,
    visit_id: Optional[int] = None,
    current_doctor = Depends(get_current_doctor)
):
    """Get AI analysis summary for the doctor (optionally filtered by patient or visit)"""
    try:
        summary = await db.get_ai_analysis_summary(
            current_doctor["firebase_uid"],
            patient_id,
            visit_id
        )
        
        return AIAnalysisSummary(**summary)
        
    except Exception as e:
        print(f"Error fetching AI analysis summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch AI analysis summary"
        )

@app.post("/reports/batch-analyze", response_model=dict)
async def batch_analyze_reports(
    report_ids: List[int],
    priority: int = 1,
    current_doctor = Depends(get_current_doctor)
):
    """Queue multiple reports for AI analysis"""
    try:
        # Check if AI is enabled for this doctor
        check_ai_enabled(current_doctor)
        
        queued_analyses = []
        failed_analyses = []
        
        for report_id in report_ids:
            # Check if report exists and belongs to current doctor
            report = await db.get_report_by_id(report_id, current_doctor["firebase_uid"])
            if not report:
                failed_analyses.append({
                    "report_id": report_id,
                    "error": "Report not found"
                })
                continue
            
            # Check if analysis already exists
            existing_analysis = await db.get_ai_analysis_by_report_id(report_id, current_doctor["firebase_uid"])
            if existing_analysis:
                failed_analyses.append({
                    "report_id": report_id,
                    "error": "Analysis already exists"
                })
                continue
            
            # Queue analysis
            queue_data = {
                "report_id": report_id,
                "visit_id": report["visit_id"],
                "patient_id": report["patient_id"],
                "doctor_firebase_uid": current_doctor["firebase_uid"],
                "priority": priority,
                "status": "pending",
                "queued_at": datetime.now(timezone.utc).isoformat()
            }
            
            queued = await db.queue_ai_analysis(queue_data)
            if queued:
                queued_analyses.append(report_id)
            else:
                failed_analyses.append({
                    "report_id": report_id,
                    "error": "Failed to queue analysis"
                })
        
        return {
            "message": f"Queued {len(queued_analyses)} reports for AI analysis",
            "queued_reports": queued_analyses,
            "failed_reports": failed_analyses,
            "total_requested": len(report_ids),
            "successfully_queued": len(queued_analyses),
            "failed_count": len(failed_analyses)
        }
        
    except Exception as e:
        print(f"Error in batch analysis: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue batch analysis"
        )

@app.get("/ai-processor-status")
async def get_ai_processor_status(current_doctor: dict = Depends(get_current_doctor)):
    """Get the status of the AI analysis background processor"""
    try:
        global ai_processor
        
        if not ai_processor:
            return {
                "processor_initialized": False,
                "processor_running": False,
                "error": "Processor not initialized"
            }
        
        # Get processor statistics
        stats = await ai_processor.get_processing_stats()
        
        return {
            "processor_initialized": True,
            "processor_running": ai_processor.is_running,
            "processing_interval_seconds": ai_processor.process_interval,
            "max_concurrent_analyses": ai_processor.max_concurrent,
            "queue_statistics": stats
        }
        
    except Exception as e:
        print(f"Error getting processor status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get processor status"
        )

@app.get("/ai-queue-stats")
async def get_ai_queue_stats(current_doctor: dict = Depends(get_current_doctor)):
    """Get AI analysis queue statistics"""
    try:
        # Get overall queue stats
        overall_stats = await db.get_queue_stats()
        
        # Get doctor-specific stats
        doctor_stats = await db.get_queue_stats(current_doctor["firebase_uid"])
        
        return {
            "overall_queue": overall_stats,
            "your_queue": doctor_stats
        }
    except Exception as e:
        print(f"Error getting queue stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get queue statistics"
        )

@app.post("/ai-queue-cleanup")
async def trigger_queue_cleanup(current_doctor: dict = Depends(get_current_doctor)):
    """Manually trigger AI analysis queue cleanup"""
    try:
        # Get stats before cleanup
        before_stats = await db.get_queue_stats()
        
        # Run cleanup
        completed_cleaned = await db.cleanup_completed_queue_items(hours_old=24)
        stale_reset = await db.cleanup_stale_processing_items(hours_stale=2)
        
        # Get stats after cleanup
        after_stats = await db.get_queue_stats()
        
        return {
            "message": "Queue cleanup completed",
            "completed_items_removed": completed_cleaned,
            "stale_items_reset": stale_reset,
            "queue_before": before_stats,
            "queue_after": after_stats
        }
    except Exception as e:
        print(f"Error during manual queue cleanup: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cleanup queue"
        )

# ============================================================================
# CLINICAL ALERTS ENDPOINTS
# ============================================================================

@app.get("/alerts", response_model=AlertListResponse, tags=["Clinical Alerts"])
async def get_clinical_alerts(
    patient_id: Optional[int] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Get unacknowledged clinical alerts for the current doctor.
    
    Returns AI-generated alerts from document analysis including critical lab values,
    drug interactions, and urgent findings requiring attention.
    
    **Query Parameters:**
    - **patient_id**: Optional - Filter alerts by specific patient
    - **severity**: Optional - Filter by severity level (high, medium, low)
    - **limit**: Maximum alerts to return (default: 50, max: 100)
    
    **Response:**
    - **alerts**: List of alert objects with details
    - **count**: Total number of alerts returned
    
    **Alert Object Properties:**
    - id, alert_type, severity, title, description
    - source_finding, recommended_action
    - patient_id, visit_id, analysis_id
    - created_at, acknowledged (always false for this endpoint)
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        alerts = await db.get_unacknowledged_alerts(
            doctor_firebase_uid=doctor_uid,
            patient_id=patient_id,
            severity=severity,
            limit=limit
        )
        
        return {
            "alerts": alerts,
            "count": len(alerts)
        }
    except Exception as e:
        print(f"Error getting clinical alerts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get clinical alerts"
        )

@app.get("/alerts/counts", response_model=dict, tags=["Clinical Alerts"])
async def get_alert_counts(current_doctor: dict = Depends(get_current_doctor)):
    """
    Get counts of unacknowledged alerts grouped by severity.
    
    Useful for displaying alert badges/indicators in the UI without
    fetching full alert details.
    
    **Response:**
    - **counts**: Object with high, medium, low, and total counts
    - **has_alerts**: Boolean indicating if any alerts exist
    - **has_high_priority**: Boolean indicating critical alerts exist
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        counts = await db.get_alert_counts(doctor_uid)
        
        return {
            "counts": counts,
            "has_alerts": counts.get("total", 0) > 0,
            "has_high_priority": counts.get("high", 0) > 0
        }
    except Exception as e:
        print(f"Error getting alert counts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get alert counts"
        )

@app.post("/alerts/{alert_id}/acknowledge", response_model=dict, tags=["Clinical Alerts"])
async def acknowledge_alert(
    alert_id: str,
    notes: Optional[str] = None,
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Acknowledge a clinical alert.
    
    Marks the alert as reviewed by the doctor. Acknowledged alerts
    won't appear in the unacknowledged alerts list but remain in history.
    
    **Path Parameters:**
    - **alert_id**: UUID of the alert to acknowledge
    
    **Body Parameters:**
    - **notes**: Optional notes about actions taken (max 1000 chars)
    
    **Response:**
    - **message**: Success confirmation
    - **alert_id**: ID of acknowledged alert
    
    **Errors:**
    - 404: Alert not found or already acknowledged
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        success = await db.acknowledge_alert(
            alert_id=alert_id,
            doctor_firebase_uid=doctor_uid,
            notes=notes
        )
        
        if success:
            return {
                "message": "Alert acknowledged successfully",
                "alert_id": alert_id
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alert not found or already acknowledged"
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error acknowledging alert: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to acknowledge alert"
        )

@app.post("/patients/{patient_id}/alerts/acknowledge-all", response_model=dict, tags=["Clinical Alerts"])
async def acknowledge_all_patient_alerts(
    patient_id: int,
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Acknowledge all unacknowledged alerts for a specific patient.
    
    Bulk operation useful when reviewing a patient's complete alert history.
    
    **Path Parameters:**
    - **patient_id**: ID of the patient
    
    **Response:**
    - **message**: Success confirmation with count
    - **patient_id**: ID of the patient
    - **acknowledged_count**: Number of alerts acknowledged
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        count = await db.acknowledge_all_patient_alerts(
            patient_id=patient_id,
            doctor_firebase_uid=doctor_uid
        )
        
        return {
            "message": f"Acknowledged {count} alerts for patient",
            "patient_id": patient_id,
            "acknowledged_count": count
        }
    except Exception as e:
        print(f"Error acknowledging patient alerts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to acknowledge alerts"
        )

@app.get("/patients/{patient_id}/alerts/history", response_model=dict, tags=["Clinical Alerts"])
async def get_patient_alert_history(
    patient_id: int,
    days: int = 90,
    include_acknowledged: bool = True,
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Get complete alert history for a patient.
    
    Returns both acknowledged and unacknowledged alerts within the
    specified time period for historical review.
    
    **Path Parameters:**
    - **patient_id**: ID of the patient
    
    **Query Parameters:**
    - **days**: Number of days of history (default: 90, max: 365)
    - **include_acknowledged**: Include acknowledged alerts (default: true)
    
    **Response:**
    - **alerts**: List of alert objects with acknowledgment details
    - **count**: Total alerts returned
    - **patient_id**: Patient ID
    - **days**: Days of history returned
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        alerts = await db.get_patient_alert_history(
            patient_id=patient_id,
            doctor_firebase_uid=doctor_uid,
            days=days,
            include_acknowledged=include_acknowledged
        )
        
        return {
            "alerts": alerts,
            "count": len(alerts),
            "patient_id": patient_id,
            "days": days
        }
    except Exception as e:
        print(f"Error getting patient alert history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get alert history"
        )

@app.get("/visits/{visit_id}/alerts", response_model=dict, tags=["Clinical Alerts"])
async def get_visit_alerts(
    visit_id: int,
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Get all alerts generated during a specific visit.
    
    Returns alerts from all document analyses performed during the visit,
    useful for reviewing findings from a particular consultation.
    
    **Path Parameters:**
    - **visit_id**: ID of the visit
    
    **Response:**
    - **alerts**: List of alert objects for this visit
    - **count**: Total alerts for the visit
    - **visit_id**: Visit ID
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        alerts = await db.get_alerts_for_visit(
            visit_id=visit_id,
            doctor_firebase_uid=doctor_uid
        )
        
        return {
            "alerts": alerts,
            "count": len(alerts),
            "visit_id": visit_id
        }
    except Exception as e:
        print(f"Error getting visit alerts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get visit alerts"
        )

# ============================================================================
# END OF CLINICAL ALERTS ENDPOINTS
# ============================================================================

# ============================================================================
# PHASE 2: CLINICAL INTELLIGENCE ENDPOINTS
# ============================================================================

# Import medication service
from medication_service import MedicationInteractionService, get_medication_service

# Pydantic models for Phase 2 endpoints
class MedicationCheckRequest(BaseModel):
    current_medications: List[str] = Field(default=[], description="List of current medications")
    new_medications: List[str] = Field(default=[], description="List of new medications to check")
    patient_allergies: str = Field(default="", description="Patient's known allergies")
    patient_conditions: Optional[List[str]] = Field(default=None, description="Patient's medical conditions")

class VisitSummaryRequest(BaseModel):
    include_reports: bool = Field(default=True, description="Include AI report analyses")
    include_handwritten: bool = Field(default=True, description="Include handwritten note analyses")

class RiskScoreRequest(BaseModel):
    recalculate: bool = Field(default=False, description="Force recalculation even if recent score exists")
    include_all_visits: bool = Field(default=True, description="Include all visits in analysis")

# -------------------------------------------------------------------------
# Medication Interaction Checking (Phase 2.1)
# -------------------------------------------------------------------------

@app.post("/medications/check-interactions", response_model=dict, tags=["Clinical Intelligence"])
async def check_medication_interactions(
    request: MedicationCheckRequest,
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Check for drug-drug interactions and allergy conflicts.
    
    Phase 2.1: Medication Interaction Checking
    
    This endpoint performs comprehensive medication safety checks including:
    - Drug-drug interactions with severity levels
    - Allergy conflict detection
    - Condition-based contraindications
    
    **Request Body:**
    - **current_medications**: List of medications patient is currently taking
    - **new_medications**: New medications being prescribed
    - **patient_allergies**: Comma-separated string of known allergies
    - **patient_conditions**: Optional list of medical conditions
    
    **Response:**
    - **drug_interactions**: List of detected drug interactions
    - **allergy_warnings**: List of allergy conflicts
    - **contraindications**: List of condition-based contraindications
    - **summary**: Overall safety assessment
    - **recommendations**: Prioritized action recommendations
    """
    try:
        med_service = get_medication_service()
        
        result = await med_service.comprehensive_medication_check(
            current_medications=request.current_medications,
            new_medications=request.new_medications,
            patient_allergies=request.patient_allergies,
            patient_conditions=request.patient_conditions
        )
        
        return {
            "success": True,
            "check_result": result,
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"Error checking medication interactions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check medication interactions"
        )

@app.post("/patients/{patient_id}/check-medications", response_model=dict, tags=["Clinical Intelligence"])
async def check_patient_medication_safety(
    patient_id: int,
    new_medications: List[str] = Body(..., description="New medications to check"),
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Check medication safety for a specific patient using their profile data.
    
    Automatically uses patient's allergies and medical history from their profile.
    
    **Path Parameters:**
    - **patient_id**: ID of the patient
    
    **Request Body:**
    - **new_medications**: List of new medications to check
    
    **Response:**
    - Complete safety check using patient's profile data
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        # Get patient data
        patient = await db.get_patient_by_id(patient_id, doctor_uid)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Get current medications from recent visits
        visits = await db.get_visits_by_patient_id(patient_id, doctor_uid)
        current_meds = []
        if visits:
            # Get medications from last visit
            recent_visit = visits[0]
            if recent_visit.get("medications"):
                current_meds = [recent_visit["medications"]]
        
        # Extract conditions from medical history
        med_service = get_medication_service()
        conditions = med_service._extract_conditions_from_history(
            patient.get("medical_history", "")
        )
        
        result = await med_service.comprehensive_medication_check(
            current_medications=current_meds,
            new_medications=new_medications,
            patient_allergies=patient.get("allergies", ""),
            patient_conditions=conditions,
            patient_context=patient
        )
        
        return {
            "success": True,
            "patient_id": patient_id,
            "patient_name": f"{patient.get('first_name', '')} {patient.get('last_name', '')}",
            "check_result": result,
            "current_medications_detected": current_meds,
            "conditions_detected": conditions,
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error checking patient medication safety: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check medication safety"
        )

# -------------------------------------------------------------------------
# Visit Summary / SOAP Note Generation (Phase 2.3)
# -------------------------------------------------------------------------

@app.post("/visits/{visit_id}/generate-summary", response_model=dict, tags=["Clinical Intelligence"])
async def generate_visit_summary(
    visit_id: int,
    request: VisitSummaryRequest = VisitSummaryRequest(),
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Generate AI-powered SOAP note visit summary for documentation.
    
    Phase 2.3: Smart Visit Summary Generation
    
    Generates a professional SOAP (Subjective, Objective, Assessment, Plan) note
    from visit data, including AI analyses of reports and handwritten notes.
    
    **Path Parameters:**
    - **visit_id**: ID of the visit
    
    **Query Parameters:**
    - **include_reports**: Include AI report analyses (default: true)
    - **include_handwritten**: Include handwritten note analyses (default: true)
    
    **Response:**
    - **soap_note**: Structured SOAP data (subjective, objective, assessment, plan)
    - **soap_note_text**: Formatted text version for display/printing
    - **icd10_codes**: Suggested ICD-10 codes
    - **cpt_codes**: Suggested CPT codes
    """
    try:
        check_ai_enabled(current_doctor)
        doctor_uid = current_doctor["firebase_uid"]
        
        # Get visit data
        visit = await db.get_visit_by_id(visit_id, doctor_uid)
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Get patient data
        patient = await db.get_patient_by_id(visit["patient_id"], doctor_uid)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Check if summary already exists
        existing_summary = await db.get_visit_summary(visit_id, doctor_uid)
        if existing_summary:
            return {
                "success": True,
                "message": "Visit summary already exists",
                "already_exists": True,
                "summary": existing_summary
            }
        
        # Get reports and analyses if requested
        reports = []
        analyses = []
        if request.include_reports:
            reports = await db.get_reports_by_visit_id(visit_id, doctor_uid)
            analyses = await db.get_ai_analyses_by_visit_id(visit_id, doctor_uid)
        
        # Get handwritten notes if requested
        handwritten_notes = None
        if request.include_handwritten:
            handwritten_notes = await db.get_handwritten_visit_notes_by_visit_id(visit_id, doctor_uid)
        
        # Generate SOAP note
        result = await ai_analysis_service.generate_visit_summary(
            patient_context=patient,
            visit_context=visit,
            reports=reports,
            analyses=analyses,
            doctor_context=current_doctor,
            handwritten_notes=handwritten_notes
        )
        
        if result.get("success"):
            # Store the summary
            summary_data = {
                "visit_id": visit_id,
                "patient_id": visit["patient_id"],
                "doctor_firebase_uid": doctor_uid,
                "subjective": result.get("soap_note", {}).get("subjective"),
                "objective": result.get("soap_note", {}).get("objective"),
                "assessment": result.get("soap_note", {}).get("assessment"),
                "plan": result.get("soap_note", {}).get("plan"),
                "soap_note_text": result.get("soap_note_text"),
                "icd10_codes": result.get("soap_note", {}).get("assessment", {}).get("icd10_codes", []),
                "cpt_codes": result.get("soap_note", {}).get("plan", {}).get("cpt_codes", []),
                "confidence_score": result.get("confidence_score"),
                "model_used": result.get("model_used")
            }
            
            saved_summary = await db.create_visit_summary(summary_data)
            
            return {
                "success": True,
                "message": "SOAP note generated successfully",
                "already_exists": False,
                "summary": saved_summary or result,
                "generated_at": result.get("generated_at")
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate SOAP note: {result.get('error')}"
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generating visit summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate visit summary"
        )

@app.get("/visits/{visit_id}/summary", response_model=dict, tags=["Clinical Intelligence"])
async def get_visit_summary(
    visit_id: int,
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Get existing visit summary (SOAP note) for a visit.
    
    **Path Parameters:**
    - **visit_id**: ID of the visit
    
    **Response:**
    - **summary**: The SOAP note data if exists
    - **exists**: Whether a summary exists
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        summary = await db.get_visit_summary(visit_id, doctor_uid)
        
        return {
            "success": True,
            "exists": summary is not None,
            "summary": summary
        }
    except Exception as e:
        print(f"Error getting visit summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get visit summary"
        )

@app.post("/visits/{visit_id}/summary/approve", response_model=dict, tags=["Clinical Intelligence"])
async def approve_visit_summary(
    visit_id: int,
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Approve a visit summary for final documentation.
    
    Marks the summary as reviewed and approved by the doctor.
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        # Get existing summary
        summary = await db.get_visit_summary(visit_id, doctor_uid)
        if not summary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit summary not found. Generate one first."
            )
        
        # Approve
        success = await db.approve_visit_summary(
            summary_id=summary["id"],
            approved_by=doctor_uid
        )
        
        if success:
            return {
                "success": True,
                "message": "Visit summary approved",
                "approved_at": datetime.now(timezone.utc).isoformat()
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to approve summary"
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error approving visit summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve visit summary"
        )

# -------------------------------------------------------------------------
# Patient Risk Scoring (Phase 2.4)
# -------------------------------------------------------------------------

@app.get("/patients/{patient_id}/risk-score", response_model=dict, tags=["Clinical Intelligence"])
async def get_patient_risk_score(
    patient_id: int,
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Get patient risk score.
    
    Phase 2.4: Patient Risk Scoring
    
    Returns the AI-calculated risk score for a patient, including:
    - Overall health risk score (0-100)
    - Category-specific scores (cardiovascular, diabetes, etc.)
    - Identified risk factors and protective factors
    - Recommendations for risk reduction
    
    **Path Parameters:**
    - **patient_id**: ID of the patient
    
    **Response:**
    - **risk_scores**: Risk score data if calculated
    - **exists**: Whether a risk score exists
    - **calculated_at**: When the score was calculated
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        risk_score = await db.get_patient_risk_score(patient_id, doctor_uid)
        
        return {
            "success": True,
            "patient_id": patient_id,
            "exists": risk_score is not None,
            "risk_scores": risk_score
        }
    except Exception as e:
        print(f"Error getting risk score: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get risk score"
        )

@app.post("/patients/{patient_id}/calculate-risk-score", response_model=dict, tags=["Clinical Intelligence"])
async def calculate_patient_risk_score(
    patient_id: int,
    request: RiskScoreRequest = RiskScoreRequest(),
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Calculate or recalculate patient risk score.
    
    Uses AI to analyze patient's complete medical data and calculate
    comprehensive risk scores.
    
    **Path Parameters:**
    - **patient_id**: ID of the patient
    
    **Query Parameters:**
    - **recalculate**: Force recalculation even if recent score exists
    - **include_all_visits**: Include all visits in analysis
    
    **Response:**
    - **risk_scores**: Calculated risk scores
    - **risk_factors**: Identified risk factors
    - **recommendations**: AI-generated recommendations
    """
    try:
        check_ai_enabled(current_doctor)
        doctor_uid = current_doctor["firebase_uid"]
        
        # Check for existing recent score
        if not request.recalculate:
            existing = await db.get_patient_risk_score(patient_id, doctor_uid)
            if existing:
                # Check if recent (within 24 hours)
                from datetime import timedelta
                calculated_at = existing.get("calculated_at", "")
                if calculated_at:
                    try:
                        calc_time = datetime.fromisoformat(calculated_at.replace("Z", "+00:00"))
                        if datetime.now(timezone.utc) - calc_time < timedelta(hours=24):
                            return {
                                "success": True,
                                "message": "Recent risk score exists",
                                "recalculated": False,
                                "risk_scores": existing
                            }
                    except:
                        pass
        
        # Get patient data
        patient = await db.get_patient_by_id(patient_id, doctor_uid)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Get visits and analyses
        visits = await db.get_visits_by_patient_id(patient_id, doctor_uid)
        analyses = await db.get_ai_analyses_by_patient_id(patient_id, doctor_uid)
        
        # Calculate risk score
        result = await ai_analysis_service.calculate_patient_risk_score(
            patient_context=patient,
            visits=visits,
            analyses=analyses,
            doctor_context=current_doctor
        )
        
        if result.get("success"):
            risk_scores = result.get("risk_scores", {})
            
            # Store the risk score
            risk_data = {
                "patient_id": patient_id,
                "doctor_firebase_uid": doctor_uid,
                "overall_risk_score": risk_scores.get("overall_risk_score"),
                "cardiovascular_risk": risk_scores.get("cardiovascular_risk"),
                "diabetes_risk": risk_scores.get("diabetes_risk"),
                "kidney_risk": risk_scores.get("kidney_risk"),
                "liver_risk": risk_scores.get("liver_risk"),
                "risk_factors": risk_scores.get("risk_factors", []),
                "protective_factors": risk_scores.get("protective_factors", []),
                "recommendations": risk_scores.get("recommendations", []),
                "confidence_score": risk_scores.get("confidence_score"),
                "visits_analyzed": result.get("visits_analyzed", len(visits)),
                "reports_analyzed": result.get("analyses_used", len(analyses))
            }
            
            saved = await db.create_or_update_risk_score(risk_data)
            
            return {
                "success": True,
                "message": "Risk score calculated successfully",
                "recalculated": True,
                "risk_scores": saved or risk_data,
                "calculated_at": datetime.now(timezone.utc).isoformat()
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to calculate risk score: {result.get('error')}"
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error calculating risk score: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to calculate risk score"
        )

@app.get("/patients/high-risk", response_model=dict, tags=["Clinical Intelligence"])
async def get_high_risk_patients(
    min_score: int = Query(default=70, ge=0, le=100, description="Minimum risk score"),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum results"),
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Get list of high-risk patients for the doctor.
    
    Returns patients with risk scores above the specified threshold,
    sorted by risk score (highest first).
    
    **Query Parameters:**
    - **min_score**: Minimum risk score threshold (default: 70)
    - **limit**: Maximum number of results (default: 50)
    
    **Response:**
    - **patients**: List of high-risk patients with scores
    - **count**: Number of high-risk patients
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        high_risk = await db.get_high_risk_patients(
            doctor_firebase_uid=doctor_uid,
            min_risk_score=min_score,
            limit=limit
        )
        
        return {
            "success": True,
            "patients": high_risk,
            "count": len(high_risk),
            "min_score": min_score
        }
    except Exception as e:
        print(f"Error getting high-risk patients: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get high-risk patients"
        )

# -------------------------------------------------------------------------
# Historical Trend Analysis (Phase 2.2)
# -------------------------------------------------------------------------

@app.get("/patients/{patient_id}/lab-trends", response_model=dict, tags=["Clinical Intelligence"])
async def get_patient_lab_trends(
    patient_id: int,
    parameters: Optional[str] = Query(default=None, description="Comma-separated parameter names"),
    months: int = Query(default=12, ge=1, le=60, description="Months of history"),
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Get historical lab value trends for a patient.
    
    Phase 2.2: Historical Trend Analysis
    
    Returns historical lab values grouped by parameter for trend analysis.
    Useful for tracking how values change over time.
    
    **Path Parameters:**
    - **patient_id**: ID of the patient
    
    **Query Parameters:**
    - **parameters**: Comma-separated list of specific parameters (optional)
    - **months**: Number of months of history (default: 12, max: 60)
    
    **Response:**
    - **trends**: Dict of parameter -> list of historical values
    - **parameters_found**: List of parameters with data
    """
    try:
        doctor_uid = current_doctor["firebase_uid"]
        
        # Parse parameters if provided
        param_list = None
        if parameters:
            param_list = [p.strip() for p in parameters.split(",") if p.strip()]
        
        # Try to get from historical_lab_values table first
        trends = await db.get_historical_lab_values(
            patient_id=patient_id,
            doctor_firebase_uid=doctor_uid,
            parameters=param_list,
            months_back=months
        )
        
        # If empty, try to extract from existing analyses
        if not trends:
            trends = await db.get_historical_lab_values_from_analyses(
                patient_id=patient_id,
                doctor_firebase_uid=doctor_uid,
                months_back=months
            )
        
        return {
            "success": True,
            "patient_id": patient_id,
            "trends": trends,
            "parameters_found": list(trends.keys()),
            "months_analyzed": months
        }
    except Exception as e:
        print(f"Error getting lab trends: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get lab trends"
        )

@app.post("/reports/{report_id}/analyze-with-trends", response_model=dict, tags=["Clinical Intelligence"])
async def analyze_report_with_trends(
    report_id: int,
    current_doctor: dict = Depends(get_current_doctor)
):
    """
    Analyze a report with historical trend context.
    
    Enhanced analysis that compares current values with historical
    data for better clinical decision support.
    
    **Path Parameters:**
    - **report_id**: ID of the report to analyze
    
    **Response:**
    - **analysis**: AI analysis with trend comparison
    - **trends_used**: Historical parameters included
    """
    try:
        check_ai_enabled(current_doctor)
        doctor_uid = current_doctor["firebase_uid"]
        
        # Get report
        report = await db.get_report_by_id(report_id, doctor_uid)
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report not found"
            )
        
        # Get visit and patient
        visit = await db.get_visit_by_id(report["visit_id"], doctor_uid)
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        patient = await db.get_patient_by_id(visit["patient_id"], doctor_uid)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Get historical values
        historical = await db.get_historical_lab_values_from_analyses(
            patient_id=visit["patient_id"],
            doctor_firebase_uid=doctor_uid,
            months_back=12
        )
        
        # Download report file
        file_content = await file_downloader.download_file_async(report["file_url"])
        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to download report file"
            )
        
        # Get case visit chain if applicable
        visit_chain = None
        if visit.get("case_id"):
            visit_chain = await db.get_visits_by_case(visit["case_id"], doctor_uid)
        
        # Perform analysis with trends
        result = await ai_analysis_service.analyze_with_historical_trends(
            file_content=file_content,
            file_name=report["file_name"],
            file_type=report["file_type"],
            patient_context=patient,
            visit_context=visit,
            doctor_context=current_doctor,
            historical_values=historical,
            visit_chain_context=visit_chain
        )
        
        if result.get("success"):
            return {
                "success": True,
                "analysis": result.get("analysis"),
                "historical_context_used": result.get("historical_context_used"),
                "parameters_with_history": result.get("parameters_with_history", []),
                "processed_at": result.get("processed_at")
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Analysis failed: {result.get('error')}"
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error analyzing report with trends: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to analyze report with trends"
        )

# ============================================================================
# END OF PHASE 2: CLINICAL INTELLIGENCE ENDPOINTS
# ============================================================================

@app.post("/patients/{patient_id}/analyze-comprehensive-history", response_model=dict)
async def analyze_patient_comprehensive_history(
    patient_id: int,
    request_data: PatientHistoryAnalysisRequest,
    current_doctor = Depends(get_current_doctor)
):
    """Generate comprehensive AI-powered analysis of complete patient history including all visits, reports, and medical journey
    
    OPTIMIZED: Reduced from 8 DB calls to 3 by fetching data once and reusing (60% fewer calls).
    """
    # Create a unique key for this patient + doctor combination
    analysis_key = f"analysis_{patient_id}_{current_doctor['firebase_uid']}"
    
    # Check if analysis is already in progress (prevent duplicate concurrent requests)
    if analysis_key in _analyses_in_progress:
        return {
            "message": "Analysis already in progress for this patient. Please wait for it to complete.",
            "already_in_progress": True,
            "analysis": None
        }
    
    # Mark analysis as in progress
    _analyses_in_progress.add(analysis_key)
    
    try:
        # Check if AI is enabled for this doctor
        check_ai_enabled(current_doctor)
        
        start_time = datetime.now()
        doctor_uid = current_doctor["firebase_uid"]
        
        # Verify the patient exists and belongs to the current doctor
        patient = await db.get_patient_by_id(patient_id, doctor_uid)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # OPTIMIZATION: Fetch visits and reports ONCE upfront, reuse throughout
        # This reduces 8 DB calls to 3 (patient, visits, reports)
        all_visits = []
        if request_data.include_visits:
            all_visits = await db.get_visits_by_patient_id(patient_id, doctor_uid)
        
        all_reports = []
        if request_data.include_reports:
            all_reports = await db.get_reports_by_patient_id(patient_id, doctor_uid)
        
        # Apply time period filter if specified
        visits = all_visits
        reports = all_reports
        if request_data.analysis_period_months:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=request_data.analysis_period_months * 30)
            cutoff_date_only = cutoff_date.date()
            visits = [v for v in all_visits if datetime.fromisoformat(v["visit_date"]).date() >= cutoff_date_only]
            reports = [r for r in all_reports if datetime.fromisoformat(r["uploaded_at"].replace('Z', '+00:00')) >= cutoff_date]
        
        current_visit_count = len(visits)
        current_report_count = len(reports)
        
        # Check if analysis already exists for this patient (check for recent analysis)
        existing_analysis = await db.get_latest_patient_history_analysis(patient_id, doctor_uid)
        
        # Clean up any outdated analyses (pass counts to avoid redundant fetches)
        await db.cleanup_outdated_patient_history_analyses(
            patient_id, doctor_uid, 
            current_visit_count=current_visit_count, 
            current_report_count=current_report_count
        )
        
        # Re-fetch after cleanup to get the most current analysis (if any)
        if existing_analysis:
            # Check if the analysis we had was cleaned up
            existing_analysis = await db.get_latest_patient_history_analysis(patient_id, doctor_uid)
        
        if existing_analysis:
            # Check if the analysis is recent (within last 24 hours)
            analyzed_at = datetime.fromisoformat(existing_analysis["analyzed_at"].replace('Z', '+00:00'))
            time_diff = datetime.now(timezone.utc) - analyzed_at
            
            # Check if the analysis data is still valid by comparing visit/report counts
            analysis_is_outdated = (
                existing_analysis.get("total_visits", 0) != current_visit_count or 
                existing_analysis.get("total_reports", 0) != current_report_count
            )
            
            # Return cached analysis only if it's recent AND data hasn't changed
            if time_diff.total_seconds() < 24 * 3600 and not analysis_is_outdated:
                return {
                    "message": "Recent comprehensive analysis already exists for this patient",
                    "analysis": PatientHistoryAnalysis(**existing_analysis),
                    "analysis_age_hours": time_diff.total_seconds() / 3600,
                    "already_exists": True
                }
            elif analysis_is_outdated:
                # Delete the outdated analysis to force regeneration
                await db.delete_patient_history_analysis(existing_analysis["id"], doctor_uid)
        
        # Get existing AI analyses for this patient
        existing_ai_analyses = await db.get_ai_analyses_by_patient_id(patient_id, current_doctor["firebase_uid"])
        
        # Get all handwritten notes for this patient
        handwritten_notes = await db.get_handwritten_visit_notes_by_patient_id(patient_id, current_doctor["firebase_uid"])
        print(f"📝 Found {len(handwritten_notes)} handwritten notes for patient {patient_id}")
        
        if not visits and not reports and not handwritten_notes:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No medical data found for this patient in the specified period"
            )
        
        # Download report files for comprehensive analysis using async non-blocking downloads
        report_documents = []
        
        if reports:
            # Use concurrent downloads to speed up multiple file downloads
            file_urls = [report["file_url"] for report in reports]
            downloaded_files = await file_downloader.download_multiple_files(
                urls=file_urls,
                concurrent_limit=5  # Download max 5 files at once
            )
            
            # Process downloaded files
            for report in reports:
                file_url = report["file_url"]
                file_content = downloaded_files.get(file_url)
                
                if file_content:
                    report_documents.append({
                        "content": file_content,
                        "file_name": report["file_name"],
                        "file_type": report["file_type"],
                        "test_type": report.get("test_type", "General Report"),
                        "uploaded_at": report["uploaded_at"],
                        "visit_id": report["visit_id"]
                    })
                else:
                    print(f"⚠️ Failed to download report {report['id']}")
        
        # Download handwritten note PDFs for analysis
        handwritten_documents = []
        if handwritten_notes:
            hw_urls = [note["handwritten_pdf_url"] for note in handwritten_notes if note.get("handwritten_pdf_url")]
            if hw_urls:
                hw_downloaded = await file_downloader.download_multiple_files(
                    urls=hw_urls,
                    concurrent_limit=5
                )
                for note in handwritten_notes:
                    hw_url = note.get("handwritten_pdf_url")
                    if hw_url and hw_url in hw_downloaded and hw_downloaded[hw_url]:
                        handwritten_documents.append({
                            "content": hw_downloaded[hw_url],
                            "file_name": note.get("handwritten_pdf_filename", "handwritten_note.pdf"),
                            "file_type": "application/pdf",
                            "visit_id": note.get("visit_id"),
                            "created_at": note.get("created_at")
                        })
                        print(f"✅ Downloaded handwritten note for visit {note.get('visit_id')}")
        
        print(f"📊 Comprehensive analysis data: {len(visits)} visits, {len(reports)} reports, {len(report_documents)} downloaded reports, {len(handwritten_documents)} handwritten notes")
        
        # Perform comprehensive patient history analysis
        analysis_result = await ai_analysis_service.analyze_patient_comprehensive_history(
            patient_context=patient,
            visits=visits,
            reports=report_documents,
            existing_analyses=existing_ai_analyses,
            handwritten_notes=handwritten_documents,
            doctor_context=current_doctor,
            analysis_period_months=request_data.analysis_period_months
        )
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Determine analysis period (initialize here to avoid UnboundLocalError)
        period_start = None
        period_end = None
        
        if request_data.analysis_period_months:
            period_end = datetime.now(timezone.utc).date().isoformat()
            period_start = (datetime.now(timezone.utc) - timedelta(days=request_data.analysis_period_months * 30)).date().isoformat()
        elif visits or reports:
            # Find the earliest and latest dates
            all_dates = []
            for visit in visits:
                # Visit date is a date string, so convert to datetime and then to date
                visit_date = datetime.fromisoformat(visit["visit_date"])
                if visit_date.tzinfo is None:
                    # If it's just a date, treat it as start of day UTC
                    visit_date = visit_date.replace(tzinfo=timezone.utc)
                all_dates.append(visit_date)
            for report in reports:
                # Report date is a datetime string with timezone
                report_date = datetime.fromisoformat(report["uploaded_at"].replace('Z', '+00:00'))
                all_dates.append(report_date)
            
            if all_dates:
                period_start = min(all_dates).date().isoformat()
                period_end = max(all_dates).date().isoformat()
        
        if analysis_result["success"]:
            # Store comprehensive analysis in database
            # Only save essential fields - raw_analysis contains everything
            # Frontend parses and formats the raw_analysis for display
            analysis_data = {
                "patient_id": patient_id,
                "doctor_firebase_uid": current_doctor["firebase_uid"],
                "analysis_period_start": period_start,
                "analysis_period_end": period_end,
                "total_visits": len(visits),
                "total_reports": len(reports),
                "model_used": "gemini-2.0-flash-exp",
                "confidence_score": analysis_result.get("confidence_score", 0.85),
                "raw_analysis": analysis_result["comprehensive_analysis"],
                "analysis_success": True,
                "analysis_error": None,
                "processing_time_ms": int(processing_time),
                "analyzed_at": analysis_result["processed_at"],
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            created_analysis = await db.create_patient_history_analysis(analysis_data)
            
            if created_analysis:
                return {
                    "message": "Comprehensive patient history analysis completed successfully",
                    "analysis": PatientHistoryAnalysis(**created_analysis),
                    "patient_name": f"{patient['first_name']} {patient['last_name']}",
                    "analysis_period": f"{period_start} to {period_end}" if period_start and period_end else "All available data",
                    "data_analyzed": {
                        "visits": len(visits),
                        "reports": len(reports),
                        "report_documents": len(report_documents),
                        "existing_ai_analyses": len(existing_ai_analyses)
                    },
                    "processing_time_ms": int(processing_time),
                    "already_exists": False
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to save comprehensive analysis results"
                )
        else:
            # Store failed analysis
            analysis_data = {
                "patient_id": patient_id,
                "doctor_firebase_uid": current_doctor["firebase_uid"],
                "analysis_period_start": period_start,
                "analysis_period_end": period_end,
                "total_visits": len(visits),
                "total_reports": len(reports),
                "model_used": "gemini-2.0-flash-exp",
                "confidence_score": 0.0,
                "raw_analysis": "",
                "analysis_success": False,
                "analysis_error": analysis_result["error"],
                "processing_time_ms": int(processing_time),
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            await db.create_patient_history_analysis(analysis_data)
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Comprehensive analysis failed: {analysis_result['error']}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in comprehensive patient history analysis: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to perform comprehensive patient history analysis"
        )
    finally:
        # Always remove the analysis key when done (success or failure)
        _analyses_in_progress.discard(analysis_key)

@app.get("/patients/{patient_id}/history-analysis", response_model=PatientHistoryAnalysis)
async def get_patient_history_analysis(
    patient_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get the latest comprehensive history analysis for a patient"""
    try:
        # Verify the patient exists and belongs to the current doctor
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        analysis = await db.get_latest_patient_history_analysis(patient_id, current_doctor["firebase_uid"])
        
        if not analysis:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No comprehensive history analysis found for this patient. Please generate one first."
            )
        
        return PatientHistoryAnalysis(**analysis)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching patient history analysis: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch patient history analysis"
        )

@app.get("/patients/{patient_id}/history-analyses", response_model=List[PatientHistoryAnalysis])
async def get_patient_history_analyses(
    patient_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get all comprehensive history analyses for a patient"""
    try:
        # Verify the patient exists and belongs to the current doctor
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        analyses = await db.get_patient_history_analyses(patient_id, current_doctor["firebase_uid"])
        return [PatientHistoryAnalysis(**analysis) for analysis in analyses]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching patient history analyses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch patient history analyses"
        )

@app.post("/patients/{patient_id}/cleanup-history-analyses", response_model=dict)
async def cleanup_patient_history_analyses(
    patient_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Clean up/delete all patient history analyses for a specific patient (for testing/debugging)"""
    try:
        success = await db.delete_patient_history_analyses_by_patient(patient_id, current_doctor["firebase_uid"])
        if success:
            return {
                "message": f"Successfully cleaned up all history analyses for patient {patient_id}",
                "patient_id": patient_id
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No analyses found to clean up"
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error cleaning up patient history analyses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clean up patient history analyses"
        )

@app.get("/patients/{patient_id}/history-analysis-debug", response_model=dict)
async def debug_patient_history_analysis(
    patient_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """DEBUG: Get raw analysis data directly from database"""
    try:
        analysis = await db.get_latest_patient_history_analysis(patient_id, current_doctor["firebase_uid"])
        
        if not analysis:
            return {
                "found": False,
                "message": "No analysis found in database",
                "patient_id": patient_id
            }
        
        return {
            "found": True,
            "analysis_id": analysis.get('id'),
            "patient_id": analysis.get('patient_id'),
            "analyzed_at": analysis.get('analyzed_at'),
            "total_visits": analysis.get('total_visits'),
            "total_reports": analysis.get('total_reports'),
            "analysis_success": analysis.get('analysis_success'),
            "raw_analysis_length": len(analysis.get('raw_analysis', '')),
            "raw_analysis_preview": analysis.get('raw_analysis', '')[:500],
            "comprehensive_summary_length": len(analysis.get('comprehensive_summary', '') or ''),
            "comprehensive_summary": analysis.get('comprehensive_summary'),
            "medical_trajectory": analysis.get('medical_trajectory'),
            "chronic_conditions": analysis.get('chronic_conditions'),
            "recommendations": analysis.get('recommendations'),
            "all_fields": list(analysis.keys())
        }
        
    except Exception as e:
        print(f"Error in debug endpoint: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }

# NOTE: Removed duplicate endpoint - use POST /patients/{patient_id}/cleanup-history-analyses defined earlier

@app.post("/cleanup-all-history-analyses", response_model=dict)
async def cleanup_all_patient_history_analyses(
    current_doctor = Depends(get_current_doctor)
):
    """Manually clean up all outdated comprehensive history analyses for the current doctor"""
    try:
        # Run cleanup for all patients
        cleanup_result = await db.cleanup_all_outdated_patient_history_analyses(current_doctor["firebase_uid"])
        
        return {
            "message": "Global cleanup completed successfully",
            "doctor_uid": current_doctor["firebase_uid"],
            "cleanup_success": cleanup_result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in global history analysis cleanup: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during global cleanup"
        )

# Notification Endpoints
@app.get(
    "/notifications", 
    response_model=List[Notification],
    tags=["Notifications"],
    summary="Get doctor notifications"
)
async def get_notifications(
    unread_only: bool = False,
    limit: int = 50,
    current_doctor = Depends(get_current_doctor)
):
    """Get notifications for the current doctor"""
    try:
        notifications = await db.get_doctor_notifications(
            current_doctor["firebase_uid"], 
            unread_only=unread_only, 
            limit=limit
        )
        
        return [Notification(**notification) for notification in notifications]
        
    except Exception as e:
        print(f"Error getting notifications: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get notifications"
        )

@app.get("/notifications/summary", response_model=NotificationSummary, tags=["Notifications"])
async def get_notification_summary(
    current_doctor = Depends(get_current_doctor)
):
    """Get notification summary with unread count and recent notifications"""
    try:
        # Get unread count
        unread_count = await db.get_unread_notification_count(current_doctor["firebase_uid"])
        
        # Get recent notifications (last 10)
        recent_notifications = await db.get_doctor_notifications(
            current_doctor["firebase_uid"], 
            unread_only=False, 
            limit=10
        )
        
        return NotificationSummary(
            total_unread=unread_count,
            recent_notifications=[Notification(**notification) for notification in recent_notifications]
        )
        
    except Exception as e:
        print(f"Error getting notification summary: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get notification summary"
        )

@app.get("/notifications/unread/count", response_model=dict, tags=["Notifications"])
async def get_unread_notification_count(
    current_doctor = Depends(get_current_doctor)
):
    """Get count of unread notifications"""
    try:
        unread_count = await db.get_unread_notification_count(current_doctor["firebase_uid"])
        
        return {
            "unread_count": unread_count,
            "doctor_uid": current_doctor["firebase_uid"]
        }
        
    except Exception as e:
        print(f"Error getting unread notification count: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get unread notification count"
        )

@app.put("/notifications/{notification_id}/read", response_model=dict, tags=["Notifications"])
async def mark_notification_as_read(
    notification_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Mark a specific notification as read"""
    try:
        success = await db.mark_notification_as_read(notification_id, current_doctor["firebase_uid"])
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found or not authorized"
            )
        
        return {
            "message": "Notification marked as read",
            "notification_id": notification_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error marking notification as read: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark notification as read"
        )

@app.put("/notifications/mark-all-read", response_model=dict, tags=["Notifications"])
async def mark_all_notifications_as_read(
    current_doctor = Depends(get_current_doctor)
):
    """Mark all notifications as read for the current doctor"""
    try:
        success = await db.mark_all_notifications_as_read(current_doctor["firebase_uid"])
        
        return {
            "message": "All notifications marked as read",
            "success": success,
            "doctor_uid": current_doctor["firebase_uid"]
        }
        
    except Exception as e:
        print(f"Error marking all notifications as read: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark all notifications as read"
        )

@app.delete("/notifications/{notification_id}", response_model=dict, tags=["Notifications"])
async def delete_notification(
    notification_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Delete a specific notification"""
    try:
        success = await db.delete_notification(notification_id, current_doctor["firebase_uid"])
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found or not authorized"
            )
        
        return {
            "message": "Notification deleted",
            "notification_id": notification_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting notification: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete notification"
        )

# Lab Management Endpoints
@app.post("/lab-contacts", response_model=dict)
async def create_lab_contact(
    lab_contact: LabContactCreate,
    current_doctor = Depends(get_current_doctor)
):
    """Create a new lab contact for the doctor"""
    try:
        if lab_contact.lab_type not in ["pathology", "radiology"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lab type must be either 'pathology' or 'radiology'"
            )
        
        lab_data = {
            "doctor_firebase_uid": current_doctor["firebase_uid"],
            "lab_type": lab_contact.lab_type,
            "lab_name": lab_contact.lab_name,
            "contact_phone": lab_contact.contact_phone,
            "contact_email": lab_contact.contact_email,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        created_contact = await db.create_lab_contact(lab_data)
        if not created_contact:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create lab contact"
            )
        
        return {
            "message": "Lab contact created successfully",
            "lab_contact": created_contact
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating lab contact: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create lab contact"
        )

@app.get("/lab-contacts", response_model=List[LabContact])
async def get_lab_contacts(
    lab_type: Optional[str] = None,
    active_only: bool = True,
    current_doctor = Depends(get_current_doctor)
):
    """Get lab contacts for the current doctor"""
    try:
        if lab_type and lab_type not in ["pathology", "radiology"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lab type must be either 'pathology' or 'radiology'"
            )
        
        contacts = await db.get_doctor_lab_contacts(
            current_doctor["firebase_uid"], 
            lab_type=lab_type, 
            active_only=active_only
        )
        
        return [LabContact(**contact) for contact in contacts]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting lab contacts: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get lab contacts"
        )

@app.put("/lab-contacts/{contact_id}", response_model=dict)
async def update_lab_contact(
    contact_id: int,
    lab_contact: LabContactUpdate,
    current_doctor = Depends(get_current_doctor)
):
    """Update a lab contact"""
    try:
        update_data = {key: value for key, value in lab_contact.dict().items() if value is not None}
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        success = await db.update_lab_contact(contact_id, current_doctor["firebase_uid"], update_data)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lab contact not found or not authorized"
            )
        
        return {
            "message": "Lab contact updated successfully",
            "contact_id": contact_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating lab contact: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update lab contact"
        )

@app.delete("/lab-contacts/{contact_id}", response_model=dict)
async def delete_lab_contact(
    contact_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Delete a lab contact"""
    try:
        success = await db.delete_lab_contact(contact_id, current_doctor["firebase_uid"])
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lab contact not found or not authorized"
            )
        
        return {
            "message": "Lab contact deleted successfully",
            "contact_id": contact_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting lab contact: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete lab contact"
        )

@app.post("/visits/{visit_id}/auto-create-lab-requests", response_model=dict)
async def auto_create_lab_requests_for_visit(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Automatically create lab report requests for a visit that has tests_recommended"""
    try:
        # Get visit details
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Check if visit has tests recommended
        if not visit.get("tests_recommended") or not visit["tests_recommended"].strip():
            return {
                "message": "No tests recommended for this visit",
                "lab_requests_created": 0,
                "lab_requests": []
            }
        
        # Get existing lab requests for this visit to avoid duplicates
        existing_requests = await db.get_lab_report_requests_by_visit_id(visit_id)
        existing_test_names = {req.get("test_name", "").lower().strip() for req in existing_requests}
        
        # Get doctor profile and patient details
        doctor_profile = await db.get_doctor_by_firebase_uid(current_doctor["firebase_uid"])
        patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
        
        if not doctor_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor profile not found"
            )
        
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        lab_requests_created = []
        
        # Parse the tests_recommended field
        tests_recommended = visit["tests_recommended"].strip()
        
        # Try different common delimiters to split tests
        test_list = []
        for delimiter in [',', ';', '\n', '|']:
            if delimiter in tests_recommended:
                test_list = [test.strip() for test in tests_recommended.split(delimiter)]
                break
        
        # If no delimiter found, treat as single test
        if not test_list:
            test_list = [tests_recommended]
        
        # Remove empty entries
        test_list = [test for test in test_list if test.strip()]
        
        # Automatically determine lab type based on test keywords
        pathology_keywords = ['blood', 'urine', 'stool', 'cbc', 'complete blood count', 'glucose', 'cholesterol', 'bilirubin', 'creatinine', 'urea', 'hemoglobin', 'culture', 'sensitivity', 'liver', 'kidney', 'thyroid', 'hormone', 'enzyme', 'protein', 'electrolyte', 'lipid', 'serum', 'plasma', 'wbc', 'rbc', 'platelet', 'hematocrit', 'biochemistry', 'microbiology', 'pathology', 'histopathology']
        radiology_keywords = ['xray', 'x-ray', 'ct', 'scan', 'mri', 'ultrasound', 'echo', 'mammogram', 'bone', 'chest', 'abdomen', 'pelvis', 'spine', 'brain', 'cardiac', 'doppler', 'angiogram', 'radiolog', 'imaging', 'sonography', 'ecg', 'ekg', 'fluoroscopy']
        
        skipped_tests = []
        
        for test_name in test_list:
            test_lower = test_name.lower().strip()
            
            # Skip if request already exists for this test
            if test_lower in existing_test_names:
                skipped_tests.append(f"{test_name} (already requested)")
                continue
            
            # Determine report type based on test keywords
            report_type = None
            if any(keyword in test_lower for keyword in pathology_keywords):
                report_type = "pathology"
            elif any(keyword in test_lower for keyword in radiology_keywords):
                report_type = "radiology"
            else:
                # Default to pathology for unknown tests
                report_type = "pathology"
            
            # Check if doctor has lab contact for this type
            lab_phone = None
            lab_name = None
            
            if report_type == "pathology" and doctor_profile.get("pathology_lab_phone"):
                lab_phone = doctor_profile.get("pathology_lab_phone")
                lab_name = doctor_profile.get("pathology_lab_name", "Pathology Lab")
            elif report_type == "radiology" and doctor_profile.get("radiology_lab_phone"):
                lab_phone = doctor_profile.get("radiology_lab_phone")
                lab_name = doctor_profile.get("radiology_lab_name", "Radiology Lab")
            
            # Create lab report request if lab contact exists
            if lab_phone:
                # Ensure we have a valid lab_contact_id from the table
                lab_contact_id = await db.ensure_lab_contact_exists(
                    current_doctor["firebase_uid"], 
                    lab_phone, 
                    lab_name, 
                    report_type
                )

                request_token = str(uuid.uuid4())
                request_data = {
                    "visit_id": visit_id,
                    "patient_id": visit["patient_id"],
                    "doctor_firebase_uid": current_doctor["firebase_uid"],
                    "lab_contact_id": lab_contact_id,
                    "patient_name": f"{patient['first_name']} {patient['last_name']}",
                    "report_type": report_type,
                    "test_name": test_name.strip(),
                    "instructions": f"Auto-generated request for test: {test_name.strip()}",
                    "status": "pending",
                    "request_token": request_token,
                    "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
                
                created_request = await db.create_lab_report_request(request_data)
                if created_request:
                    lab_requests_created.append({
                        "request_id": created_request["id"],
                        "test_name": test_name.strip(),
                        "report_type": report_type,
                        "lab_name": lab_name,
                        "lab_phone": lab_phone,
                        "request_token": request_token
                    })
                    print(f"Created lab request for {test_name} -> {lab_name} ({lab_phone})")
                else:
                    skipped_tests.append(f"{test_name} (creation failed)")
            else:
                skipped_tests.append(f"{test_name} (no {report_type} lab contact)")
        
        return {
            "message": f"Successfully created {len(lab_requests_created)} lab report requests",
            "visit_id": visit_id,
            "tests_recommended": tests_recommended,
            "lab_requests_created": len(lab_requests_created),
            "lab_requests": lab_requests_created,
            "skipped_tests": skipped_tests,
            "skipped_count": len(skipped_tests)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error auto-creating lab requests: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create lab requests"
        )

@app.post("/visits/{visit_id}/request-lab-report", response_model=dict)
async def request_lab_report(
    visit_id: int,
    report_type: str,  # "pathology" or "radiology"
    test_name: str,
    request: Request,
    instructions: Optional[str] = None,
    current_doctor = Depends(get_current_doctor)
):
    """Request a lab report upload for a visit using doctor's profile lab contacts"""
    try:
        if report_type not in ["pathology", "radiology"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Report type must be either 'pathology' or 'radiology'"
            )
        
        # Get visit details
        visit = await db.get_visit_by_id(visit_id)
        if not visit or visit["doctor_firebase_uid"] != current_doctor["firebase_uid"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found or not authorized"
            )
        
        # Get patient details
        patient = await db.get_patient_by_id(visit["patient_id"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Get doctor's lab contact info from profile
        doctor_profile = await db.get_doctor_by_firebase_uid(current_doctor["firebase_uid"])
        if not doctor_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor profile not found"
            )
        
        # Check if doctor has the required lab contact
        lab_phone = None
        lab_name = None
        
        if report_type == "pathology":
            lab_phone = doctor_profile.get("pathology_lab_phone")
            lab_name = doctor_profile.get("pathology_lab_name", "Pathology Lab")
        elif report_type == "radiology":
            lab_phone = doctor_profile.get("radiology_lab_phone") 
            lab_name = doctor_profile.get("radiology_lab_name", "Radiology Lab")
        
        if not lab_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No {report_type} lab contact configured in doctor profile. Please add {report_type} lab phone number in your profile settings."
            )
        
        # Generate unique request token
        import uuid
        request_token = str(uuid.uuid4())
        
        # Ensure we have a valid lab_contact_id from the table
        lab_contact_id = await db.ensure_lab_contact_exists(
            current_doctor["firebase_uid"], 
            lab_phone, 
            lab_name, 
            report_type
        )
        
        # Create lab report request
        request_data = {
            "visit_id": visit_id,
            "patient_id": visit["patient_id"],
            "doctor_firebase_uid": current_doctor["firebase_uid"],
            "lab_contact_id": lab_contact_id,
            "patient_name": f"{patient['first_name']} {patient['last_name']}",
            "report_type": report_type,
            "test_name": test_name,
            "instructions": instructions,
            "status": "pending",
            "request_token": request_token,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        created_request = await db.create_lab_report_request(request_data)
        if not created_request:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create lab report request"
            )
        
        # Generate upload URL for the lab
        base_url = str(request.base_url).rstrip('/')
        upload_url = f"{base_url}/lab-upload/{request_token}"
        
        return {
            "message": "Lab report request created successfully",
            "request_id": created_request["id"],
            "request_token": request_token,
            "upload_url": upload_url,
            "lab_contact": {
                "lab_name": lab_name,
                "lab_phone": lab_phone,
                "lab_type": report_type
            },
            "patient_name": f"{patient['first_name']} {patient['last_name']}",
            "test_name": test_name,
            "expires_at": request_data["expires_at"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating lab report request: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create lab report request"
        )

# Lab Login and Upload Endpoints (for lab technicians)
@app.post("/lab-login", response_model=dict)
async def lab_login(lab_login: LabLogin):
    """Simple phone-only login for lab technicians (internal app)"""
    try:
        # Check if phone number exists in lab contacts
        lab_contact = await db.get_lab_contact_by_phone(lab_login.phone)
        if not lab_contact:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lab contact not found or inactive"
            )
        
        # Direct login without OTP (since it's an internal app)
        # Generate session token
        import jwt
        session_token = jwt.encode(
            {
                "lab_contact_id": lab_contact.get("id"),
                "phone": lab_login.phone,
                "lab_name": lab_contact.get("lab_name"),
                "lab_type": lab_contact.get("lab_type"),
                "exp": datetime.now(timezone.utc) + timedelta(hours=8)
            },
            "lab-secret-key",  # In production, use a proper secret
            algorithm="HS256"
        )
        
        return {
            "message": "Login successful",
            "session_token": session_token,
            "lab_info": {
                "lab_name": lab_contact.get("lab_name", "Lab"),
                "lab_type": lab_contact.get("lab_type", "unknown"),
                "phone": lab_login.phone,
                "available_types": lab_contact.get("available_lab_types", [lab_contact.get("lab_type", "unknown")]),
                "source": lab_contact.get("source", "unknown")
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in lab login: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )

@app.get("/lab-dashboard/{phone}")
async def get_lab_dashboard(
    phone: str,
    status: Optional[str] = None
):
    """Get pending lab report requests for a lab contact (supports profile-based contacts)"""
    try:
        # Get lab contact info to show which types this contact handles
        lab_contact_info = await db.get_lab_contact_by_phone(phone)
        if not lab_contact_info:
            return {
                "message": "No lab contact found for this phone number",
                "phone": phone,
                "requests": [],
                "lab_contact_info": None
            }
        
        # Get lab report requests
        requests = await db.get_lab_report_requests_by_phone(phone, status)
        
        # Format the response with detailed info
        formatted_requests = []
        for req in requests:
            patient = req.get("patients") or {}
            visit = req.get("visits") or {}
            
            formatted_request = {
                "id": req.get("id"),
                "visit_id": req.get("visit_id"),
                "patient_id": req.get("patient_id"),
                "doctor_firebase_uid": req.get("doctor_firebase_uid"),
                "patient_name": req.get("patient_name", ""),
                "report_type": req.get("report_type", ""),
                "test_name": req.get("test_name", ""),
                "instructions": req.get("instructions"),
                "status": req.get("status", "pending"),
                "request_token": req.get("request_token", ""),
                "expires_at": req.get("expires_at", ""),
                "created_at": req.get("created_at", ""),
                "patient_phone": patient.get("phone") if isinstance(patient, dict) else None,
                "visit_date": visit.get("visit_date") if isinstance(visit, dict) else None,
                "visit_type": visit.get("visit_type") if isinstance(visit, dict) else None,
                "chief_complaint": visit.get("chief_complaint") if isinstance(visit, dict) else None,
                "contact_source": req.get("contact_source", "unknown")
            }
            formatted_requests.append(formatted_request)
        
        return {
            "lab_contact_info": lab_contact_info,
            "phone": phone,
            "total_requests": len(formatted_requests),
            "pending_count": len([r for r in formatted_requests if r["status"] == "pending"]),
            "requests": formatted_requests,
            "message": f"Found {len(formatted_requests)} requests" if formatted_requests else "No requests found yet. Doctor may need to create lab requests for visits."
        }
        
    except Exception as e:
        print(f"Error getting lab dashboard: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get lab dashboard"
        )
# Debug upload and alternative lab-upload endpoints removed.
# Use `/api/lab-upload-reports` for lab uploads and the lab dashboard endpoints for lab workflows.

@app.post("/api/lab-upload-reports", response_model=dict)
async def lab_upload_reports(
    request: Request
):
    """Handle lab report file uploads with flexible form handling"""
    try:
        # Parse form data manually for more flexibility
        form = await request.form()
        
        # Get request token
        request_token = form.get("request_token")
        notes = form.get("notes", "")
        
        print(f"Lab upload - Token: {request_token}, Form keys: {list(form.keys())}")
        
        if not request_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request token is required"
            )
        
        # Get files from form
        files = []
        for key, value in form.items():
            if hasattr(value, 'filename') and value.filename:
                files.append(value)
                print(f"Found file: {value.filename}")
        
        if not files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No files provided"
            )
        
        # Get and validate request
        request_data = await db.get_lab_report_request_by_token(request_token)
        if not request_data:
            print(f"Invalid token: {request_token}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid request token"
            )
        
        # Check if request has expired
        expires_at = datetime.fromisoformat(request_data["expires_at"].replace('Z', '+00:00'))
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Upload request has expired"
            )
        
        uploaded_files = []
        loop = asyncio.get_event_loop()
        
        print(f"About to process {len(files)} files")
        
        for i, file in enumerate(files):
            print(f"Processing file {i+1}/{len(files)}: {getattr(file, 'filename', 'NO_FILENAME')}")
            
            if not hasattr(file, 'filename'):
                print(f"  ❌ File {i} has no filename attribute")
                continue
                
            if not file.filename:
                print(f"  ❌ File {i} has empty filename")
                continue
                
            print(f"  ✅ Valid file: {file.filename}")
            
            # Read file content
            file_content = await file.read()
            file_size = len(file_content)
            
            print(f"  File size: {file_size} bytes")
            
            # Validate file size (10MB limit)
            if file_size > 10 * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File {file.filename} is too large. Maximum size is 10MB."
                )
            
            # Skip empty files
            if file_size == 0:
                print(f"  ⚠️  Skipping empty file: {file.filename}")
                continue
            
            print(f"  ✅ File is valid, proceeding with upload...")
            
            # Generate unique filename
            file_extension = file.filename.split('.')[-1] if '.' in file.filename else ''
            unique_filename = f"{uuid.uuid4()}.{file_extension}" if file_extension else str(uuid.uuid4())
            
            # Upload to same reports folder structure as regular uploads
            try:
                bucket_path = f"reports/visit_{request_data['visit_id']}/{unique_filename}"
                
                # Upload to storage. The Supabase storage API may return a coroutine or a sync result
                upload_result = supabase.storage.from_("medical-reports").upload(
                    path=bucket_path,
                    file=file_content,
                    file_options={
                        "content-type": file.content_type or "application/octet-stream",
                        "x-upsert": "false"
                    }
                )
                if asyncio.iscoroutine(upload_result):
                    upload_result = await upload_result
                
                def _extract_storage_url(result):
                    if isinstance(result, str):
                        return result
                    if isinstance(result, dict):
                        data = result.get("data") if isinstance(result.get("data"), dict) else None
                        for key in ("publicUrl", "publicURL", "signedUrl", "signedURL"):
                            if key in result:
                                return result[key]
                            if data and key in data:
                                return data[key]
                    return None

                url_result = supabase.storage.from_("medical-reports").get_public_url(bucket_path)
                if asyncio.iscoroutine(url_result):
                    url_result = await url_result
                file_url = _extract_storage_url(url_result)

                if not file_url:
                    signed_result = supabase.storage.from_("medical-reports").create_signed_url(
                        bucket_path,
                        60 * 60 * 24 * 7
                    )
                    if asyncio.iscoroutine(signed_result):
                        signed_result = await signed_result
                    file_url = _extract_storage_url(signed_result)

                if not file_url:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to generate public URL for uploaded file"
                    )

                print(f"Lab file uploaded to reports folder: {file.filename} -> {bucket_path}")
            except Exception as storage_error:
                print(f"Error uploading to storage: {storage_error}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to upload file: {str(storage_error)}"
                )
                
            # Create a temporary upload token for lab uploads to satisfy foreign key constraint
            lab_upload_token = str(uuid.uuid4())

            # Resolve/validate doctor UID to avoid FK constraint failures.
            requested_doctor_uid = request_data.get("doctor_firebase_uid")
            resolved_doctor_uid = requested_doctor_uid

            valid_doctor = None
            if requested_doctor_uid:
                valid_doctor = await db.get_doctor_by_firebase_uid(requested_doctor_uid)

            if not valid_doctor:
                # Try to resolve via the lab contact nested in the request
                lab_contact = request_data.get("lab_contacts") or {}
                contact_phone = lab_contact.get("contact_phone")
                if contact_phone:
                    lab_info = await db.get_lab_contact_by_phone(contact_phone)
                    if lab_info and lab_info.get("doctor_firebase_uid"):
                        candidate_uid = lab_info.get("doctor_firebase_uid")
                        cand = await db.get_doctor_by_firebase_uid(candidate_uid)
                        if cand:
                            resolved_doctor_uid = candidate_uid
                            print(f"Resolved doctor UID via lab contact: {resolved_doctor_uid}")
                        else:
                            print(f"Lab contact returned doctor UID {candidate_uid} but no doctor record exists")
                if not resolved_doctor_uid:
                    print("Warning: Could not resolve a valid doctor UID for report upload; insert may fail due to FK constraints.")

            # Create temporary upload link for lab uploads (use resolved_doctor_uid)
            link_data = {
                "visit_id": request_data["visit_id"],
                "patient_id": request_data["patient_id"],
                "doctor_firebase_uid": resolved_doctor_uid,
                "upload_token": lab_upload_token,
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            }

            await db.create_report_upload_link(link_data)
            print(f"Created temporary upload link for lab upload: {lab_upload_token}")

            # Create report record using the same structure as regular uploads
            report_data = {
                "visit_id": request_data["visit_id"],
                "patient_id": request_data["patient_id"],
                "doctor_firebase_uid": resolved_doctor_uid,
                "file_name": file.filename,
                "file_size": file_size,
                "file_type": file.content_type or "application/octet-stream",
                "file_url": file_url,
                "storage_path": bucket_path,
                "test_type": f"Lab {request_data['report_type'].title()} - {request_data['test_name']}",
                "notes": notes,
                "upload_token": lab_upload_token,  # Use temporary upload token for lab uploads
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            }

            created_report = await db.create_report_direct(report_data)
            if created_report:
                uploaded_files.append({
                    "file_name": file.filename,
                    "file_size": file_size,
                    "file_type": file.content_type or "application/octet-stream",
                    "file_url": file_url,
                    "storage_path": bucket_path,
                    "test_type": f"Lab {request_data['report_type'].title()} - {request_data['test_name']}",
                    "report_id": created_report["id"]
                })
                print(f"Lab report saved to main reports table: {file.filename}")
                
                # Update the lab request status to completed
                await db.update_lab_report_request_status(
                    request_data["id"], 
                    "completed", 
                    created_report["id"]
                )
                
                # Create notification for the doctor
                try:
                    lab_contact = request_data.get("lab_contacts", {})
                    notification_data = {
                        "doctor_firebase_uid": request_data["doctor_firebase_uid"],
                        "title": "Lab Report Uploaded",
                        "message": f"Lab has uploaded {request_data['test_name']} report for {request_data['patient_name']}",
                        "notification_type": "lab_report_upload",
                        "priority": 1,
                        "is_read": False,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "metadata": {
                            "report_id": created_report["id"],
                            "visit_id": request_data["visit_id"],
                            "patient_id": request_data["patient_id"],
                            "patient_name": request_data["patient_name"],
                            "test_name": request_data["test_name"],
                            "file_name": file.filename
                        }
                    }
                    
                    await db.create_notification(notification_data)
                except Exception as notification_error:
                    print(f"Failed to create notification: {notification_error}")
                    # Don't fail the upload if notification fails
                    await db.create_notification(notification_data)
                except Exception as notification_error:
                    print(f"Failed to create notification: {notification_error}")
                    # Don't fail the upload if notification fails
        
        # Return success response
        return {
            "message": f"Successfully uploaded {len(uploaded_files)} file(s) to reports folder",
            "uploaded_files": uploaded_files,
            "upload_count": len(uploaded_files)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error uploading lab reports: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload lab reports"
        )

# ============================================================
# CASE/EPISODE OF CARE ENDPOINTS
# ============================================================

@app.post("/patients/{patient_id}/cases", response_model=CaseResponse, tags=["Cases"])
async def create_patient_case(
    patient_id: int,
    case_data: CaseCreate,
    current_doctor = Depends(get_current_doctor)
):
    """
    Create a new case/episode of care for a patient.
    A case groups related visits for a specific medical problem.
    """
    try:
        # Verify patient belongs to doctor
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        case = await db.create_case(
            patient_id=patient_id,
            doctor_firebase_uid=current_doctor["firebase_uid"],
            case_data=case_data.model_dump()
        )
        
        if not case:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create case"
            )
        
        return case
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating case: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create case: {str(e)}"
        )

@app.get("/patients/{patient_id}/cases", response_model=List[CaseSummary], tags=["Cases"])
async def get_patient_cases(
    patient_id: int,
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status: active, resolved, ongoing, etc."),
    include_resolved: bool = Query(True, description="Include resolved/closed cases"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_doctor = Depends(get_current_doctor)
):
    """
    Get all cases for a patient.
    """
    try:
        # Verify patient belongs to doctor
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        cases = await db.get_cases_by_patient(
            patient_id=patient_id,
            doctor_firebase_uid=current_doctor["firebase_uid"],
            status=status_filter,
            include_resolved=include_resolved,
            limit=limit,
            offset=offset
        )
        
        # Add helper fields for before/after photo status
        result = []
        for case in cases:
            photos = await db.get_case_photos(case["id"], current_doctor["firebase_uid"])
            has_before = any(p["photo_type"] == "before" for p in photos)
            has_after = any(p["photo_type"] == "after" for p in photos)
            
            result.append({
                **case,
                "has_before_photo": has_before,
                "has_after_photo": has_after
            })
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting patient cases: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get cases: {str(e)}"
        )

@app.get("/cases/active", response_model=List[dict], tags=["Cases"])
async def get_active_cases(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_doctor = Depends(get_current_doctor)
):
    """
    Get all active cases for the current doctor across all patients.
    """
    try:
        cases = await db.get_active_cases_by_doctor(
            doctor_firebase_uid=current_doctor["firebase_uid"],
            limit=limit,
            offset=offset
        )
        return cases
    except Exception as e:
        print(f"Error getting active cases: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get active cases: {str(e)}"
        )

@app.get("/cases/{case_id}", response_model=CaseResponse, tags=["Cases"])
async def get_case(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Get a case by ID.
    """
    try:
        case = await db.get_case_by_id(case_id, current_doctor["firebase_uid"])
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found"
            )
        return case
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting case: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get case: {str(e)}"
        )

@app.get("/cases/{case_id}/details", response_model=CaseWithDetails, tags=["Cases"])
async def get_case_with_details(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Get a case with all related data including visits, photos, reports, and latest analysis.
    """
    try:
        case_details = await db.get_case_with_details(case_id, current_doctor["firebase_uid"])
        if not case_details:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found"
            )
        return case_details
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting case details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get case details: {str(e)}"
        )

@app.put("/cases/{case_id}", response_model=CaseResponse, tags=["Cases"])
async def update_case(
    case_id: int,
    update_data: CaseUpdate,
    current_doctor = Depends(get_current_doctor)
):
    """
    Update a case.
    """
    try:
        case = await db.update_case(
            case_id=case_id,
            doctor_firebase_uid=current_doctor["firebase_uid"],
            update_data=update_data.model_dump(exclude_none=True)
        )
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found or update failed"
            )
        return case
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating case: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update case: {str(e)}"
        )

@app.post("/cases/{case_id}/resolve", response_model=CaseResponse, tags=["Cases"])
async def resolve_case(
    case_id: int,
    resolve_data: CaseResolve,
    current_doctor = Depends(get_current_doctor)
):
    """
    Resolve/close a case with outcome information.
    """
    try:
        case = await db.resolve_case(
            case_id=case_id,
            doctor_firebase_uid=current_doctor["firebase_uid"],
            outcome=resolve_data.outcome.value,
            final_diagnosis=resolve_data.final_diagnosis,
            outcome_notes=resolve_data.outcome_notes,
            patient_satisfaction=resolve_data.patient_satisfaction
        )
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found or resolve failed"
            )
        return case
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error resolving case: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve case: {str(e)}"
        )

@app.delete("/cases/{case_id}", response_model=dict, tags=["Cases"])
async def delete_case(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Delete a case. Soft deletes if visits exist, hard deletes if no visits.
    """
    try:
        success = await db.delete_case(case_id, current_doctor["firebase_uid"])
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found"
            )
        return {"message": "Case deleted successfully", "case_id": case_id}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting case: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete case: {str(e)}"
        )

@app.get("/cases/{case_id}/timeline", response_model=CaseTimeline, tags=["Cases"])
async def get_case_timeline(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Get a chronological timeline of all events for a case.
    """
    try:
        timeline = await db.get_case_timeline(case_id, current_doctor["firebase_uid"])
        if timeline.get("error") == "Case not found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found"
            )
        return timeline
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting case timeline: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get case timeline: {str(e)}"
        )

# ============================================================
# CASE PHOTOS ENDPOINTS
# ============================================================

@app.post("/cases/{case_id}/photos", response_model=CasePhotoResponse, tags=["Case Photos"])
async def upload_case_photo(
    case_id: int,
    file: UploadFile = File(...),
    photo_type: str = Form(..., description="before, progress, or after"),
    body_part: Optional[str] = Form(None),
    body_part_detail: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    clinical_notes: Optional[str] = Form(None),
    photo_taken_at: Optional[str] = Form(None),
    is_primary: bool = Form(False),
    visit_id: Optional[int] = Form(None),
    current_doctor = Depends(get_current_doctor)
):
    """
    Upload a photo to a case. Supports before, progress, and after photos.
    """
    try:
        # Verify case exists
        case = await db.get_case_by_id(case_id, current_doctor["firebase_uid"])
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found"
            )
        
        # Validate photo_type
        if photo_type not in ["before", "progress", "after"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="photo_type must be 'before', 'progress', or 'after'"
            )
        
        # Validate file type
        allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type {file.content_type} not allowed. Allowed types: {allowed_types}"
            )
        
        # Read file content
        content = await file.read()
        file_size = len(content)
        
        # Generate unique filename
        file_ext = file.filename.split('.')[-1] if '.' in file.filename else 'jpg'
        unique_filename = f"case_{case_id}_{photo_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.{file_ext}"
        
        # Upload to Firebase Storage
        storage_path = f"case_photos/{current_doctor['firebase_uid']}/{case['patient_id']}/{case_id}/{unique_filename}"
        
        # Get Firebase bucket
        bucket = firebase_admin.storage.bucket()
        blob = bucket.blob(storage_path)
        blob.upload_from_string(content, content_type=file.content_type)
        blob.make_public()
        file_url = blob.public_url
        
        # Create photo record
        photo_data = {
            "photo_type": photo_type,
            "file_name": file.filename,
            "file_url": file_url,
            "file_size": file_size,
            "file_type": file.content_type,
            "storage_path": storage_path,
            "body_part": body_part,
            "body_part_detail": body_part_detail,
            "description": description,
            "clinical_notes": clinical_notes,
            "photo_taken_at": photo_taken_at,
            "is_primary": is_primary,
            "visit_id": visit_id
        }
        
        photo = await db.add_case_photo(
            case_id=case_id,
            doctor_firebase_uid=current_doctor["firebase_uid"],
            photo_data=photo_data
        )
        
        if not photo:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save photo record"
            )
        
        return photo
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error uploading case photo: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload photo: {str(e)}"
        )

@app.get("/cases/{case_id}/photos", response_model=List[CasePhotoResponse], tags=["Case Photos"])
async def get_case_photos(
    case_id: int,
    photo_type: Optional[str] = Query(None, description="Filter by type: before, progress, after"),
    current_doctor = Depends(get_current_doctor)
):
    """
    Get all photos for a case, optionally filtered by type.
    """
    try:
        # Verify case exists
        case = await db.get_case_by_id(case_id, current_doctor["firebase_uid"])
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found"
            )
        
        photos = await db.get_case_photos(
            case_id=case_id,
            doctor_firebase_uid=current_doctor["firebase_uid"],
            photo_type=photo_type
        )
        
        return photos
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting case photos: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get photos: {str(e)}"
        )

@app.get("/cases/{case_id}/before-after", response_model=BeforeAfterComparison, tags=["Case Photos"])
async def get_before_after_comparison(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Get before and after photos for comparison.
    Returns primary before/after photos plus all photos of each type.
    """
    try:
        # Verify case exists
        case = await db.get_case_by_id(case_id, current_doctor["firebase_uid"])
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found"
            )
        
        comparison = await db.get_before_after_photos(
            case_id=case_id,
            doctor_firebase_uid=current_doctor["firebase_uid"]
        )
        
        # Calculate days between if both before and after exist
        days_between = None
        if comparison.get("before_photo") and comparison.get("after_photo"):
            try:
                before_date = comparison["before_photo"].get("photo_taken_at") or comparison["before_photo"]["uploaded_at"]
                after_date = comparison["after_photo"].get("photo_taken_at") or comparison["after_photo"]["uploaded_at"]
                from datetime import datetime as dt
                before_dt = dt.fromisoformat(before_date.replace("Z", "+00:00"))
                after_dt = dt.fromisoformat(after_date.replace("Z", "+00:00"))
                days_between = (after_dt - before_dt).days
            except:
                pass
        
        return {
            "case_id": case_id,
            "case_title": case["case_title"],
            "case_status": case["status"],
            "body_part": case.get("body_parts_affected", [None])[0] if case.get("body_parts_affected") else None,
            **comparison,
            "days_between": days_between
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting before/after comparison: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get comparison: {str(e)}"
        )

@app.put("/cases/{case_id}/photos/{photo_id}", response_model=CasePhotoResponse, tags=["Case Photos"])
async def update_case_photo(
    case_id: int,
    photo_id: int,
    body_part: Optional[str] = None,
    body_part_detail: Optional[str] = None,
    description: Optional[str] = None,
    clinical_notes: Optional[str] = None,
    photo_taken_at: Optional[str] = None,
    current_doctor = Depends(get_current_doctor)
):
    """
    Update case photo metadata.
    """
    try:
        update_data = {
            "body_part": body_part,
            "body_part_detail": body_part_detail,
            "description": description,
            "clinical_notes": clinical_notes,
            "photo_taken_at": photo_taken_at
        }
        
        photo = await db.update_case_photo(
            photo_id=photo_id,
            doctor_firebase_uid=current_doctor["firebase_uid"],
            update_data=update_data
        )
        
        if not photo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Photo not found"
            )
        
        return photo
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating case photo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update photo: {str(e)}"
        )

@app.post("/cases/{case_id}/photos/{photo_id}/set-primary", response_model=dict, tags=["Case Photos"])
async def set_primary_photo(
    case_id: int,
    photo_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Set a photo as the primary photo for its type within the case.
    """
    try:
        success = await db.set_primary_photo(
            case_id=case_id,
            photo_id=photo_id,
            doctor_firebase_uid=current_doctor["firebase_uid"]
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Photo not found or doesn't belong to this case"
            )
        
        return {"message": "Primary photo set successfully", "photo_id": photo_id}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error setting primary photo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set primary photo: {str(e)}"
        )

@app.delete("/cases/{case_id}/photos/{photo_id}", response_model=dict, tags=["Case Photos"])
async def delete_case_photo(
    case_id: int,
    photo_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Delete a case photo.
    """
    try:
        # Get photo to get storage path
        photo = await db.get_case_photo_by_id(photo_id, current_doctor["firebase_uid"])
        if not photo or photo["case_id"] != case_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Photo not found"
            )
        
        # Delete from storage
        if photo.get("storage_path"):
            try:
                bucket = firebase_admin.storage.bucket()
                blob = bucket.blob(photo["storage_path"])
                blob.delete()
            except Exception as storage_error:
                print(f"Warning: Could not delete from storage: {storage_error}")
        
        # Delete record
        success = await db.delete_case_photo(photo_id, current_doctor["firebase_uid"])
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete photo"
            )
        
        return {"message": "Photo deleted successfully", "photo_id": photo_id}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting case photo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete photo: {str(e)}"
        )

# ============================================================
# VISIT-CASE RELATIONSHIP ENDPOINTS
# ============================================================

@app.post("/visits/{visit_id}/assign-to-case", response_model=dict, tags=["Cases"])
async def assign_visit_to_case(
    visit_id: int,
    assignment: AssignVisitToCase,
    current_doctor = Depends(get_current_doctor)
):
    """
    Assign a visit to a case/episode of care.
    """
    try:
        visit = await db.assign_visit_to_case(
            visit_id=visit_id,
            case_id=assignment.case_id,
            doctor_firebase_uid=current_doctor["firebase_uid"],
            is_case_opener=assignment.is_case_opener
        )
        
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit or case not found"
            )
        
        return {
            "message": "Visit assigned to case successfully",
            "visit_id": visit_id,
            "case_id": assignment.case_id,
            "is_case_opener": assignment.is_case_opener
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error assigning visit to case: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to assign visit to case: {str(e)}"
        )

@app.post("/visits/{visit_id}/remove-from-case", response_model=dict, tags=["Cases"])
async def remove_visit_from_case(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Remove a visit from its case.
    """
    try:
        visit = await db.remove_visit_from_case(
            visit_id=visit_id,
            doctor_firebase_uid=current_doctor["firebase_uid"]
        )
        
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        return {
            "message": "Visit removed from case successfully",
            "visit_id": visit_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error removing visit from case: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove visit from case: {str(e)}"
        )

@app.get("/cases/{case_id}/visits", response_model=List[dict], tags=["Cases"])
async def get_case_visits(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Get all visits for a case.
    """
    try:
        case = await db.get_case_by_id(case_id, current_doctor["firebase_uid"])
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found"
            )
        
        visits = await db.get_visits_by_case(case_id, current_doctor["firebase_uid"])
        return visits
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting case visits: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get case visits: {str(e)}"
        )

# ============================================================
# CASE ANALYSIS ENDPOINTS
# ============================================================

@app.get("/cases/{case_id}/analyses", response_model=List[CaseAnalysisResponse], tags=["Case Analysis"])
async def get_case_analyses(
    case_id: int,
    limit: int = Query(10, ge=1, le=50),
    current_doctor = Depends(get_current_doctor)
):
    """
    Get all AI analyses for a case.
    """
    try:
        case = await db.get_case_by_id(case_id, current_doctor["firebase_uid"])
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found"
            )
        
        analyses = await db.get_case_analyses(
            case_id=case_id,
            doctor_firebase_uid=current_doctor["firebase_uid"],
            limit=limit
        )
        return analyses
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting case analyses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get analyses: {str(e)}"
        )

@app.get("/cases/{case_id}/latest-analysis", response_model=Optional[CaseAnalysisResponse], tags=["Case Analysis"])
async def get_latest_case_analysis(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Get the most recent AI analysis for a case.
    """
    try:
        case = await db.get_case_by_id(case_id, current_doctor["firebase_uid"])
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found"
            )
        
        analysis = await db.get_latest_case_analysis(
            case_id=case_id,
            doctor_firebase_uid=current_doctor["firebase_uid"]
        )
        
        return analysis  # Can be None if no analysis exists
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting latest case analysis: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get latest analysis: {str(e)}"
        )

@app.post("/cases/{case_id}/analyze", response_model=CaseAnalysisResponse, tags=["Case Analysis"])
async def analyze_case(
    case_id: int,
    request: CaseAnalysisRequest,
    current_doctor = Depends(get_current_doctor)
):
    """
    Trigger AI analysis for a case. Analyzes all visits, reports, and photos.
    If the case already has an analysis, returns the existing one unless force_reanalyze is set.
    """
    try:
        if not ai_analysis_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI analysis service is not available"
            )
        
        # Check if case already has an analysis (unless force_reanalyze is requested)
        if not getattr(request, 'force_reanalyze', False):
            existing_analysis = await db.get_latest_case_analysis(case_id, current_doctor["firebase_uid"])
            if existing_analysis and existing_analysis.get("analysis_success"):
                print(f"Returning existing analysis for case {case_id}")
                return existing_analysis
        
        # Get case with all related data
        case_details = await db.get_case_with_details(case_id, current_doctor["firebase_uid"])
        if not case_details:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found"
            )
        
        # Get patient context
        patient = await db.get_patient_by_id(case_details["patient_id"], current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Build patient context
        patient_context = {
            "full_name": patient.get("full_name", "Unknown"),
            "age": patient.get("age", "Unknown"),
            "gender": patient.get("gender", "Unknown"),
            "blood_group": patient.get("blood_group", "Unknown"),
            "allergies": patient.get("allergies", "None known"),
            "chronic_conditions": patient.get("chronic_conditions", "None known"),
            "current_medications": patient.get("current_medications", "None")
        }
        
        # Build doctor context
        doctor_context = {
            "name": current_doctor.get("full_name", "Doctor"),
            "specialization": current_doctor.get("specialization", "General")
        }
        
        # Get photos if requested
        photos = []
        if request.include_photos:
            photos = case_details.get("photos", [])
        
        # Get reports if requested
        reports = []
        if request.include_reports:
            reports = case_details.get("reports", [])
        
        # Run AI analysis
        analysis_result = await ai_analysis_service.analyze_case(
            case_data=case_details,
            visits=case_details.get("visits", []),
            photos=photos,
            reports=reports,
            patient_context=patient_context,
            doctor_context=doctor_context,
            analysis_type=request.analysis_type
        )
        
        if not analysis_result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Analysis failed: {analysis_result.get('error', 'Unknown error')}"
            )
        
        # Save analysis to database
        saved_analysis = await db.create_case_analysis(
            case_id=case_id,
            patient_id=case_details["patient_id"],
            doctor_firebase_uid=current_doctor["firebase_uid"],
            analysis_data=analysis_result
        )
        
        if not saved_analysis:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save analysis results"
            )
        
        return saved_analysis
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error analyzing case: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze case: {str(e)}"
        )

@app.post("/cases/{case_id}/compare-photos", response_model=dict, tags=["Case Analysis"])
async def compare_case_photos(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """
    Compare before and after photos for a case using AI.
    """
    try:
        if not ai_analysis_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI analysis service is not available"
            )
        
        # Get case
        case = await db.get_case_by_id(case_id, current_doctor["firebase_uid"])
        if not case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found"
            )
        
        # Get before/after photos
        comparison = await db.get_before_after_photos(case_id, current_doctor["firebase_uid"])
        
        if not comparison.get("before_photo") or not comparison.get("after_photo"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Need both before and after photos for comparison"
            )
        
        # Get patient for context
        patient = await db.get_patient_by_id(case["patient_id"], current_doctor["firebase_uid"])
        patient_context = {
            "age": patient.get("age", "Unknown") if patient else "Unknown",
            "gender": patient.get("gender", "Unknown") if patient else "Unknown"
        }
        
        # Run photo comparison
        result = await ai_analysis_service.analyze_photos_comparison(
            before_photo_url=comparison["before_photo"]["file_url"],
            after_photo_url=comparison["after_photo"]["file_url"],
            case_context=case,
            patient_context=patient_context
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Photo comparison failed: {result.get('error', 'Unknown error')}"
            )
        
        # Update photos with AI analysis
        if result.get("visual_improvement_score"):
            await db.update_case_photo(
                photo_id=comparison["after_photo"]["id"],
                doctor_firebase_uid=current_doctor["firebase_uid"],
                update_data={
                    "ai_improvement_score": result["visual_improvement_score"],
                    "ai_detected_changes": result.get("analysis", {}).get("comparison_summary", {}).get("overall_change"),
                    "comparison_pair_id": comparison["before_photo"]["id"]
                }
            )
        
        return {
            "case_id": case_id,
            "before_photo_id": comparison["before_photo"]["id"],
            "after_photo_id": comparison["after_photo"]["id"],
            "visual_improvement_score": result.get("visual_improvement_score"),
            "overall_change": result.get("overall_change"),
            "analysis": result.get("analysis"),
            "confidence_score": result.get("confidence_score")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error comparing case photos: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compare photos: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=5000, reload=True)
5