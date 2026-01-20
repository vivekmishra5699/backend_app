# 🏥 Medical Practice Management System - Backend API

A comprehensive, production-ready FastAPI backend for managing complete medical practice operations including doctor workflows, pharmacy integration, lab management, front desk operations, AI-powered report analysis, and patient engagement.

## 🌟 Key Features

- **Multi-Role Support**: Doctors, Pharmacists, Lab Technicians, Front Desk Staff
- **AI-Powered Analysis**: Automated medical report analysis using Google Gemini AI
- **WhatsApp Integration**: Automated notifications and report sharing via Twilio
- **Performance Optimized**: Connection pooling, LRU caching, async operations
- **Comprehensive Billing**: Track consultations, payments, and earnings analytics
- **Lab Integration**: External lab report management (pathology & radiology)
- **Pharmacy Management**: Prescription tracking, inventory, and invoicing
- **Calendar & Appointments**: Follow-up tracking and appointment scheduling
- **PDF Generation**: Professional visit reports and patient profiles
- **Real-time Notifications**: In-app notification system for doctors

## 🏗️ System Architecture

```
backend_app/
├── app.py                          # Main FastAPI app (10,000+ lines, 150+ endpoints)
├── database.py                     # Database abstraction with connection pooling
├── firebase_manager.py             # Async Firebase authentication
├── whatsapp_service.py             # Twilio WhatsApp integration
├── ai_analysis_service.py          # Google Gemini AI analysis engine
├── ai_analysis_processor.py        # Background AI processing queue
├── pdf_generator.py                # PDF generation utilities
├── visit_report_generator.py       # Medical report templates
├── connection_pool.py              # Supabase connection pool manager
├── thread_pool_manager.py          # Unified thread pool for async operations
├── optimized_cache.py              # LRU cache with TTL and statistics
├── async_file_downloader.py        # Async file download handler
├── query_cache.py                  # Database query result caching
├── current_schema.sql              # Complete database schema (context)
└── requirements.txt                # Python dependencies
```

## 📋 Table of Contents

- [Quick Start](#-quick-start)
- [Environment Setup](#-environment-setup)
- [Core Modules](#-core-modules)
- [API Endpoints](#-api-endpoints-reference)
- [Authentication](#-authentication)
- [Database Schema](#-database-schema)
- [Usage Examples](#-usage-examples)
- [Performance Features](#-performance--scalability)
- [Deployment](#-deployment)
- [Testing](#-testing)

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+** (Tested on 3.11+)
- **Supabase Account** (PostgreSQL database)
- **Firebase Project** (for authentication)
- **Twilio Account** (for WhatsApp messaging)
- **Google AI API Key** (for Gemini AI analysis)

### Installation

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd backend_app

# 2. Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows PowerShell:
venv\Scripts\Activate.ps1
# Windows CMD:
venv\Scripts\activate.bat
# macOS/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables (see below)
# Create .env file with required configurations

# 5. Run the application
python app.py
# OR
uvicorn app:app --host 127.0.0.1 --port 5000 --reload
```

The API will be available at: **http://localhost:5000**

---

## 🔧 Environment Setup

Create a `.env` file in the root directory:

```env
# ==================== SUPABASE CONFIGURATION ====================
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key

# ==================== FIREBASE CONFIGURATION ====================
FIREBASE_PROJECT_ID=your-firebase-project-id
# Place your Firebase admin SDK JSON file in the root directory
# File should be named: doctor-4bdc9-firebase-adminsdk-xxxxx.json

# ==================== TWILIO WHATSAPP CONFIGURATION ====================
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886

# ==================== AI CONFIGURATION ====================
GOOGLE_API_KEY=your_google_ai_api_key

# ==================== OPTIONAL CONFIGURATIONS ====================
# Set to 'production' for production deployment
ENVIRONMENT=development
```

### Firebase Setup

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Create a new project (or use existing)
3. Enable **Authentication** > **Sign-in method** > **Email/Password**
4. Go to **Project Settings** > **Service Accounts**
5. Click **Generate New Private Key**
6. Save the JSON file to your project root directory

---

## 📦 Core Modules

### 1. `app.py` - Main FastAPI Application

The core application with 150+ API endpoints organized into:

**Doctor Endpoints:**
- Authentication (register, login, profile management)
- Patient management (CRUD operations)
- Visit tracking and management
- Medical report analysis
- Calendar and appointments
- Earnings and billing

**Pharmacy Endpoints:**
- Prescription management
- Inventory tracking
- Invoice generation
- Sales analytics
- Supplier management

**Front Desk Endpoints:**
- Patient registration
- Appointment scheduling
- Hospital dashboard
- Multi-doctor management

**Lab Technician Endpoints:**
- Lab report requests
- Upload interface for pathology/radiology reports
- Lab dashboard

**Shared Features:**
- WhatsApp integration
- PDF generation
- AI analysis
- Notifications

### 2. `database.py` - Database Layer

**Connection Management:**
```python
# Uses connection pooling for performance
- Connection pool with max 10 connections
- Automatic connection reuse
- Retry logic for failed queries
```

**Key Functions:**
- All CRUD operations for doctors, patients, visits, reports
- Complex analytical queries with JOINs
- Transaction support
- Async/await pattern throughout

### 3. `firebase_manager.py` - Authentication

**AsyncFirebaseManager Class:**
- JWT token validation
- User authentication
- Custom middleware for protected routes
- Token expiration handling
- Async Firebase Admin SDK integration

### 4. `whatsapp_service.py` - WhatsApp Messaging

**WhatsAppService Class:**
- Send text messages
- Send media files (PDFs, images)
- Template messages
- Message status tracking
- Error handling and retry logic

**Use Cases:**
- Send report upload links to patients
- Share medical reports after upload
- Send visit summaries
- Appointment reminders

### 5. `ai_analysis_service.py` - AI Analysis Engine

**Powered by Google Gemini AI (gemini-2.0-flash-exp)**

**Features:**
- Single document analysis
- Multi-document consolidated analysis
- Comprehensive patient history analysis
- Structured medical data extraction
- Clinical significance assessment
- Patient-friendly communication generation

**Analysis Types:**
1. **Document Analysis**: Individual medical reports
2. **Consolidated Analysis**: Multiple reports from one visit
3. **Patient History Analysis**: Complete medical timeline

### 6. `ai_analysis_processor.py` - Background Processing

**Background Worker:**
- Queue-based task processing
- Automatic retry on failures
- Priority-based processing
- Status tracking (pending, processing, completed, failed)
- Graceful shutdown handling

**Benefits:**
- Non-blocking API responses
- Handles long-running AI tasks
- Prevents timeout issues
- Better resource management

### 7. `connection_pool.py` - Performance Optimization

**Features:**
- Supabase client connection pooling
- Singleton pattern for shared connections
- Automatic cleanup on shutdown
- Thread-safe operations

### 8. `optimized_cache.py` - Caching Layer

**LRU Cache with TTL:**
```python
- Maximum 1000 items
- 5-minute TTL (time-to-live)
- Thread-safe operations
- Cache statistics (hits, misses, hit rate)
- Automatic eviction of old entries
```

**Cached Operations:**
- Patient profiles
- Visit details
- Doctor profiles
- Lab contacts
- PDF templates

### 9. `thread_pool_manager.py` - Async Operations

**Unified Thread Pool:**
- Shared executor for CPU-bound tasks
- Configurable worker count
- Graceful shutdown
- Used for file I/O, PDF generation, etc.

---

## 🌐 API Endpoints Reference

### Overview

The API has **150+ endpoints** organized into the following categories:

| Category | Endpoints | Description |
|----------|-----------|-------------|
| Authentication | 5 | Doctor/Pharmacy/Frontdesk login & registration |
| Patient Management | 7 | CRUD operations for patients |
| Visit Management | 12 | Create, update, track medical visits |
| Report Management | 15 | Upload, download, group medical reports |
| AI Analysis | 12 | Analyze reports, patient history |
| Calendar & Appointments | 8 | Follow-up tracking, appointments |
| Notifications | 6 | In-app notifications for doctors |
| Billing & Earnings | 6 | Track payments and revenue |
| PDF & Templates | 8 | Generate and manage PDF templates |
| Lab Management | 9 | Lab report requests and uploads |
| Pharmacy Management | 18 | Prescriptions, inventory, invoicing |
| Front Desk | 6 | Appointments, patient registration |
| WhatsApp Integration | 5 | Send messages and media |

### Authentication Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/` | Root endpoint / health check | ❌ |
| `GET` | `/test` | API status test | ❌ |
| `POST` | `/register` | Doctor registration | ❌ |
| `POST` | `/login` | Doctor login | ❌ |
| `POST` | `/validate-token` | Validate Firebase JWT token | ❌ |
| `GET` | `/profile` | Get doctor profile | ✅ Doctor |
| `PUT` | `/profile` | Update doctor profile | ✅ Doctor |

**Doctor Registration Example:**
```json
POST /register
{
  "email": "doctor@example.com",
  "firebase_uid": "firebase_user_id_here",
  "first_name": "John",
  "last_name": "Doe",
  "specialization": "Cardiology",
  "license_number": "MED123456",
  "phone": "1234567890",
  "hospital_name": "City Hospital"
}
```

### Patient Management Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/patients/register` | Register new patient | ✅ Doctor |
| `GET` | `/patients` | Get all doctor's patients | ✅ Doctor |
| `GET` | `/patients/{patient_id}` | Get patient details | ✅ Doctor |
| `PUT` | `/patients/{patient_id}` | Update patient info | ✅ Doctor |
| `DELETE` | `/patients/{patient_id}` | Delete patient | ✅ Doctor |
| `GET` | `/patients/{patient_id}/profile` | Get patient with all visits | ✅ Doctor |
| `GET` | `/patients/{patient_id}/reports` | Get all patient reports | ✅ Doctor |

**Create Patient Example:**
```json
POST /patients/register
Authorization: Bearer <firebase_jwt_token>

{
  "first_name": "Jane",
  "last_name": "Smith",
  "email": "jane@example.com",
  "phone": "9876543210",
  "date_of_birth": "1990-05-15",
  "gender": "Female",
  "address": "123 Main St, City",
  "blood_group": "O+",
  "allergies": "Penicillin",
  "medical_history": "Hypertension since 2018"
}
```

### Visit Management Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/patients/{patient_id}/visits` | Create new visit | ✅ Doctor |
| `GET` | `/patients/{patient_id}/visits` | Get patient's visits | ✅ Doctor |
| `GET` | `/visits/{visit_id}` | Get visit details | ✅ Doctor |
| `PUT` | `/visits/{visit_id}` | Update visit | ✅ Doctor |
| `DELETE` | `/visits/{visit_id}` | Delete visit | ✅ Doctor |
| `PUT` | `/visits/{visit_id}/billing` | Update billing info | ✅ Doctor |
| `PUT` | `/visits/{visit_id}/follow-up-date` | Set follow-up appointment | ✅ Doctor |
| `POST` | `/visits/{visit_id}/generate-report` | Generate visit PDF | ✅ Doctor |
| `GET` | `/visits/{visit_id}/handwriting-template` | Get template for notes | ✅ Doctor |
| `POST` | `/visits/{visit_id}/upload-handwritten-pdf` | Upload handwritten notes | ✅ Doctor |

**Create Visit Example:**
```json
POST /patients/8/visits
Authorization: Bearer <token>

{
  "visit_date": "2025-11-09",
  "visit_time": "10:30:00",
  "visit_type": "Follow-up",
  "chief_complaint": "Chest pain",
  "symptoms": "Intermittent chest pain for 2 days",
  "vitals": {
    "blood_pressure": "120/80",
    "pulse": "72",
    "temperature": "98.6",
    "weight": "70"
  },
  "clinical_examination": "Cardiovascular: Normal S1, S2",
  "diagnosis": "Stable angina",
  "treatment_plan": "Continue medications, lifestyle modifications",
  "medications": "Aspirin 75mg OD, Atorvastatin 20mg OD",
  "tests_recommended": "ECG, Lipid profile",
  "follow_up_date": "2025-12-09",
  "consultation_fee": 500,
  "payment_status": "paid",
  "payment_method": "cash"
}
```

### Report Management & Upload

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/visits/{visit_id}/generate-report-link` | Create upload link for patients | ✅ Doctor |
| `POST` | `/visits/{visit_id}/send-whatsapp-report-link` | Send link via WhatsApp | ✅ Doctor |
| `GET` | `/upload-reports/{upload_token}` | Patient upload page (HTML) | ❌ Public |
| `POST` | `/api/upload-reports` | Upload reports (from patient) | ❌ Public |
| `GET` | `/visits/{visit_id}/reports` | Get visit's reports | ✅ Doctor |
| `GET` | `/visits/{visit_id}/reports/grouped` | Get grouped reports | ✅ Doctor |
| `GET` | `/reports/{report_id}/download` | Download report file | ✅ Doctor |

**Upload Flow:**
1. Doctor generates upload link: `POST /visits/{visit_id}/generate-report-link`
2. System returns unique token and expiry (24 hours)
3. Doctor sends link via WhatsApp: `POST /visits/{visit_id}/send-whatsapp-report-link`
4. Patient clicks link, opens upload page: `GET /upload-reports/{token}`
5. Patient uploads files: `POST /api/upload-reports`
6. Doctor receives notification
7. AI analysis automatically triggered

### AI Analysis Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/reports/{report_id}/analyze` | Analyze single report | ✅ Doctor |
| `POST` | `/visits/{visit_id}/analyze-consolidated` | Analyze all visit reports | ✅ Doctor |
| `POST` | `/patients/{patient_id}/analyze-comprehensive-history` | Analyze patient history | ✅ Doctor |
| `GET` | `/reports/{report_id}/analysis` | Get report analysis | ✅ Doctor |
| `GET` | `/visits/{visit_id}/analyses` | Get visit analyses | ✅ Doctor |
| `GET` | `/visits/{visit_id}/consolidated-analyses` | Get consolidated analyses | ✅ Doctor |
| `GET` | `/patients/{patient_id}/analyses` | Get all patient analyses | ✅ Doctor |
| `GET` | `/patients/{patient_id}/history-analysis` | Get latest history analysis | ✅ Doctor |
| `GET` | `/ai-analysis-summary` | Get AI processing summary | ✅ Doctor |
| `GET` | `/ai-processor-status` | Get processor status | ✅ Doctor |
| `POST` | `/reports/batch-analyze` | Batch analyze multiple reports | ✅ Doctor |

**AI Analysis Response Example:**
```json
{
  "report_id": 123,
  "analysis_type": "document_analysis",
  "model_used": "gemini-2.0-flash-exp",
  "confidence_score": 0.92,
  "document_summary": "Complete blood count showing mild anemia...",
  "clinical_significance": "Hemoglobin levels below normal range...",
  "key_findings": {
    "abnormal_values": ["Hemoglobin: 10.2 g/dL (Low)"],
    "normal_values": ["WBC: 7200/μL"]
  },
  "actionable_insights": "Consider iron supplementation...",
  "patient_communication": "Your blood test shows mild anemia...",
  "analysis_success": true,
  "analyzed_at": "2025-11-09T10:30:00Z"
}
```

### Calendar & Appointments

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/calendar/current` | Get current month calendar | ✅ Doctor |
| `GET` | `/calendar/{year}/{month}` | Get specific month | ✅ Doctor |
| `GET` | `/calendar/appointments/{date}` | Get day's appointments | ✅ Doctor |
| `GET` | `/calendar/upcoming` | Get upcoming appointments | ✅ Doctor |
| `GET` | `/calendar/overdue` | Get overdue follow-ups | ✅ Doctor |
| `GET` | `/calendar/summary` | Get calendar summary | ✅ Doctor |

**Calendar Response Example:**
```json
GET /calendar/current

{
  "year": 2025,
  "month": 11,
  "month_name": "November",
  "total_appointments": 45,
  "appointments_by_date": {
    "2025-11-09": 3,
    "2025-11-10": 5,
    "2025-11-15": 2
  },
  "appointments": [
    {
      "visit_id": 39,
      "patient_name": "John Doe",
      "patient_phone": "1234567890",
      "follow_up_date": "2025-11-10",
      "follow_up_time": "10:00:00",
      "chief_complaint": "Follow-up checkup",
      "is_overdue": false,
      "days_until_appointment": 1
    }
  ]
}
```

### Notifications

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/notifications` | Get all notifications | ✅ Doctor |
| `GET` | `/notifications/summary` | Get notification summary | ✅ Doctor |
| `GET` | `/notifications/unread/count` | Get unread count (for badges) | ✅ Doctor |
| `PUT` | `/notifications/{notification_id}/read` | Mark as read | ✅ Doctor |
| `PUT` | `/notifications/mark-all-read` | Mark all as read | ✅ Doctor |
| `DELETE` | `/notifications/{notification_id}` | Delete notification | ✅ Doctor |

**Notification Types:**
- `report_upload` - Patient uploaded medical reports
- `ai_analysis_complete` - AI analysis finished
- `ai_analysis_failed` - AI analysis failed
- `follow_up_reminder` - Upcoming appointment
- `lab_report_uploaded` - Lab uploaded reports

### Billing & Earnings

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/earnings/daily/{date}` | Daily earnings report | ✅ Doctor |
| `GET` | `/earnings/monthly/{year}/{month}` | Monthly earnings | ✅ Doctor |
| `GET` | `/earnings/yearly/{year}` | Yearly earnings | ✅ Doctor |
| `POST` | `/earnings/custom` | Custom date range | ✅ Doctor |
| `GET` | `/earnings/pending-payments` | Unpaid visits | ✅ Doctor |
| `GET` | `/earnings/dashboard` | Earnings dashboard | ✅ Doctor |

**Earnings Response:**
```json
GET /earnings/monthly/2025/11

{
  "period": "November 2025",
  "total_visits": 45,
  "paid_visits": 40,
  "unpaid_visits": 5,
  "total_earnings": 22500.00,
  "consultation_fees": 20000.00,
  "additional_charges": 2500.00,
  "pending_amount": 2500.00,
  "payment_methods": {
    "cash": 15000.00,
    "upi": 5000.00,
    "card": 2500.00
  }
}
```

### Lab Management (External Labs)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/lab-contacts` | Add lab contact | ✅ Doctor |
| `GET` | `/lab-contacts` | Get lab contacts | ✅ Doctor |
| `PUT` | `/lab-contacts/{contact_id}` | Update lab contact | ✅ Doctor |
| `DELETE` | `/lab-contacts/{contact_id}` | Delete lab contact | ✅ Doctor |
| `POST` | `/visits/{visit_id}/request-lab-report` | Request lab upload | ✅ Doctor |
| `POST` | `/lab-login` | Lab technician login | ❌ Public |
| `GET` | `/lab-dashboard/{phone}` | Lab dashboard | ❌ Lab Tech |
| `GET` | `/lab-upload/{request_token}` | Lab upload page | ❌ Lab Tech |
| `POST` | `/api/lab-upload-reports` | Upload lab reports | ❌ Lab Tech |

**Lab Workflow:**
1. Doctor adds lab contacts: `POST /lab-contacts`
2. Doctor requests report upload: `POST /visits/{visit_id}/request-lab-report`
3. Lab receives WhatsApp message with upload link
4. Lab logs in: `POST /lab-login`
5. Lab views pending requests: `GET /lab-dashboard/{phone}`
6. Lab uploads reports: `POST /api/lab-upload-reports`
7. Doctor receives notification
8. AI analysis triggered automatically

### Pharmacy Management

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/pharmacy/register` | Register pharmacy | ❌ |
| `POST` | `/pharmacy/login` | Pharmacy login | ❌ |
| `GET` | `/pharmacy/{pharmacy_id}/dashboard` | Pharmacy dashboard | ✅ Pharmacy |
| `GET` | `/pharmacy/{pharmacy_id}/prescriptions` | Get prescriptions | ✅ Pharmacy |
| `POST` | `/pharmacy/{pharmacy_id}/prescriptions/{id}/claim` | Claim prescription | ✅ Pharmacy |
| `POST` | `/pharmacy/{pharmacy_id}/prescriptions/{id}/status` | Update status | ✅ Pharmacy |
| `POST` | `/pharmacy/{pharmacy_id}/prescriptions/{id}/invoice` | Generate invoice | ✅ Pharmacy |
| `GET` | `/pharmacy/{pharmacy_id}/inventory` | Get inventory | ✅ Pharmacy |
| `POST` | `/pharmacy/{pharmacy_id}/inventory` | Add inventory item | ✅ Pharmacy |
| `PUT` | `/pharmacy/{pharmacy_id}/inventory/{item_id}` | Update inventory | ✅ Pharmacy |
| `GET` | `/pharmacy/{pharmacy_id}/suppliers` | Get suppliers | ✅ Pharmacy |
| `POST` | `/pharmacy/{pharmacy_id}/suppliers` | Add supplier | ✅ Pharmacy |
| `GET` | `/pharmacy/{pharmacy_id}/reports/sales` | Sales report | ✅ Pharmacy |

**Pharmacy Features:**
- Prescription management and dispensing
- Inventory tracking with low-stock alerts
- Supplier management
- Invoice generation with tax calculations
- Sales analytics and reports
- Patient medication history

### Front Desk Management

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/frontdesk/register` | Register front desk user | ❌ |
| `POST` | `/frontdesk/login` | Front desk login | ❌ |
| `GET` | `/frontdesk/{id}/dashboard` | Hospital dashboard | ✅ Frontdesk |
| `GET` | `/frontdesk/{id}/doctors` | Get all doctors | ✅ Frontdesk |
| `GET` | `/frontdesk/{id}/patients` | Get all patients | ✅ Frontdesk |
| `POST` | `/frontdesk/{id}/register-patient` | Register patient | ✅ Frontdesk |
| `POST` | `/frontdesk/{id}/appointments` | Create appointment | ✅ Frontdesk |
| `GET` | `/frontdesk/{id}/appointments` | Get appointments | ✅ Frontdesk |
| `PUT` | `/frontdesk/{id}/appointments/{appointment_id}` | Update appointment | ✅ Frontdesk |
| `DELETE` | `/frontdesk/{id}/appointments/{appointment_id}` | Cancel appointment | ✅ Frontdesk |

**Front Desk Features:**
- Multi-doctor management in one hospital
- Patient registration across doctors
- Appointment scheduling
- Hospital-wide dashboard
- Patient search and management

### PDF Templates & Generation

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/pdf-templates/upload` | Upload template | ✅ Doctor |
| `GET` | `/pdf-templates` | Get all templates | ✅ Doctor |
| `GET` | `/pdf-templates/{template_id}` | Get template | ✅ Doctor |
| `PUT` | `/pdf-templates/{template_id}` | Update template | ✅ Doctor |
| `DELETE` | `/pdf-templates/{template_id}` | Delete template | ✅ Doctor |
| `GET` | `/pdf-templates/{template_id}/download` | Download template | ✅ Doctor |
| `POST` | `/visits/{visit_id}/generate-report` | Generate visit PDF | ✅ Doctor |
| `POST` | `/patients/{patient_id}/send-profile` | Send profile via WhatsApp | ✅ Doctor |

---

## 🔐 Authentication

The API uses **Firebase JWT tokens** for authentication.

### How It Works

1. **User authenticates via Firebase** (in Flutter/mobile app)
2. **Firebase returns JWT token**
3. **Include token in API requests** via Authorization header

### Request Format

```http
GET /patients
Authorization: Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Ij...
```

### Authentication Middleware

The API uses a custom `get_current_user` dependency that:
- Validates JWT token signature
- Checks token expiration
- Extracts user Firebase UID
- Returns authenticated user info

### Protected Routes

Routes marked with ✅ require authentication. Example:

```python
@app.get("/patients", response_model=list[PatientProfile])
async def get_patients(current_user = Depends(get_current_user)):
    # current_user contains: {"uid": "firebase_uid", "email": "user@example.com"}
    doctor_uid = current_user["uid"]
    # ... fetch and return patients
```

### Error Responses

**401 Unauthorized:**
```json
{
  "detail": "Invalid authentication credentials",
  "status_code": 401
}
```

**403 Forbidden:**
```json
{
  "detail": "You don't have permission to access this resource",
  "status_code": 403
}
```

---

## 🗄️ Database Schema

The system uses **Supabase (PostgreSQL)** with the following core tables:

### Core Tables

**doctors** - Doctor profiles and credentials
```sql
id, firebase_uid, email, first_name, last_name, 
specialization, license_number, phone, hospital_name,
pathology_lab_name, pathology_lab_phone,
radiology_lab_name, radiology_lab_phone
```

**patients** - Patient records
```sql
id, first_name, last_name, email, phone, date_of_birth,
gender, address, blood_group, allergies, medical_history,
emergency_contact_name, emergency_contact_phone,
created_by_doctor
```

**visits** - Medical visits
```sql
id, patient_id, doctor_firebase_uid, visit_date, visit_time,
visit_type, chief_complaint, symptoms, vitals (JSONB),
clinical_examination, diagnosis, treatment_plan, medications,
tests_recommended, follow_up_date, follow_up_time,
consultation_fee, additional_charges, total_amount,
payment_status, payment_method, payment_date
```

**reports** - Medical reports uploaded by patients/labs
```sql
id, visit_id, patient_id, doctor_firebase_uid,
file_name, file_size, file_type, file_url, storage_path,
upload_token, uploaded_at, test_type, notes
```

### AI Analysis Tables

**ai_analysis_queue** - Background processing queue
```sql
id, report_id, visit_id, patient_id, doctor_firebase_uid,
status (pending/processing/completed/failed),
priority, retry_count, max_retries, error_message,
queued_at, started_at, completed_at
```

**ai_document_analysis** - Single document analysis results
```sql
id, report_id, visit_id, patient_id, doctor_firebase_uid,
analysis_type, model_used, confidence_score, raw_analysis,
document_summary, clinical_significance, key_findings (JSONB),
actionable_insights, patient_communication, analyzed_at
```

**ai_consolidated_analysis** - Multi-document analysis
```sql
id, visit_id, patient_id, doctor_firebase_uid,
report_ids (ARRAY), document_count, overall_assessment,
clinical_picture, integrated_recommendations,
consolidated_findings (JSONB), priority_actions (JSONB)
```

**patient_history_analysis** - Comprehensive patient history
```sql
id, patient_id, doctor_firebase_uid, total_visits, total_reports,
comprehensive_summary, medical_trajectory,
chronic_conditions (ARRAY), recurring_patterns (ARRAY),
treatment_effectiveness, risk_factors (ARRAY),
recommendations (ARRAY), significant_findings (ARRAY)
```

### Support Tables

**report_upload_links** - Temporary upload links for patients
```sql
id, visit_id, patient_id, doctor_firebase_uid,
upload_token, expires_at, created_at
```

**notifications** - In-app notifications
```sql
id, doctor_firebase_uid, title, message, notification_type,
priority, is_read, read_at, metadata (JSONB), created_at
```

**lab_contacts** - External lab contacts
```sql
id, doctor_firebase_uid, lab_type (pathology/radiology),
lab_name, contact_phone, contact_email, is_active
```

**lab_report_requests** - Lab report upload requests
```sql
id, visit_id, patient_id, doctor_firebase_uid, lab_contact_id,
patient_name, report_type, test_name, instructions,
status, request_token, expires_at
```

**pdf_templates** - Custom PDF templates
```sql
id, doctor_firebase_uid, template_name, file_name,
file_url, file_size, storage_path, is_active
```

**handwritten_visit_notes** - Handwritten visit notes
```sql
id, visit_id, patient_id, doctor_firebase_uid, template_id,
original_template_url, handwritten_pdf_url,
handwritten_pdf_filename, sent_via_whatsapp
```

### Pharmacy Tables

**pharmacy_users** - Pharmacy accounts
```sql
id, name, phone, hospital_name, username, password_hash, is_active
```

**pharmacy_prescriptions** - Doctor prescriptions
```sql
id, pharmacy_id, visit_id, patient_id, doctor_firebase_uid,
doctor_name, patient_name, patient_phone, medications_text,
medications_json (JSONB), status, total_estimated_amount
```

**pharmacy_inventory** - Medicine inventory
```sql
id, pharmacy_id, medicine_name, sku, batch_number,
expiry_date, stock_quantity, reorder_level, unit,
purchase_price, selling_price, supplier_id
```

**pharmacy_invoices** - Sales invoices
```sql
id, pharmacy_id, prescription_id, invoice_number,
items (JSONB), subtotal, tax, discount, total_amount,
payment_method, status
```

**pharmacy_suppliers** - Supplier management
```sql
id, pharmacy_id, name, contact_person, phone, email,
address, notes, is_active
```

### Front Desk Tables

**frontdesk_users** - Front desk accounts
```sql
id, name, phone, hospital_name, username, password_hash, is_active
```

**appointments** - Scheduled appointments
```sql
id, doctor_firebase_uid, patient_id, frontdesk_user_id,
appointment_date, appointment_time, duration_minutes,
status (scheduled/confirmed/completed/cancelled),
appointment_type, notes, patient_notes
```

### Database Indexes (for performance)

Key indexes have been created for:
- Foreign key relationships
- Frequently queried fields (doctor_firebase_uid, patient_id, visit_id)
- Date fields (visit_date, follow_up_date, created_at)
- Status fields for filtering

See `migrations/comprehensive_database_indexes.sql` for complete index definitions.

---

## 📝 Usage Examples

### Example 1: Complete Patient Visit Workflow

```python
import requests

BASE_URL = "http://localhost:5000"
TOKEN = "your_firebase_jwt_token"
headers = {"Authorization": f"Bearer {TOKEN}"}

# 1. Register a new patient
patient_data = {
    "first_name": "Alice",
    "last_name": "Johnson",
    "phone": "9876543210",
    "date_of_birth": "1985-03-20",
    "gender": "Female",
    "blood_group": "A+",
    "medical_history": "No significant history"
}
response = requests.post(f"{BASE_URL}/patients/register", 
                         json=patient_data, headers=headers)
patient = response.json()["patient"]
patient_id = patient["id"]

# 2. Create a visit
visit_data = {
    "visit_date": "2025-11-09",
    "visit_type": "Consultation",
    "chief_complaint": "Fever and cough",
    "symptoms": "Fever 101°F, dry cough for 3 days",
    "vitals": {
        "temperature": "101.2",
        "blood_pressure": "118/76",
        "pulse": "88"
    },
    "diagnosis": "Upper respiratory tract infection",
    "medications": "Paracetamol 500mg TDS, Azithromycin 500mg OD",
    "follow_up_date": "2025-11-16",
    "consultation_fee": 500,
    "payment_status": "paid",
    "payment_method": "upi"
}
response = requests.post(f"{BASE_URL}/patients/{patient_id}/visits",
                         json=visit_data, headers=headers)
visit = response.json()["visit"]
visit_id = visit["id"]

# 3. Generate report upload link
response = requests.post(f"{BASE_URL}/visits/{visit_id}/generate-report-link",
                         headers=headers)
upload_link = response.json()["upload_link"]
upload_token = response.json()["upload_token"]

# 4. Send WhatsApp link to patient
whatsapp_data = {
    "patient_phone": "9876543210",
    "message": "Please upload your test reports"
}
response = requests.post(f"{BASE_URL}/visits/{visit_id}/send-whatsapp-report-link",
                         json=whatsapp_data, headers=headers)

# Patient uploads reports via the web interface...
# AI analysis happens automatically in background

# 5. Check AI analysis results (after some time)
response = requests.get(f"{BASE_URL}/visits/{visit_id}/analyses",
                        headers=headers)
analyses = response.json()

# 6. Generate visit PDF report
response = requests.post(f"{BASE_URL}/visits/{visit_id}/generate-report",
                         headers=headers)
pdf_url = response.json()["file_url"]
```

### Example 2: Check Today's Appointments

```python
from datetime import date

today = date.today().isoformat()  # "2025-11-09"

# Get appointments for today
response = requests.get(f"{BASE_URL}/calendar/appointments/{today}",
                        headers=headers)
appointments = response.json()

for apt in appointments:
    print(f"Patient: {apt['patient_first_name']} {apt['patient_last_name']}")
    print(f"Phone: {apt['patient_phone']}")
    print(f"Complaint: {apt['chief_complaint']}")
    print(f"Follow-up time: {apt.get('follow_up_time', 'Not specified')}")
    print("---")
```

### Example 3: Get Unread Notifications (for mobile badge)

```python
# Get unread count
response = requests.get(f"{BASE_URL}/notifications/unread/count",
                        headers=headers)
unread_count = response.json()["unread_count"]
print(f"You have {unread_count} unread notifications")

# Get all unread notifications
response = requests.get(f"{BASE_URL}/notifications?status=unread",
                        headers=headers)
notifications = response.json()

for notif in notifications:
    print(f"[{notif['notification_type']}] {notif['title']}")
    print(f"  {notif['message']}")
    
    # Mark as read
    requests.put(f"{BASE_URL}/notifications/{notif['id']}/read",
                 headers=headers)
```

### Example 4: Monthly Earnings Report

```python
# Get November 2025 earnings
response = requests.get(f"{BASE_URL}/earnings/monthly/2025/11",
                        headers=headers)
earnings = response.json()

print(f"Period: {earnings['period']}")
print(f"Total Visits: {earnings['total_visits']}")
print(f"Total Earnings: ₹{earnings['total_earnings']}")
print(f"Pending Payments: ₹{earnings['pending_amount']}")
print("\nPayment Methods:")
for method, amount in earnings['payment_methods'].items():
    print(f"  {method}: ₹{amount}")
```

### Example 5: Lab Report Request Workflow

```python
# 1. Add lab contact (one-time setup)
lab_data = {
    "lab_type": "pathology",
    "lab_name": "City Diagnostics",
    "contact_phone": "1234567890",
    "contact_email": "lab@example.com"
}
response = requests.post(f"{BASE_URL}/lab-contacts",
                         json=lab_data, headers=headers)
lab_contact_id = response.json()["lab_contact"]["id"]

# 2. Request lab report upload
request_data = {
    "lab_contact_id": lab_contact_id,
    "test_name": "Complete Blood Count",
    "instructions": "Fasting sample required"
}
response = requests.post(f"{BASE_URL}/visits/{visit_id}/request-lab-report",
                         json=request_data, headers=headers)

# Lab receives WhatsApp with upload link
# Lab uploads report via web interface
# Doctor receives notification when upload complete
```

### Example 6: Pharmacy Integration

```python
# Pharmacy claims a prescription
pharmacy_id = 1
prescription_id = 42

response = requests.post(
    f"{BASE_URL}/pharmacy/{pharmacy_id}/prescriptions/{prescription_id}/claim",
    headers={"Authorization": f"Bearer {pharmacy_token}"}
)

# Update prescription status
status_data = {"status": "preparing"}
response = requests.post(
    f"{BASE_URL}/pharmacy/{pharmacy_id}/prescriptions/{prescription_id}/status",
    json=status_data,
    headers={"Authorization": f"Bearer {pharmacy_token}"}
)

# Generate invoice
invoice_data = {
    "items": [
        {
            "medicine_name": "Paracetamol 500mg",
            "quantity": 30,
            "unit_price": 2.00,
            "total": 60.00
        },
        {
            "medicine_name": "Azithromycin 500mg",
            "quantity": 6,
            "unit_price": 25.00,
            "total": 150.00
        }
    ],
    "payment_method": "cash"
}
response = requests.post(
    f"{BASE_URL}/pharmacy/{pharmacy_id}/prescriptions/{prescription_id}/invoice",
    json=invoice_data,
    headers={"Authorization": f"Bearer {pharmacy_token}"}
)
invoice = response.json()
print(f"Invoice #{invoice['invoice_number']}: ₹{invoice['total_amount']}")
```

---

## ⚡ Performance & Scalability

### Performance Optimizations Implemented

#### 1. **Connection Pooling**
```python
# connection_pool.py
- Maintains pool of 10 reusable Supabase connections
- Reduces connection overhead by ~70%
- Thread-safe singleton pattern
```

#### 2. **LRU Cache with TTL**
```python
# optimized_cache.py
- Caches frequently accessed data (patients, visits, templates)
- Max 1000 items, 5-minute TTL
- Typical cache hit rate: 60-80%
- Reduces database queries significantly
```

#### 3. **Async/Await Pattern**
```python
# All database operations use async/await
- Non-blocking I/O operations
- Better concurrency under load
- Handles multiple requests simultaneously
```

#### 4. **Background Processing**
```python
# ai_analysis_processor.py
- AI analysis runs in background queue
- Prevents API timeout issues
- Automatic retry on failures
- Priority-based processing
```

#### 5. **Query Optimization**
```python
# N+1 query fixes in migrations/fix_n_plus_one_queries.sql
- JOINs instead of multiple queries
- Reduced query count by 80-90% for complex endpoints
- Proper indexing on foreign keys
```

#### 6. **File Operations**
```python
# async_file_downloader.py
- Async file downloads from Supabase Storage
- Parallel file processing
- Chunked uploads for large files
```

### Performance Metrics

Based on `PERFORMANCE_ANALYSIS_REPORT.md`:

**Before Optimization:**
- Average response time: 800-1200ms
- Database connections: 50-100 per request
- Cache hit rate: 0%
- Concurrent users supported: ~20

**After Optimization:**
- Average response time: 150-300ms (75% improvement)
- Database connections: 5-10 per request (90% reduction)
- Cache hit rate: 60-80%
- Concurrent users supported: ~200+

### Load Testing Results

```bash
# Example: 100 concurrent users
ab -n 1000 -c 100 -H "Authorization: Bearer token" \
   http://localhost:5000/patients

Results:
- Requests per second: 180-220
- Mean response time: 280ms
- 95th percentile: 450ms
- 99th percentile: 650ms
- Failed requests: 0%
```

### Scalability Recommendations

**Current Capacity:**
- Single instance: 200-300 concurrent users
- Database: 10,000+ patients
- Storage: Unlimited (Supabase)

**For Higher Load:**
1. **Horizontal Scaling**: Deploy multiple app instances behind load balancer
2. **Database Read Replicas**: Use Supabase read replicas for read-heavy operations
3. **CDN**: Use Cloudflare/Cloudfront for static assets and PDF files
4. **Redis Cache**: Replace in-memory cache with Redis for shared cache
5. **Message Queue**: Use RabbitMQ/Celery for more robust background processing

---

## 🚀 Deployment

### Development Deployment

```bash
# Run locally with auto-reload
python app.py

# Or with uvicorn
uvicorn app:app --host 0.0.0.0 --port 5000 --reload
```

### Production Deployment Options

#### Option 1: Google Cloud Run (Recommended)

See complete guide: `GCP_COMPLETE_DEPLOYMENT_GUIDE.md`

**Benefits:**
- Serverless, auto-scaling
- Pay only for usage
- Built-in HTTPS
- Managed infrastructure

**Quick Deploy:**
```bash
# Build and deploy
gcloud builds submit --tag gcr.io/PROJECT_ID/backend-app
gcloud run deploy backend-app \
  --image gcr.io/PROJECT_ID/backend-app \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

**Estimated Cost**: $25-100/month depending on traffic

#### Option 2: Traditional Server (VPS/EC2)

```bash
# Install dependencies
pip install -r requirements.txt

# Use Gunicorn with Uvicorn workers
gunicorn -w 4 -k uvicorn.workers.UvicornWorker \
  app:app --bind 0.0.0.0:5000 \
  --access-logfile - \
  --error-logfile -

# With systemd service (production)
sudo systemctl start backend-app
sudo systemctl enable backend-app
```

**Nginx Reverse Proxy:**
```nginx
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Option 3: Docker Deployment

```dockerfile
# See included Dockerfile
docker build -t backend-app .
docker run -p 5000:5000 --env-file .env backend-app
```

### Environment-Specific Configurations

**Production Checklist:**
- [ ] Set `ENVIRONMENT=production` in .env
- [ ] Use strong Supabase service role key
- [ ] Enable HTTPS/SSL
- [ ] Configure CORS properly
- [ ] Set up monitoring (Sentry, CloudWatch)
- [ ] Enable database backups
- [ ] Configure rate limiting
- [ ] Set up logging aggregation
- [ ] Use secrets manager for credentials
- [ ] Enable API key authentication for webhooks

---

## 🧪 Testing

### Manual Testing

**Health Check:**
```bash
curl http://localhost:5000/test
# Response: {"message": "API is working!", "timestamp": "..."}
```

**Test WhatsApp:**
```bash
curl -X POST http://localhost:5000/test-whatsapp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"phone": "+919876543210", "message": "Test message"}'
```

### Test Scripts Included

```bash
# Test cache performance
python test_cache_lru.py

# Test N+1 query fixes
python test_n_plus_one_fix.py
```

### API Documentation

**Interactive API Docs:**
- Swagger UI: `http://localhost:5000/docs`
- ReDoc: `http://localhost:5000/redoc`

### Postman Collection

Import the following base URL and endpoints into Postman:
- Base URL: `http://localhost:5000`
- Add Authorization header: `Bearer {{firebase_token}}`
- Test all endpoints with sample data

---

## 🔍 Troubleshooting

### Common Issues

**Issue: "Database connection failed"**
```bash
# Check Supabase credentials
echo $SUPABASE_URL
echo $SUPABASE_KEY

# Test connection
python -c "from database import DatabaseManager; db = DatabaseManager()"
```

**Issue: "Firebase authentication error"**
```bash
# Verify Firebase admin SDK file exists
ls doctor-*-firebase-adminsdk-*.json

# Check Firebase project ID
echo $FIREBASE_PROJECT_ID
```

**Issue: "WhatsApp messages not sending"**
```bash
# Verify Twilio credentials
echo $TWILIO_ACCOUNT_SID
echo $TWILIO_AUTH_TOKEN

# Test Twilio connection
python -c "from twilio.rest import Client; client = Client('SID', 'TOKEN')"
```

**Issue: "AI analysis not working"**
```bash
# Check Google AI API key
echo $GOOGLE_API_KEY

# Test AI service
python -c "import google.generativeai as genai; genai.configure(api_key='KEY')"
```

**Issue: "High memory usage"**
```bash
# Clear cache
# The cache auto-clears but you can restart the app

# Check connection pool
# Ensure proper cleanup in connection_pool.py

# Monitor with htop or Task Manager
```

---

## 📚 Additional Resources

### Documentation Files

- `GCP_COMPLETE_DEPLOYMENT_GUIDE.md` - Complete Google Cloud deployment guide
- `PERFORMANCE_ANALYSIS_REPORT.md` - Performance optimization analysis
- `migrations/README_N_PLUS_ONE_FIX.md` - Database query optimization guide
- `current_schema.sql` - Complete database schema
- `performance_indexes.sql` - Database indexes for performance

### Migration Files

- `migrations/comprehensive_database_indexes.sql` - All database indexes
- `migrations/fix_n_plus_one_queries.sql` - Optimized query implementations

### Architecture Diagrams

- `app_flow_diagram.puml` - PlantUML system architecture diagram

---

## 🤝 Contributing

This is a production backend for a medical practice. Key areas for contribution:

1. **Performance Improvements**: Cache optimization, query optimization
2. **New Features**: Additional integrations, reporting features
3. **Security Enhancements**: Rate limiting, input validation
4. **Documentation**: API examples, integration guides
5. **Testing**: Unit tests, integration tests, load tests

### Development Setup

```bash
# Fork and clone
git clone <your-fork>
cd backend_app

# Create feature branch
git checkout -b feature/your-feature

# Make changes and test
python app.py

# Commit and push
git add .
git commit -m "Add: your feature description"
git push origin feature/your-feature
```

---

## 📄 License

This is proprietary software for medical practice management. All rights reserved.

---

## 📞 Support & Contact

For issues, questions, or feature requests:

1. **Check Documentation**: Review this README and related docs
2. **Check Logs**: Application logs show detailed error information
3. **Check Database**: Verify data integrity in Supabase dashboard
4. **Check Services**: Ensure Firebase, Twilio, Google AI are configured
5. **Performance Issues**: See `PERFORMANCE_ANALYSIS_REPORT.md`

---

## 📊 System Statistics

**Current Version:** 2.0  
**Total Lines of Code:** ~15,000+  
**Total Endpoints:** 150+  
**Database Tables:** 28  
**Supported Roles:** 4 (Doctor, Pharmacy, Lab, Front Desk)  
**AI Models Used:** Google Gemini 2.0 Flash  
**Average API Response Time:** 150-300ms  
**Supported Concurrent Users:** 200+  

---

**Built with ❤️ using:**
- FastAPI 0.104.1
- Supabase (PostgreSQL)
- Firebase Authentication
- Google Gemini AI
- Twilio WhatsApp API
- Python 3.11+

**Last Updated:** November 9, 2025
