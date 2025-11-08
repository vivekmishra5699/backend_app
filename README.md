# Medical Practice Management System - Backend API

A comprehensive FastAPI-based backend system for managing medical practices, including patient management, visit tracking, report analysis, calendar functionality, and notifications.

## 🏗️ System Architecture

```
├── app.py                      # Main FastAPI application with all endpoints
├── database.py                 # Database abstraction layer (Supabase/PostgreSQL)
├── firebase_manager.py         # Firebase authentication management
├── whatsapp_service.py         # WhatsApp messaging integration (Twilio)
├── ai_analysis_service.py      # AI-powered medical report analysis
├── ai_analysis_processor.py    # Background AI processing worker
├── pdf_generator.py            # PDF generation for reports and visits
├── visit_report_generator.py   # Visit report generation utilities
└── requirements.txt            # Python dependencies
```

## 📋 Table of Contents

- [Installation & Setup](#installation--setup)
- [Environment Variables](#environment-variables)
- [Modules Overview](#modules-overview)
- [API Endpoints](#api-endpoints)
- [Authentication](#authentication)
- [Usage Examples](#usage-examples)
- [Database Schema](#database-schema)

## 🚀 Installation & Setup

### Prerequisites
- Python 3.8+
- Supabase account and project
- Firebase project with authentication enabled
- Twilio account (for WhatsApp messaging)
- GOOGLE_AI API key (for AI analysis)

### Installation Steps

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd backend_app
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables** (see [Environment Variables](#environment-variables))

4. **Run the database schema** (see [Database Schema](#database-schema))

5. **Start the development server:**
   ```bash
   python app.py
   # or
   uvicorn app:app --host 127.0.0.1 --port 5000 --reload
   ```

The API will be available at: `http://localhost:5000`

## 🔧 Environment Variables

Create a `.env` file in the root directory with the following variables:

```env
# Supabase Configuration
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key

# Firebase Configuration
FIREBASE_PROJECT_ID=your_firebase_project_id

# Twilio WhatsApp Configuration
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+your_twilio_whatsapp_number

# OpenAI Configuration
GOOGLE_API_KEY=your_openai_api_key
```

## 📦 Modules Overview

### 1. **app.py** - Main Application
The core FastAPI application containing all API endpoints organized by functionality:
- **Authentication**: Doctor registration, login, profile management
- **Patient Management**: CRUD operations for patients
- **Visit Management**: Medical visit tracking and management
- **Report Management**: Medical report uploads and analysis
- **Calendar System**: Follow-up appointment scheduling
- **Notification System**: In-app notifications for doctors
- **AI Analysis**: Automated medical report analysis
- **PDF Generation**: Report and visit document generation

### 2. **database.py** - Database Layer
Abstraction layer for all database operations using Supabase/PostgreSQL:
- Connection management with connection pooling
- CRUD operations for all entities (doctors, patients, visits, reports)
- Complex queries for analytics and reporting
- Async/await pattern for non-blocking database operations

### 3. **firebase_manager.py** - Authentication
Firebase authentication integration:
- JWT token validation and verification
- User authentication middleware
- Firebase Admin SDK integration

### 4. **whatsapp_service.py** - Messaging
WhatsApp messaging service using Twilio:
- Send text messages and media
- Report upload links delivery
- Visit summaries and notifications
- Message status tracking

### 5. **ai_analysis_service.py** - AI Analysis
AI-powered medical report analysis using OpenAI:
- Automated report interpretation
- Medical insights generation
- Patient history analysis
- Structured medical data extraction

### 6. **ai_analysis_processor.py** - Background Processing
Background worker for processing AI analysis tasks:
- Queue-based task processing
- Async analysis execution
- Error handling and retry logic

### 7. **pdf_generator.py** - Document Generation
PDF generation utilities:
- Visit summaries and reports
- Patient profiles
- Medical certificates
- Customizable templates

## 🌐 API Endpoints

### Authentication Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/register` | Doctor registration | ❌ |
| `POST` | `/login` | Doctor login | ❌ |
| `POST` | `/validate-token` | Validate Firebase token | ❌ |
| `GET` | `/profile` | Get doctor profile | ✅ |
| `PUT` | `/profile` | Update doctor profile | ✅ |

### Patient Management

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/patients/register` | Register new patient | ✅ |
| `GET` | `/patients` | Get all patients | ✅ |
| `GET` | `/patients/{patient_id}` | Get patient details | ✅ |
| `PUT` | `/patients/{patient_id}` | Update patient | ✅ |
| `DELETE` | `/patients/{patient_id}` | Delete patient | ✅ |
| `GET` | `/patients/{patient_id}/profile` | Get patient with visits | ✅ |

### Visit Management

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/patients/{patient_id}/visits` | Create new visit | ✅ |
| `GET` | `/patients/{patient_id}/visits` | Get patient visits | ✅ |
| `GET` | `/visits/{visit_id}` | Get visit details | ✅ |
| `PUT` | `/visits/{visit_id}` | Update visit | ✅ |
| `DELETE` | `/visits/{visit_id}` | Delete visit | ✅ |
| `POST` | `/visits/{visit_id}/upload-handwritten-pdf` | Upload handwritten notes | ✅ |

### Report Management

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/visits/{visit_id}/generate-report-link` | Generate upload link | ✅ |
| `POST` | `/visits/{visit_id}/send-report-link-whatsapp` | Send link via WhatsApp | ✅ |
| `GET` | `/upload-reports/{upload_token}` | Patient upload page | ❌ |
| `POST` | `/api/upload-reports` | Upload reports (patients) | ❌ |
| `GET` | `/visits/{visit_id}/reports` | Get visit reports | ✅ |

### Calendar System

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/calendar/current` | Get current month calendar | ✅ |
| `GET` | `/calendar/{year}/{month}` | Get specific month calendar | ✅ |
| `GET` | `/calendar/appointments/{date}` | Get appointments for date | ✅ |
| `GET` | `/calendar/upcoming` | Get upcoming appointments | ✅ |
| `GET` | `/calendar/summary` | Get calendar summary | ✅ |

### Notification System

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/notifications` | Get notifications | ✅ |
| `GET` | `/notifications/summary` | Get notification summary | ✅ |
| `GET` | `/notifications/unread/count` | Get unread count | ✅ |
| `PUT` | `/notifications/{notification_id}/read` | Mark as read | ✅ |
| `PUT` | `/notifications/mark-all-read` | Mark all as read | ✅ |
| `DELETE` | `/notifications/{notification_id}` | Delete notification | ✅ |

### AI Analysis

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/reports/{report_id}/analysis` | Get report analysis | ✅ |
| `POST` | `/reports/{report_id}/analyze` | Trigger analysis | ✅ |
| `GET` | `/patients/{patient_id}/analyses` | Get patient analyses | ✅ |
| `POST` | `/patients/{patient_id}/analyze-comprehensive-history` | Analyze patient history | ✅ |
| `GET` | `/ai-analysis-summary` | Get AI analysis summary | ✅ |

### PDF Generation

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/visits/{visit_id}/generate-pdf` | Generate visit PDF | ✅ |
| `POST` | `/patients/{patient_id}/send-profile-whatsapp` | Send profile via WhatsApp | ✅ |
| `POST` | `/pdf-templates/upload` | Upload PDF template | ✅ |
| `GET` | `/pdf-templates` | Get PDF templates | ✅ |

## 🔐 Authentication

The API uses Firebase JWT tokens for authentication. Include the token in the Authorization header:

```
Authorization: Bearer <firebase_jwt_token>
```

### Getting a Firebase Token
1. Authenticate user in your frontend (Flutter app)
2. Get the ID token from Firebase Auth
3. Include it in API requests

## 📝 Usage Examples

### Sample API Request Format

Here's a complete example of creating a new patient:

**Request:**
```http
POST http://localhost:5000/patients/register
Content-Type: application/json
Authorization: Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Ij...

{
  "first_name": "John",
  "last_name": "Doe",
  "email": "john.doe@example.com",
  "phone": "1234567890",
  "date_of_birth": "1990-05-15",
  "gender": "Male",
  "address": "123 Main St, City, State 12345",
  "emergency_contact": "Jane Doe - 0987654321",
  "medical_history": "No known allergies, previous surgery in 2020"
}
```

**Response:**
```json
{
  "message": "Patient registered successfully",
  "patient": {
    "id": 42,
    "first_name": "John",
    "last_name": "Doe",
    "email": "john.doe@example.com",
    "phone": "1234567890",
    "date_of_birth": "1990-05-15",
    "gender": "Male",
    "address": "123 Main St, City, State 12345",
    "emergency_contact": "Jane Doe - 0987654321",
    "medical_history": "No known allergies, previous surgery in 2020",
    "doctor_firebase_uid": "jxXGiJNiYKRLWy3i6wmNYmtAgjn2",
    "created_at": "2025-08-20T10:30:00.000Z",
    "updated_at": "2025-08-20T10:30:00.000Z"
  }
}
```

### Common Usage Patterns

#### 1. Get Unread Notifications Count (for Flutter badge)
```http
GET /notifications/unread/count
Authorization: Bearer <token>

Response:
{
  "unread_count": 5,
  "doctor_uid": "jxXGiJNiYKRLWy3i6wmNYmtAgjn2"
}
```

#### 2. Get Today's Calendar Appointments
```http
GET /calendar/appointments/2025-08-20
Authorization: Bearer <token>

Response:
[
  {
    "visit_id": 39,
    "patient_id": 8,
    "patient_first_name": "rakesh",
    "patient_last_name": "dandugula",
    "patient_phone": "7207167087",
    "follow_up_date": "2025-08-20",
    "follow_up_time": null,
    "original_visit_date": "2025-08-19",
    "visit_type": "Emergency",
    "chief_complaint": "chest pain",
    "phone": "7207167087",
    "notes": null,
    "is_overdue": false,
    "days_until_appointment": 0
  }
]
```

#### 3. Mark Notification as Read
```http
PUT /notifications/123/read
Authorization: Bearer <token>

Response:
{
  "message": "Notification marked as read",
  "notification_id": 123
}
```

## 🗄️ Database Schema

### Required Tables
Run these SQL commands in your Supabase SQL editor:

```sql
-- Core Tables (should already exist)
-- doctors, patients, visits, reports, ai_analysis_queue, ai_analysis_results

-- New Tables for Enhanced Features

-- 1. Notifications Table
CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    doctor_firebase_uid TEXT NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    notification_type VARCHAR(50) DEFAULT 'report_upload',
    priority INTEGER DEFAULT 1,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    read_at TIMESTAMP WITH TIME ZONE NULL,
    metadata JSONB NULL
);

-- 2. PDF Templates Table (if using custom templates)
CREATE TABLE pdf_templates (
    id SERIAL PRIMARY KEY,
    doctor_firebase_uid TEXT NOT NULL,
    template_name VARCHAR(255) NOT NULL,
    file_url TEXT NOT NULL,
    file_size INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Report Upload Links Table
CREATE TABLE report_upload_links (
    id SERIAL PRIMARY KEY,
    visit_id INTEGER REFERENCES visits(id),
    patient_id INTEGER REFERENCES patients(id),
    doctor_firebase_uid TEXT NOT NULL,
    upload_token TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

## 🔧 Configuration & Deployment

### Development
```bash
python app.py
# Server runs on http://localhost:5000
```

### Production Deployment
1. Set environment variables on your hosting platform
2. Use a production WSGI server like Gunicorn:
   ```bash
   gunicorn -w 4 -k uvicorn.workers.UvicornWorker app:app --bind 0.0.0.0:5000
   ```

### Health Check
```http
GET /test
# Returns: {"message": "API is working!", "timestamp": "..."}
```

## 🛠️ Development Tools

### Testing Scripts
- `test_notifications.py` - Test notification system
- `test_calendar_direct.py` - Test calendar functionality
- `check_database_appointments.py` - Verify appointment data

### Database Management
- `notifications_schema.sql` - Complete notification schema
- Built-in database migration support through Supabase

## 📱 Frontend Integration

This backend is designed to work with Flutter mobile applications. Key integration points:

1. **Authentication**: Use Firebase Auth in Flutter, send JWT tokens to backend
2. **Real-time Updates**: Use Supabase realtime subscriptions for live data
3. **File Uploads**: Handle multipart form data for report uploads
4. **Push Notifications**: Integrate with Firebase Cloud Messaging for real-time alerts
5. **Offline Support**: Cache API responses for offline functionality

## 🔍 Error Handling

All endpoints return standardized error responses:

```json
{
  "detail": "Error message description",
  "status_code": 400
}
```

Common HTTP status codes:
- `200` - Success
- `400` - Bad Request (validation errors)
- `401` - Unauthorized (invalid/missing token)
- `403` - Forbidden (insufficient permissions)
- `404` - Not Found
- `422` - Unprocessable Entity (data validation failed)
- `500` - Internal Server Error

## 📞 Support

For issues or questions:
1. Check the console logs for detailed error messages
2. Verify environment variables are correctly set
3. Ensure database tables are created properly
4. Confirm Firebase authentication is working

---

**Built with ❤️ using FastAPI, Supabase, Firebase, and modern Python async/await patterns.**

# Medical Practice Management System - Backend API

A comprehensive FastAPI-based backend system for managing medical practices, including patient management, visit tracking, report analysis, calendar functionality, and notifications.

## 🏗️ System Architecture

```
├── app.py                      # Main FastAPI application with all endpoints
├── database.py                 # Database abstraction layer (Supabase/PostgreSQL)
├── firebase_manager.py         # Firebase authentication management
├── whatsapp_service.py         # WhatsApp messaging integration (Twilio)
├── ai_analysis_service.py      # AI-powered medical report analysis
├── ai_analysis_processor.py    # Background AI processing worker
├── pdf_generator.py            # PDF generation for reports and visits
├── visit_report_generator.py   # Visit report generation utilities
└── requirements.txt            # Python dependencies
```

## 📋 Table of Contents

- [Installation & Setup](#installation--setup)
- [Environment Variables](#environment-variables)
- [Modules Overview](#modules-overview)
- [API Endpoints](#api-endpoints)
- [Authentication](#authentication)
- [Usage Examples](#usage-examples)
- [Database Schema](#database-schema)

## 🚀 Installation & Setup

### Prerequisites
- Python 3.8+
- Supabase account and project
- Firebase project with authentication enabled
- Twilio account (for WhatsApp messaging)
- OpenAI API key (for AI analysis)

### Installation Steps

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd backend_app
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables** (see [Environment Variables](#environment-variables))

4. **Run the database schema** (see [Database Schema](#database-schema))

5. **Start the development server:**
   ```bash
   python app.py
   # or
   uvicorn app:app --host 127.0.0.1 --port 5000 --reload
   ```

The API will be available at: `http://localhost:5000`

## 🔧 Environment Variables

Create a `.env` file in the root directory with the following variables:

```env
# Supabase Configuration
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key

# Firebase Configuration
FIREBASE_PROJECT_ID=your_firebase_project_id

# Twilio WhatsApp Configuration
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+your_twilio_whatsapp_number

# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key
```

## 📦 Modules Overview

### 1. **app.py** - Main Application
The core FastAPI application containing all API endpoints organized by functionality:
- **Authentication**: Doctor registration, login, profile management
- **Patient Management**: CRUD operations for patients
- **Visit Management**: Medical visit tracking and management
- **Report Management**: Medical report uploads and analysis
- **Calendar System**: Follow-up appointment scheduling
- **Notification System**: In-app notifications for doctors
- **Lab Management**: External lab integration for pathology and radiology reports
- **AI Analysis**: Automated medical report analysis
- **PDF Generation**: Report and visit document generation

### 2. **database.py** - Database Layer
Abstraction layer for all database operations using Supabase/PostgreSQL:
- Connection management with connection pooling
- CRUD operations for all entities (doctors, patients, visits, reports)
- Complex queries for analytics and reporting
- Async/await pattern for non-blocking database operations

### 3. **firebase_manager.py** - Authentication
Firebase authentication integration:
- JWT token validation and verification
- User authentication middleware
- Firebase Admin SDK integration

### 4. **whatsapp_service.py** - Messaging
WhatsApp messaging service using Twilio:
- Send text messages and media
- Report upload links delivery
- Visit summaries and notifications
- Message status tracking

### 5. **ai_analysis_service.py** - AI Analysis
AI-powered medical report analysis using OpenAI:
- Automated report interpretation
- Medical insights generation
- Patient history analysis
- Structured medical data extraction

### 6. **ai_analysis_processor.py** - Background Processing
Background worker for processing AI analysis tasks:
- Queue-based task processing
- Async analysis execution
- Error handling and retry logic

### 7. **pdf_generator.py** - Document Generation
PDF generation utilities:
- Visit summaries and reports
- Patient profiles
- Medical certificates
- Customizable templates

## 🌐 API Endpoints

### Authentication Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/register` | Doctor registration | ❌ |
| `POST` | `/login` | Doctor login | ❌ |
| `POST` | `/validate-token` | Validate Firebase token | ❌ |
| `GET` | `/profile` | Get doctor profile | ✅ |
| `PUT` | `/profile` | Update doctor profile | ✅ |

### Patient Management

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/patients/register` | Register new patient | ✅ |
| `GET` | `/patients` | Get all patients | ✅ |
| `GET` | `/patients/{patient_id}` | Get patient details | ✅ |
| `PUT` | `/patients/{patient_id}` | Update patient | ✅ |
| `DELETE` | `/patients/{patient_id}` | Delete patient | ✅ |
| `GET` | `/patients/{patient_id}/profile` | Get patient with visits | ✅ |

### Visit Management

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/patients/{patient_id}/visits` | Create new visit | ✅ |
| `GET` | `/patients/{patient_id}/visits` | Get patient visits | ✅ |
| `GET` | `/visits/{visit_id}` | Get visit details | ✅ |
| `PUT` | `/visits/{visit_id}` | Update visit | ✅ |
| `DELETE` | `/visits/{visit_id}` | Delete visit | ✅ |
| `POST` | `/visits/{visit_id}/upload-handwritten-pdf` | Upload handwritten notes | ✅ |

### Report Management

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/visits/{visit_id}/generate-report-link` | Generate upload link | ✅ |
| `POST` | `/visits/{visit_id}/send-report-link-whatsapp` | Send link via WhatsApp | ✅ |
| `GET` | `/upload-reports/{upload_token}` | Patient upload page | ❌ |
| `POST` | `/api/upload-reports` | Upload reports (patients) | ❌ |
| `GET` | `/visits/{visit_id}/reports` | Get visit reports | ✅ |

### Calendar System

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/calendar/current` | Get current month calendar | ✅ |
| `GET` | `/calendar/{year}/{month}` | Get specific month calendar | ✅ |
| `GET` | `/calendar/appointments/{date}` | Get appointments for date | ✅ |
| `GET` | `/calendar/upcoming` | Get upcoming appointments | ✅ |
| `GET` | `/calendar/summary` | Get calendar summary | ✅ |

### Notification System

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/notifications` | Get notifications | ✅ |
| `GET` | `/notifications/summary` | Get notification summary | ✅ |
| `GET` | `/notifications/unread/count` | Get unread count | ✅ |
| `PUT` | `/notifications/{notification_id}/read` | Mark as read | ✅ |
| `PUT` | `/notifications/mark-all-read` | Mark all as read | ✅ |
| `DELETE` | `/notifications/{notification_id}` | Delete notification | ✅ |

### Lab Management

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/lab-contacts` | Create lab contact | ✅ |
| `GET` | `/lab-contacts` | Get lab contacts | ✅ |
| `PUT` | `/lab-contacts/{contact_id}` | Update lab contact | ✅ |
| `DELETE` | `/lab-contacts/{contact_id}` | Delete lab contact | ✅ |
| `POST` | `/visits/{visit_id}/request-lab-report` | Request lab report upload | ✅ |
| `POST` | `/lab-login` | Lab technician login | ❌ |
| `GET` | `/lab-dashboard/{phone}` | Lab technician dashboard | ❌ |
| `GET` | `/lab-upload/{request_token}` | Lab report upload page | ❌ |
| `POST` | `/api/lab-upload-reports` | Lab report file upload | ❌ |

### AI Analysis

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/reports/{report_id}/analysis` | Get report analysis | ✅ |
| `POST` | `/reports/{report_id}/analyze` | Trigger analysis | ✅ |
| `GET` | `/patients/{patient_id}/analyses` | Get patient analyses | ✅ |
| `POST` | `/patients/{patient_id}/analyze-comprehensive-history` | Analyze patient history | ✅ |
| `GET` | `/ai-analysis-summary` | Get AI analysis summary | ✅ |

### PDF Generation

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `GET` | `/visits/{visit_id}/generate-pdf` | Generate visit PDF | ✅ |
| `POST` | `/patients/{patient_id}/send-profile-whatsapp` | Send profile via WhatsApp | ✅ |
| `POST` | `/pdf-templates/upload` | Upload PDF template | ✅ |
| `GET` | `/pdf-templates` | Get PDF templates | ✅ |

## 🔐 Authentication

The API uses Firebase JWT tokens for authentication. Include the token in the Authorization header:

```
Authorization: Bearer <firebase_jwt_token>
```

### Getting a Firebase Token
1. Authenticate user in your frontend (Flutter app)
2. Get the ID token from Firebase Auth
3. Include it in API requests

## 📝 Usage Examples

### Sample API Request Format

Here's a complete example of creating a new patient:

**Request:**
```http
POST http://localhost:5000/patients/register
Content-Type: application/json
Authorization: Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Ij...

{
  "first_name": "John",
  "last_name": "Doe",
  "email": "john.doe@example.com",
  "phone": "1234567890",
  "date_of_birth": "1990-05-15",
  "gender": "Male",
  "address": "123 Main St, City, State 12345",
  "emergency_contact": "Jane Doe - 0987654321",
  "medical_history": "No known allergies, previous surgery in 2020"
}
```

**Response:**
```json
{
  "message": "Patient registered successfully",
  "patient": {
    "id": 42,
    "first_name": "John",
    "last_name": "Doe",
    "email": "john.doe@example.com",
    "phone": "1234567890",
    "date_of_birth": "1990-05-15",
    "gender": "Male",
    "address": "123 Main St, City, State 12345",
    "emergency_contact": "Jane Doe - 0987654321",
    "medical_history": "No known allergies, previous surgery in 2020",
    "doctor_firebase_uid": "jxXGiJNiYKRLWy3i6wmNYmtAgjn2",
    "created_at": "2025-08-20T10:30:00.000Z",
    "updated_at": "2025-08-20T10:30:00.000Z"
  }
}
```

### Common Usage Patterns

#### 1. Get Unread Notifications Count (for Flutter badge)
```http
GET /notifications/unread/count
Authorization: Bearer <token>

Response:
{
  "unread_count": 5,
  "doctor_uid": "jxXGiJNiYKRLWy3i6wmNYmtAgjn2"
}
```

#### 2. Get Today's Calendar Appointments
```http
GET /calendar/appointments/2025-08-20
Authorization: Bearer <token>

Response:
[
  {
    "visit_id": 39,
    "patient_id": 8,
    "patient_first_name": "rakesh",
    "patient_last_name": "dandugula",
    "patient_phone": "7207167087",
    "follow_up_date": "2025-08-20",
    "follow_up_time": null,
    "original_visit_date": "2025-08-19",
    "visit_type": "Emergency",
    "chief_complaint": "chest pain",
    "phone": "7207167087",
    "notes": null,
    "is_overdue": false,
    "days_until_appointment": 0
  }
]
```

#### 3. Mark Notification as Read
```http
PUT /notifications/123/read
Authorization: Bearer <token>

Response:
{
  "message": "Notification marked as read",
  "notification_id": 123
}
```

## 🗄️ Database Schema

### Required Tables
Run these SQL commands in your Supabase SQL editor:

```sql
-- Core Tables (should already exist)
-- doctors, patients, visits, reports, ai_analysis_queue, ai_analysis_results

-- New Tables for Enhanced Features

-- 1. Notifications Table
CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    doctor_firebase_uid TEXT NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    notification_type VARCHAR(50) DEFAULT 'report_upload',
    priority INTEGER DEFAULT 1,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    read_at TIMESTAMP WITH TIME ZONE NULL,
    metadata JSONB NULL
);

-- 2. PDF Templates Table (if using custom templates)
CREATE TABLE pdf_templates (
    id SERIAL PRIMARY KEY,
    doctor_firebase_uid TEXT NOT NULL,
    template_name VARCHAR(255) NOT NULL,
    file_url TEXT NOT NULL,
    file_size INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Report Upload Links Table
CREATE TABLE report_upload_links (
    id SERIAL PRIMARY KEY,
    visit_id INTEGER REFERENCES visits(id),
    patient_id INTEGER REFERENCES patients(id),
    doctor_firebase_uid TEXT NOT NULL,
    upload_token TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

## 🔧 Configuration & Deployment

### Development
```bash
python app.py
# Server runs on http://localhost:5000
```

### Production Deployment
1. Set environment variables on your hosting platform
2. Use a production WSGI server like Gunicorn:
   ```bash
   gunicorn -w 4 -k uvicorn.workers.UvicornWorker app:app --bind 0.0.0.0:5000
   ```

### Health Check
```http
GET /test
# Returns: {"message": "API is working!", "timestamp": "..."}
```

## 🛠️ Development Tools

### Testing Scripts
- `test_notifications.py` - Test notification system
- `test_calendar_direct.py` - Test calendar functionality
- `check_database_appointments.py` - Verify appointment data

### Database Management
- `notifications_schema.sql` - Complete notification schema
- Built-in database migration support through Supabase

## 📱 Frontend Integration

This backend is designed to work with Flutter mobile applications. Key integration points:

1. **Authentication**: Use Firebase Auth in Flutter, send JWT tokens to backend
2. **Real-time Updates**: Use Supabase realtime subscriptions for live data
3. **File Uploads**: Handle multipart form data for report uploads
4. **Push Notifications**: Integrate with Firebase Cloud Messaging for real-time alerts
5. **Offline Support**: Cache API responses for offline functionality

## 🔍 Error Handling

All endpoints return standardized error responses:

```json
{
  "detail": "Error message description",
  "status_code": 400
}
```

Common HTTP status codes:
- `200` - Success
- `400` - Bad Request (validation errors)
- `401` - Unauthorized (invalid/missing token)
- `403` - Forbidden (insufficient permissions)
- `404` - Not Found
- `422` - Unprocessable Entity (data validation failed)
- `500` - Internal Server Error

## 📞 Support

For issues or questions:
1. Check the console logs for detailed error messages
2. Verify environment variables are correctly set
3. Ensure database tables are created properly
4. Confirm Firebase authentication is working

---

**Built with ❤️ using FastAPI, Supabase, Firebase, and modern Python async/await patterns.**
