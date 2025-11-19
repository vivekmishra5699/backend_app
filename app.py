from fastapi import FastAPI, HTTPException, Depends, status, Request, File, Form, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, ValidationError, Field
from datetime import datetime, timezone, timedelta, timedelta
from typing import Optional, List, Dict, Any
from supabase import create_client, Client
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
from connection_pool import get_supabase_client, close_connection_pools
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

# Load environment variables
load_dotenv()

# Global variables for services
ai_processor = None
background_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global ai_processor, background_task
    print("🚀 Starting AI Analysis background processor...")
    
    try:
        # Start the background processor task
        background_task = asyncio.create_task(ai_processor.start_processing())
        print("✅ AI Analysis background processor started successfully")
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

app = FastAPI(title="Doctor App API", version="1.0.0", lifespan=lifespan)

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
    supabase: Client = get_supabase_client(
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_SERVICE_ROLE_KEY,
        pool_size=10,  # Maintain 10 active connections
        max_overflow=20,  # Allow up to 20 overflow connections
        pool_timeout=30,  # Connection timeout
        pool_recycle=3600  # Recycle connections after 1 hour
    )
    print("✅ Supabase initialized with connection pooling")
    
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
    
except Exception as e:
    print(f"ERROR initializing Supabase: {e}")
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
                "doctor_firebase_uid": "doctor_firebase_uid_here"
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
    medical_history: Optional[str] = None
    
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
    created_at: str
    updated_at: str
    created_by_doctor: str



# Visit Models
class Vitals(BaseModel):
    temperature: Optional[float] = None  # in Celsius
    blood_pressure_systolic: Optional[int] = None
    blood_pressure_diastolic: Optional[int] = None
    heart_rate: Optional[int] = None  # BPM
    respiratory_rate: Optional[int] = None
    oxygen_saturation: Optional[float] = None  # percentage
    weight: Optional[float] = None  # in kg
    height: Optional[float] = None  # in cm
    bmi: Optional[float] = None

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
    # New handwritten notes fields
    note_input_type: Optional[str] = "typed"  # typed, handwritten
    selected_template_id: Optional[int] = None  # For handwritten notes
    # New billing fields
    consultation_fee: Optional[float] = None
    additional_charges: Optional[float] = None
    total_amount: Optional[float] = None
    payment_status: Optional[str] = "unpaid"  # unpaid, paid, partially_paid
    payment_method: Optional[str] = None  # cash, card, upi, bank_transfer
    payment_date: Optional[str] = None
    discount: Optional[float] = None
    notes_billing: Optional[str] = None

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
    # New handwritten notes fields
    note_input_type: Optional[str] = None
    selected_template_id: Optional[int] = None
    # New billing fields
    consultation_fee: Optional[float] = None
    additional_charges: Optional[float] = None
    total_amount: Optional[float] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None
    payment_date: Optional[str] = None
    discount: Optional[float] = None
    notes_billing: Optional[str] = None

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

# Additional models used in routes below
class PatientWithVisits(BaseModel):
    patient: 'PatientProfile'
    visits: list['Visit']

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

class HandwrittenNoteRequest(BaseModel):
    template_id: int
    send_whatsapp: bool = True
    custom_message: Optional[str] = None

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
    id: int
    patient_id: int
    doctor_firebase_uid: str
    analysis_period_start: Optional[str] = None
    analysis_period_end: Optional[str] = None
    total_visits: int
    total_reports: int
    model_used: str
    confidence_score: float
    raw_analysis: str
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
    analysis_success: bool
    analysis_error: Optional[str] = None
    processing_time_ms: Optional[int] = None
    analyzed_at: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

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
@app.post("/register", response_model=dict)
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

# Helper functions for password hashing
def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with salt"""
    salt = os.getenv("PASSWORD_SALT", "default_salt_change_in_production")
    return hashlib.sha256((password + salt).encode()).hexdigest()

def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return hash_password(password) == hashed_password


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


@app.post("/pharmacy/{pharmacy_id}/prescriptions/{prescription_id}/claim", response_model=dict)
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


@app.post("/pharmacy/{pharmacy_id}/prescriptions/{prescription_id}/status", response_model=dict)
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
    pharmacy_user = await get_current_pharmacy_user(pharmacy_id)
    hospital_name = pharmacy_user.get("hospital_name")

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

@app.post("/frontdesk/{frontdesk_id}/register-patient", response_model=dict)
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
@app.post("/patients/register", response_model=dict)
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
       

@app.get("/patients/{patient_id}/profile", response_model=PatientWithVisits)
async def get_patient_complete_profile(patient_id: int, current_doctor = Depends(get_current_doctor)):
    # Get patient basic info
    patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found"
        )
    
    # Get patient visits
    visits = await db.get_visits_by_patient_id(patient_id, current_doctor["firebase_uid"])
    
    return PatientWithVisits(
        patient=PatientProfile(**patient),
        visits=[Visit(**visit) for visit in visits]
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
                                request_token = str(uuid.uuid4())
                                request_data = {
                                    "visit_id": visit_id,
                                    "patient_id": visit.patient_id,
                                    "doctor_firebase_uid": current_doctor["firebase_uid"],
                                    "lab_contact_id": None,  # NULL for profile-based requests
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

@app.get("/visits/{visit_id}", response_model=Visit)
async def get_visit_details(visit_id: int, current_doctor = Depends(get_current_doctor)):
    visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
    if not visit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visit not found"
        )
    
    return Visit(**visit)

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
        
        loop = asyncio.get_event_loop()
        
        # Helper function to safely delete files from storage
        async def safe_delete_file(storage_path: str, file_type: str) -> bool:
            try:
                await loop.run_in_executor(
                    None,
                    lambda: supabase.storage.from_("medical-reports").remove([storage_path])
                )
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
                    folder_contents = await loop.run_in_executor(
                        None,
                        lambda: supabase.storage.from_("medical-reports").list(folder_path)
                    )
                    
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
    """Get the PDF template for handwriting, if the visit was created with handwritten notes option"""
    try:
        # Check if visit exists and belongs to current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Check if visit is set for handwritten notes
        if visit.get("note_input_type") != "handwritten":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This visit was not created with handwritten notes option"
            )
        
        # Get the selected template
        template_id = visit.get("selected_template_id")
        if not template_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No template selected for this visit"
            )
        
        template = await db.get_pdf_template_by_id(template_id, current_doctor["firebase_uid"])
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Template not found"
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
            "instructions": "Use a PDF editor or handwriting app to fill in the template, then upload the completed PDF using the upload endpoint."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting handwriting template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get handwriting template: {str(e)}"
        )

@app.post("/visits/{visit_id}/upload-handwritten-pdf", response_model=dict)
async def upload_handwritten_pdf(
    visit_id: int,
    request: Request,
    current_doctor = Depends(get_current_doctor)
):
    """Upload the completed handwritten PDF for a visit"""
    try:
        # Check if visit exists and belongs to current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        # Check if visit is set for handwritten notes
        if visit.get("note_input_type") != "handwritten":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This visit was not created with handwritten notes option"
            )
        
        # Parse multipart form data
        form = await request.form()
        files = form.getlist("file")
        send_whatsapp = form.get("send_whatsapp", "true").lower() == "true"
        custom_message = form.get("custom_message", "")
        
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
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"handwritten_visit_{visit_id}_{timestamp}.pdf"
        
        # Upload file to Supabase Storage
        storage_path = f"handwritten_notes/{current_doctor['firebase_uid']}/{unique_filename}"
        
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: supabase.storage.from_("medical-reports").upload(
                    path=storage_path,
                    file=file_content,
                    file_options={
                        "content-type": "application/pdf",
                        "x-upsert": "true"
                    }
                )
            )
            
            file_url = await loop.run_in_executor(
                None,
                lambda: supabase.storage.from_("medical-reports").get_public_url(storage_path)
            )
            
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
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        created_note = await db.create_handwritten_visit_note(handwritten_note_data)
        if not created_note:
            print("Warning: Failed to create handwritten note record, but file was uploaded successfully")
        
        response_data = {
            "message": "Handwritten PDF uploaded successfully",
            "visit_id": visit_id,
            "file_url": file_url,
            "file_name": unique_filename,
            "file_size": file_size,
            "template_used": template["template_name"] if template else "Unknown",
            "whatsapp_sent": False,
            "whatsapp_error": None
        }
        
        # Send WhatsApp message if requested
        if send_whatsapp:
            # Get patient information
            patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
            if patient and patient.get("phone"):
                try:
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

@app.get("/visits/{visit_id}/handwritten-notes", response_model=List[HandwrittenVisitNote])
async def get_visit_handwritten_notes(
    visit_id: int, 
    current_doctor = Depends(get_current_doctor)
):
    """Get all handwritten notes for a specific visit"""
    try:
        # Check if visit exists and belongs to current doctor
        visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
        if not visit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visit not found"
            )
        
        notes = await db.get_handwritten_visit_notes_by_visit_id(visit_id, current_doctor["firebase_uid"])
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
        base_url = os.getenv("PUBLIC_BASE_URL", "https://backend-app-wwld.onrender.com")
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
                    
                    # Run blocking storage operations in a thread
                    await loop.run_in_executor(
                        None,
                        lambda: supabase.storage.from_("medical-reports").upload(
                            path=bucket_path,
                            file=file_content,
                            file_options={
                                "content-type": file.content_type or "application/octet-stream",
                                "x-upsert": "false"
                            }
                        )
                    )
                    
                    file_url = await loop.run_in_executor(
                        None,
                        lambda: supabase.storage.from_("medical-reports").get_public_url(bucket_path)
                    )
                    
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
                        await loop.run_in_executor(
                            None,
                            lambda: supabase.storage.from_("medical-reports").remove([bucket_path])
                        )
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

            # Upload to storage - ensure header values are strings
            await loop.run_in_executor(
                None,
                lambda: supabase.storage.from_("medical-reports").upload(
                    path=storage_path,
                    file=pdf_bytes,
                    file_options={
                        "content-type": "application/pdf",
                        "x-upsert": "true",
                    },
                )
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

            public_res = await loop.run_in_executor(
                None,
                lambda: supabase.storage.from_("medical-reports").get_public_url(storage_path)
            )
            pdf_url = _extract_url(public_res)

            if not pdf_url:
                signed_res = await loop.run_in_executor(
                    None,
                    lambda: supabase.storage.from_("medical-reports").create_signed_url(storage_path, 60 * 60 * 24 * 7)
                )
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
@app.get("/calendar/{year}/{month}", response_model=MonthlyCalendar)
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

@app.get("/calendar/current", response_model=MonthlyCalendar)
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

@app.get("/calendar/summary", response_model=CalendarSummary)
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

@app.get("/calendar/debug/appointments/{date}")
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

@app.get("/calendar/appointments/{date}", response_model=List[CalendarAppointment])
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

@app.get("/calendar/upcoming", response_model=List[CalendarAppointment])
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

@app.get("/calendar/overdue", response_model=List[CalendarAppointment])
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

@app.put("/visits/{visit_id}/follow-up-date", response_model=dict)
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

@app.put("/visits/{visit_id}/billing", response_model=dict)
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

@app.get("/earnings/daily/{date}", response_model=EarningsReport)
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

@app.get("/earnings/monthly/{year}/{month}", response_model=EarningsReport)
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

@app.get("/earnings/yearly/{year}", response_model=EarningsReport)
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

@app.post("/earnings/custom", response_model=EarningsReport)
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

@app.get("/earnings/pending-payments", response_model=list[Visit])
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

@app.get("/earnings/dashboard", response_model=dict)
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
@app.post("/pdf-templates/upload", response_model=dict)
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
        loop = asyncio.get_event_loop()
        bucket_path = f"pdf_templates/{current_doctor['firebase_uid']}/{unique_filename}"
        
        try:
            await loop.run_in_executor(
                None,
                lambda: supabase.storage.from_("medical-reports").upload(
                    path=bucket_path,
                    file=file_content,
                    file_options={
                        "content-type": "application/pdf",
                        "x-upsert": "false"
                    }
                )
            )
            
            file_url = await loop.run_in_executor(
                None,
                lambda: supabase.storage.from_("medical-reports").get_public_url(bucket_path)
            )
            
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
                await loop.run_in_executor(
                    None,
                    lambda: supabase.storage.from_("medical-reports").remove([bucket_path])
                )
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

@app.get("/pdf-templates", response_model=list[PDFTemplate])
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

@app.get("/pdf-templates/{template_id}", response_model=PDFTemplate)
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

@app.put("/pdf-templates/{template_id}", response_model=dict)
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

@app.delete("/pdf-templates/{template_id}", response_model=dict)
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
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: supabase.storage.from_("medical-reports").remove([existing_template["storage_path"]])
                )
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

@app.get("/pdf-templates/{template_id}/download")
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
        
        # Upload report to Supabase Storage
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: supabase.storage.from_("medical-reports").upload(
                    path=storage_path,
                    file=pdf_bytes,
                    file_options={
                        "content-type": "application/pdf",
                        "x-upsert": "true"
                    }
                )
            )
            
            file_url = await loop.run_in_executor(
                None,
                lambda: supabase.storage.from_("medical-reports").get_public_url(storage_path)
            )
            
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

@app.get("/visits/{visit_id}/reports", response_model=list[VisitReport])
async def get_visit_reports_generated(visit_id: int, current_doctor = Depends(get_current_doctor)):
    """Get all generated visit reports for a specific visit"""
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
        
        # Perform AI analysis
        analysis_result = await ai_analysis_service.analyze_document(
            file_content=file_content,
            file_name=report["file_name"],
            file_type=report["file_type"],
            patient_context=patient,
            visit_context=visit,
            doctor_context=current_doctor
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

@app.post("/patients/{patient_id}/analyze-comprehensive-history", response_model=dict)
async def analyze_patient_comprehensive_history(
    patient_id: int,
    request_data: PatientHistoryAnalysisRequest,
    current_doctor = Depends(get_current_doctor)
):
    """Generate comprehensive AI-powered analysis of complete patient history including all visits, reports, and medical journey"""
    try:
        start_time = datetime.now()
        
        # Verify the patient exists and belongs to the current doctor
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Check if analysis already exists for this patient (check for recent analysis)
        existing_analysis = await db.get_latest_patient_history_analysis(patient_id, current_doctor["firebase_uid"])
        
        # Clean up any outdated analyses first
        await db.cleanup_outdated_patient_history_analyses(patient_id, current_doctor["firebase_uid"])
        
        # Re-fetch after cleanup to get the most current analysis (if any)
        existing_analysis = await db.get_latest_patient_history_analysis(patient_id, current_doctor["firebase_uid"])
        
        if existing_analysis:
            # Check if the analysis is recent (within last 24 hours)
            analyzed_at = datetime.fromisoformat(existing_analysis["analyzed_at"].replace('Z', '+00:00'))
            time_diff = datetime.now(timezone.utc) - analyzed_at
            
            # Get current data counts for validation
            visits = []
            if request_data.include_visits:
                visits = await db.get_visits_by_patient_id(patient_id, current_doctor["firebase_uid"])
                # Filter by time period if specified
                if request_data.analysis_period_months:
                    cutoff_date = datetime.now(timezone.utc) - timedelta(days=request_data.analysis_period_months * 30)
                    cutoff_date_only = cutoff_date.date()
                    visits = [v for v in visits if datetime.fromisoformat(v["visit_date"]).date() >= cutoff_date_only]
            
            reports = []
            if request_data.include_reports:
                reports = await db.get_reports_by_patient_id(patient_id, current_doctor["firebase_uid"])
                # Filter by time period if specified
                if request_data.analysis_period_months:
                    cutoff_date = datetime.now(timezone.utc) - timedelta(days=request_data.analysis_period_months * 30)
                    reports = [r for r in reports if datetime.fromisoformat(r["uploaded_at"].replace('Z', '+00:00')) >= cutoff_date]
            
            # Also check if the analysis data is still valid by comparing visit/report counts
            analysis_is_outdated = False
            if existing_analysis.get("total_visits", 0) != len(visits) or existing_analysis.get("total_reports", 0) != len(reports):
                analysis_is_outdated = True
            
            # Return cached analysis only if it's recent AND data hasn't changed
            if time_diff.total_seconds() < 24 * 3600 and not analysis_is_outdated:  # Less than 24 hours old and data unchanged
                return {
                    "message": "Recent comprehensive analysis already exists for this patient",
                    "analysis": PatientHistoryAnalysis(**existing_analysis),
                    "analysis_age_hours": time_diff.total_seconds() / 3600,
                    "already_exists": True
                }
            elif analysis_is_outdated:
                # Delete the outdated analysis to force regeneration
                await db.delete_patient_history_analysis(existing_analysis["id"], current_doctor["firebase_uid"])
        
        # Get all patient visits
        visits = []
        if request_data.include_visits:
            visits = await db.get_visits_by_patient_id(patient_id, current_doctor["firebase_uid"])
            
            # Filter by time period if specified
            if request_data.analysis_period_months:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=request_data.analysis_period_months * 30)
                cutoff_date_only = cutoff_date.date()
                visits = [v for v in visits if datetime.fromisoformat(v["visit_date"]).date() >= cutoff_date_only]
        
        # Get all patient reports
        reports = []
        if request_data.include_reports:
            reports = await db.get_reports_by_patient_id(patient_id, current_doctor["firebase_uid"])
            
            # Filter by time period if specified
            if request_data.analysis_period_months:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=request_data.analysis_period_months * 30)
                reports = [r for r in reports if datetime.fromisoformat(r["uploaded_at"].replace('Z', '+00:00')) >= cutoff_date]
        
        # Get existing AI analyses for this patient
        existing_ai_analyses = await db.get_ai_analyses_by_patient_id(patient_id, current_doctor["firebase_uid"])
        
        if not visits and not reports:
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
        
        # Perform comprehensive patient history analysis
        analysis_result = await ai_analysis_service.analyze_patient_comprehensive_history(
            patient_context=patient,
            visits=visits,
            reports=report_documents,
            existing_analyses=existing_ai_analyses,
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
                "comprehensive_summary": analysis_result.get("summary"),
                "medical_trajectory": analysis_result.get("medical_trajectory"),
                "chronic_conditions": analysis_result.get("chronic_conditions", []),
                "recurring_patterns": analysis_result.get("recurring_patterns", []),
                "treatment_effectiveness": analysis_result.get("treatment_effectiveness"),
                "risk_factors": analysis_result.get("risk_factors", []),
                "recommendations": analysis_result.get("recommendations", []),
                "significant_findings": analysis_result.get("significant_findings", []),
                "lifestyle_factors": analysis_result.get("lifestyle_factors"),
                "medication_history": analysis_result.get("medication_history"),
                "follow_up_suggestions": analysis_result.get("follow_up_suggestions", []),
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

@app.post("/patients/{patient_id}/cleanup-history-analyses", response_model=dict)
async def cleanup_patient_history_analyses(
    patient_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Manually clean up outdated comprehensive history analyses for a specific patient"""
    try:
        # Verify the patient exists and belongs to the current doctor
        patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found"
            )
        
        # Get analyses before cleanup
        analyses_before = await db.get_patient_history_analyses(patient_id, current_doctor["firebase_uid"])
        
        # Run cleanup
        cleanup_result = await db.cleanup_outdated_patient_history_analyses(patient_id, current_doctor["firebase_uid"])
        
        # Get analyses after cleanup
        analyses_after = await db.get_patient_history_analyses(patient_id, current_doctor["firebase_uid"])
        
        cleaned_count = len(analyses_before) - len(analyses_after)
        
        return {
            "message": "Cleanup completed successfully",
            "patient_name": f"{patient['first_name']} {patient['last_name']}",
            "analyses_before": len(analyses_before),
            "analyses_after": len(analyses_after),
            "cleaned_count": cleaned_count,
            "cleanup_success": cleanup_result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in patient history analysis cleanup: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during cleanup"
        )

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
@app.get("/notifications", response_model=List[Notification])
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

@app.get("/notifications/summary", response_model=NotificationSummary)
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

@app.get("/notifications/unread/count", response_model=dict)
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

@app.put("/notifications/{notification_id}/read", response_model=dict)
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

@app.put("/notifications/mark-all-read", response_model=dict)
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

@app.delete("/notifications/{notification_id}", response_model=dict)
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
                request_token = str(uuid.uuid4())
                request_data = {
                    "visit_id": visit_id,
                    "patient_id": visit["patient_id"],
                    "doctor_firebase_uid": current_doctor["firebase_uid"],
                    "lab_contact_id": None,  # NULL for profile-based requests
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
        
        # Create lab report request (lab_contact_id will be NULL for profile-based requests)
        request_data = {
            "visit_id": visit_id,
            "patient_id": visit["patient_id"],
            "doctor_firebase_uid": current_doctor["firebase_uid"],
            "lab_contact_id": None,  # NULL for profile-based requests
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
                "requests": []
            }
        
        # Get lab report requests
        requests = await db.get_lab_report_requests_by_phone(phone, status)
        
        # Format the response with detailed info
        formatted_requests = []
        for req in requests:
            patient = req.get("patients", {})
            visit = req.get("visits", {})
            
            formatted_request = {
                "id": req["id"],
                "visit_id": req["visit_id"],
                "patient_id": req["patient_id"],
                "doctor_firebase_uid": req["doctor_firebase_uid"],
                "patient_name": req["patient_name"],
                "report_type": req["report_type"],
                "test_name": req["test_name"],
                "instructions": req.get("instructions"),
                "status": req["status"],
                "request_token": req["request_token"],
                "expires_at": req["expires_at"],
                "created_at": req["created_at"],
                "patient_phone": patient.get("phone"),
                "visit_date": visit.get("visit_date"),
                "visit_type": visit.get("visit_type"),
                "chief_complaint": visit.get("chief_complaint"),
                "contact_source": req.get("contact_source", "unknown")
            }
            formatted_requests.append(formatted_request)
        
        return {
            "lab_contact_info": lab_contact_info,
            "phone": phone,
            "total_requests": len(formatted_requests),
            "pending_count": len([r for r in formatted_requests if r["status"] == "pending"]),
            "requests": formatted_requests
        }
        
    except Exception as e:
        print(f"Error getting lab dashboard: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get lab dashboard"
        )

# Debug endpoint for testing file uploads
@app.post("/debug-upload")
async def debug_upload(request: Request):
    """Debug file upload issues"""
    try:
        form = await request.form()
        
        debug_info = {
            "form_keys": list(form.keys()),
            "form_items": {}
        }
        
        for key, value in form.items():
            if hasattr(value, 'filename'):
                debug_info["form_items"][key] = {
                    "type": str(type(value)),
                    "filename": getattr(value, 'filename', None),
                    "content_type": getattr(value, 'content_type', None),
                    "size": len(await value.read()) if hasattr(value, 'read') else 'unknown'
                }
                # Reset file position after reading
                if hasattr(value, 'seek'):
                    await value.seek(0)
            else:
                debug_info["form_items"][key] = {
                    "type": str(type(value)),
                    "value": str(value)
                }
        
        return debug_info
    except Exception as e:
        return {"error": str(e)}

# Alternative lab upload endpoint using FastAPI File parameter
@app.post("/api/lab-upload-reports-alt", response_model=dict)
async def lab_upload_reports_alternative(
    request_token: str = Form(...),
    notes: str = Form(""),
    files: List[UploadFile] = File(...)
):
    """Alternative lab report upload using FastAPI File parameter"""
    try:
        print(f"Alt upload - Token: {request_token}, Files: {len(files)}")
        
        # Get and validate request
        request_data = await db.get_lab_report_request_by_token(request_token)
        if not request_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid request token"
            )
        
        uploaded_files = []
        
        for file in files:
            print(f"Processing file: {file.filename}")
            file_content = await file.read()
            file_size = len(file_content)
            print(f"File size: {file_size} bytes")
            
            if file_size > 0:
                # Simple success for now
                uploaded_files.append({
                    "file_name": file.filename,
                    "file_size": file_size
                })
        
        return {
            "message": f"Successfully uploaded {len(uploaded_files)} file(s) via alternative endpoint",
            "uploaded_files": uploaded_files,
            "upload_count": len(uploaded_files)
        }
        
    except Exception as e:
        print(f"Alt upload error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

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
                
                await loop.run_in_executor(
                    None,
                    lambda: supabase.storage.from_("medical-reports").upload(
                        path=bucket_path,
                        file=file_content,
                        file_options={
                            "content-type": file.content_type or "application/octet-stream",
                            "x-upsert": "false"
                        }
                    )
                )
                
                file_url = await loop.run_in_executor(
                    None,
                    lambda: supabase.storage.from_("medical-reports").get_public_url(bucket_path)
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
            
            # Create temporary upload link for lab uploads
            link_data = {
                "visit_id": request_data["visit_id"],
                "patient_id": request_data["patient_id"],
                "doctor_firebase_uid": request_data["doctor_firebase_uid"],
                "upload_token": lab_upload_token,
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            }
            
            await db.create_report_upload_link(link_data)
            print(f"Created temporary upload link for lab upload: {lab_upload_token}")
            
            # Create report record using the same structure as regular uploads
            report_data = {
                "visit_id": request_data["visit_id"],
                "patient_id": request_data["patient_id"],
                "doctor_firebase_uid": request_data["doctor_firebase_uid"],
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=5000, reload=True)
