# 🏥 Complete Google Cloud Deployment Guide
## Medical Practice Backend API - Everything on Google Cloud

---

## 📋 **Executive Summary**

This guide provides a **complete, production-ready deployment** of your medical practice backend API entirely on Google Cloud Platform. Nothing external - database, file storage, AI services, and API hosting all on GCP.

### **What You'll Get:**
- ✅ **API Hosting**: Cloud Run (serverless, auto-scaling)
- ✅ **Database**: Cloud SQL for PostgreSQL (fully managed)
- ✅ **File Storage**: Cloud Storage (for PDFs, reports, images)
- ✅ **AI Analysis**: Vertex AI / Google Gemini API
- ✅ **Authentication**: Firebase (Google's own service)
- ✅ **Messaging**: Twilio WhatsApp (integration via Cloud Run)

### **Total Estimated Monthly Cost:**
- **Small Practice (10-20 patients/day)**: $25-40/month
- **Medium Practice (50-100 patients/day)**: $60-100/month
- **Large Practice (200+ patients/day)**: $150-250/month

---

## 🎯 **Architecture Overview**

```
┌─────────────────────────────────────────────────────────┐
│                   Google Cloud Platform                  │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────┐      ┌─────────────────┐             │
│  │  Cloud Run   │◄────►│  Cloud Storage  │             │
│  │  (FastAPI)   │      │  (PDFs, Reports)│             │
│  └──────┬───────┘      └─────────────────┘             │
│         │                                                │
│         ├──────────►┌──────────────────┐               │
│         │           │  Cloud SQL       │               │
│         │           │  (PostgreSQL)    │               │
│         │           └──────────────────┘               │
│         │                                                │
│         ├──────────►┌──────────────────┐               │
│         │           │  Secret Manager  │               │
│         │           │  (Credentials)   │               │
│         │           └──────────────────┘               │
│         │                                                │
│         └──────────►┌──────────────────┐               │
│                     │  Vertex AI       │               │
│                     │  (Gemini API)    │               │
│                     └──────────────────┘               │
│                                                           │
│  External: Firebase Auth + Twilio WhatsApp              │
└─────────────────────────────────────────────────────────┘
```

---

## 💰 **Detailed Cost Breakdown**

### Monthly Costs by Component:

| Service | Small | Medium | Large | What It Does |
|---------|-------|--------|-------|--------------|
| **Cloud Run** | $5-10 | $15-30 | $50-100 | API hosting |
| **Cloud SQL** | $15-20 | $30-50 | $80-120 | PostgreSQL database |
| **Cloud Storage** | $1-3 | $5-10 | $15-25 | File storage (PDFs) |
| **Vertex AI/Gemini** | $2-5 | $10-15 | $30-50 | AI document analysis |
| **Secret Manager** | $0.50 | $0.50 | $1 | Secrets storage |
| **Networking** | $1-2 | $3-5 | $5-10 | Data transfer |
| **Firebase** | Free | Free | Free | Authentication |
| **Twilio (External)** | $5 | $10 | $20 | WhatsApp messages |
| **TOTAL** | **$25-40** | **$60-100** | **$150-250** |

---

## 🚀 **Complete Deployment Steps**

### **Part 1: Initial Google Cloud Setup**

#### 1.1 Create Google Cloud Project

```bash
# Install Google Cloud SDK first
# Windows: https://cloud.google.com/sdk/docs/install
# Mac: brew install google-cloud-sdk
# Linux: curl https://sdk.cloud.google.com | bash

# Login to Google Cloud
gcloud auth login

# Create new project
gcloud projects create medical-backend-001 --name="Medical Practice Backend"

# Set as active project
gcloud config set project medical-backend-001

# Link billing account (replace with your billing account ID)
# Get billing accounts: gcloud billing accounts list
gcloud billing projects link medical-backend-001 --billing-account=XXXXX-XXXXX-XXXXX

# Set default region (choose closest to your location)
gcloud config set compute/region us-central1
gcloud config set run/region us-central1
# For India: asia-south1, For Europe: europe-west1
```

#### 1.2 Enable Required Google Cloud APIs

```bash
# Enable all necessary APIs
gcloud services enable \
    run.googleapis.com \
    sql-component.googleapis.com \
    sqladmin.googleapis.com \
    storage-api.googleapis.com \
    storage-component.googleapis.com \
    cloudbuild.googleapis.com \
    secretmanager.googleapis.com \
    containerregistry.googleapis.com \
    aiplatform.googleapis.com \
    compute.googleapis.com
```

---

### **Part 2: Database Setup (Cloud SQL PostgreSQL)**

#### 2.1 Create Cloud SQL Instance

```bash
# Create PostgreSQL instance
gcloud sql instances create medical-db-instance \
    --database-version=POSTGRES_15 \
    --tier=db-f1-micro \
    --region=us-central1 \
    --storage-type=SSD \
    --storage-size=10GB \
    --storage-auto-increase \
    --backup-start-time=03:00 \
    --maintenance-window-day=SUN \
    --maintenance-window-hour=04

# For better performance (medium practice), use: --tier=db-g1-small
# For large practice, use: --tier=db-n1-standard-1
```

**Cost**: 
- `db-f1-micro`: ~$15-20/month (suitable for small practice)
- `db-g1-small`: ~$30-50/month (medium practice)
- `db-n1-standard-1`: ~$80-120/month (large practice)

#### 2.2 Set Database Password

```bash
# Set root password
gcloud sql users set-password postgres \
    --instance=medical-db-instance \
    --password=YOUR_SECURE_PASSWORD_HERE
```

#### 2.3 Create Database

```bash
# Create the medical practice database
gcloud sql databases create medical_practice \
    --instance=medical-db-instance
```

#### 2.4 Get Connection Details

```bash
# Get connection name (you'll need this later)
gcloud sql instances describe medical-db-instance --format="value(connectionName)"

# Output example: medical-backend-001:us-central1:medical-db-instance
```

#### 2.5 Initialize Database Schema

```bash
# Connect to database using Cloud SQL Proxy
# Download Cloud SQL Proxy
wget https://dl.google.com/cloudsql/cloud_sql_proxy.linux.amd64 -O cloud_sql_proxy
chmod +x cloud_sql_proxy

# Start proxy
./cloud_sql_proxy -instances=medical-backend-001:us-central1:medical-db-instance=tcp:5432

# In another terminal, connect with psql
psql "host=127.0.0.1 port=5432 dbname=medical_practice user=postgres"

# Run your schema from current_schema.sql
\i current_schema.sql
```

**Alternative**: Upload schema file to Cloud Storage and run:

```bash
# Upload schema to Cloud Storage
gsutil cp current_schema.sql gs://medical-backend-schemas/

# Import to Cloud SQL
gcloud sql import sql medical-db-instance \
    gs://medical-backend-schemas/current_schema.sql \
    --database=medical_practice
```

---

### **Part 3: File Storage Setup (Cloud Storage)**

#### 3.1 Create Storage Buckets

```bash
# Create bucket for medical reports
gsutil mb -p medical-backend-001 -c STANDARD -l us-central1 gs://medical-reports-storage/

# Create bucket for PDF templates
gsutil mb -p medical-backend-001 -c STANDARD -l us-central1 gs://medical-pdf-templates/

# Create bucket for handwritten notes
gsutil mb -p medical-backend-001 -c STANDARD -l us-central1 gs://medical-handwritten-notes/

# Create bucket for patient profiles
gsutil mb -p medical-backend-001 -c STANDARD -l us-central1 gs://medical-patient-profiles/
```

#### 3.2 Set Bucket Permissions

```bash
# Make buckets private (default)
gsutil iam ch allUsers:objectViewer gs://medical-reports-storage/
# Remove above if you want fully private - use signed URLs instead

# Set lifecycle policy (auto-delete old files after 2 years)
cat > lifecycle.json << EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 730}
      }
    ]
  }
}
EOF

gsutil lifecycle set lifecycle.json gs://medical-reports-storage/
```

#### 3.3 Enable Versioning (Optional - for backup)

```bash
gsutil versioning set on gs://medical-reports-storage/
gsutil versioning set on gs://medical-pdf-templates/
```

**Cost Estimate**: 
- 10GB storage: ~$0.20/month
- 100GB storage: ~$2/month
- 1TB storage: ~$20/month

---

### **Part 4: Secrets Management**

#### 4.1 Store Database Connection String

```bash
# Create database URL secret
# Format: postgresql://user:password@/database?host=/cloudsql/CONNECTION_NAME
echo -n "postgresql://postgres:YOUR_SECURE_PASSWORD@/medical_practice?host=/cloudsql/medical-backend-001:us-central1:medical-db-instance" | \
    gcloud secrets create DATABASE_URL --data-file=-

# Verify
gcloud secrets versions access latest --secret=DATABASE_URL
```

#### 4.2 Store All Application Secrets

```bash
# Firebase credentials (upload your JSON file)
gcloud secrets create FIREBASE_CREDENTIALS \
    --data-file=doctor-4bdc9-firebase-adminsdk-fbsvc-f43c360c82.json

# Twilio credentials
echo -n "YOUR_TWILIO_ACCOUNT_SID" | gcloud secrets create TWILIO_ACCOUNT_SID --data-file=-
echo -n "YOUR_TWILIO_AUTH_TOKEN" | gcloud secrets create TWILIO_AUTH_TOKEN --data-file=-
echo -n "whatsapp:+YOUR_TWILIO_NUMBER" | gcloud secrets create TWILIO_WHATSAPP_NUMBER --data-file=-

# Google AI API Key
echo -n "YOUR_GOOGLE_AI_API_KEY" | gcloud secrets create GOOGLE_API_KEY --data-file=-

# Firebase Project ID
echo -n "YOUR_FIREBASE_PROJECT_ID" | gcloud secrets create FIREBASE_PROJECT_ID --data-file=-

# Password salt for hashing
echo -n "$(openssl rand -hex 32)" | gcloud secrets create PASSWORD_SALT --data-file=-

# Cloud Storage bucket names
echo -n "medical-reports-storage" | gcloud secrets create REPORTS_BUCKET --data-file=-
echo -n "medical-pdf-templates" | gcloud secrets create TEMPLATES_BUCKET --data-file=-
echo -n "medical-handwritten-notes" | gcloud secrets create HANDWRITTEN_BUCKET --data-file=-
echo -n "medical-patient-profiles" | gcloud secrets create PROFILES_BUCKET --data-file=-
```

---

### **Part 5: Modify Application for Cloud SQL & Cloud Storage**

#### 5.1 Update `requirements.txt`

Add these dependencies:

```text
# Existing dependencies...

# Google Cloud libraries
google-cloud-storage>=2.10.0
google-cloud-secret-manager>=2.16.0
pg8000>=1.30.0
cloud-sql-python-connector>=1.4.0
asyncpg>=0.28.0
```

#### 5.2 Create `gcp_storage.py` for Cloud Storage Integration

Create a new file:

```python
from google.cloud import storage
from typing import Optional, BinaryIO
import os
from datetime import timedelta

class GCPStorageManager:
    def __init__(self):
        self.client = storage.Client()
        self.reports_bucket = self.client.bucket(os.getenv("REPORTS_BUCKET", "medical-reports-storage"))
        self.templates_bucket = self.client.bucket(os.getenv("TEMPLATES_BUCKET", "medical-pdf-templates"))
        self.handwritten_bucket = self.client.bucket(os.getenv("HANDWRITTEN_BUCKET", "medical-handwritten-notes"))
        self.profiles_bucket = self.client.bucket(os.getenv("PROFILES_BUCKET", "medical-patient-profiles"))
    
    async def upload_report(self, file_name: str, file_data: BinaryIO, content_type: str = "application/pdf") -> str:
        """Upload medical report to Cloud Storage"""
        blob = self.reports_bucket.blob(file_name)
        blob.upload_from_file(file_data, content_type=content_type)
        
        # Generate signed URL (valid for 7 days)
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=7),
            method="GET"
        )
        return url
    
    async def upload_template(self, file_name: str, file_data: BinaryIO) -> str:
        """Upload PDF template to Cloud Storage"""
        blob = self.templates_bucket.blob(file_name)
        blob.upload_from_file(file_data, content_type="application/pdf")
        
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=365),
            method="GET"
        )
        return url
    
    async def upload_handwritten_note(self, file_name: str, file_data: BinaryIO) -> str:
        """Upload handwritten note to Cloud Storage"""
        blob = self.handwritten_bucket.blob(file_name)
        blob.upload_from_file(file_data, content_type="application/pdf")
        
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=7),
            method="GET"
        )
        return url
    
    async def upload_patient_profile(self, file_name: str, file_data: BinaryIO) -> str:
        """Upload patient profile PDF to Cloud Storage"""
        blob = self.profiles_bucket.blob(file_name)
        blob.upload_from_file(file_data, content_type="application/pdf")
        
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=30),
            method="GET"
        )
        return url
    
    async def delete_file(self, bucket_name: str, file_name: str) -> bool:
        """Delete file from Cloud Storage"""
        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(file_name)
            blob.delete()
            return True
        except Exception as e:
            print(f"Error deleting file: {e}")
            return False
```

#### 5.3 Update `database.py` for Cloud SQL

Replace Supabase initialization with Cloud SQL:

```python
import asyncpg
from google.cloud.sql.connector import Connector
import os

class DatabaseManager:
    def __init__(self):
        self.connector = Connector()
        self.pool = None
    
    async def init_pool(self):
        """Initialize connection pool to Cloud SQL"""
        async def getconn():
            conn = await self.connector.connect_async(
                os.getenv("CLOUD_SQL_CONNECTION_NAME"),  # medical-backend-001:us-central1:medical-db-instance
                "asyncpg",
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD"),
                db=os.getenv("DB_NAME", "medical_practice")
            )
            return conn
        
        self.pool = await asyncpg.create_pool(
            min_size=2,
            max_size=10,
            setup=getconn
        )
    
    async def get_doctor_by_firebase_uid(self, firebase_uid: str):
        """Get doctor by Firebase UID"""
        async with self.pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM doctors WHERE firebase_uid = $1",
                firebase_uid
            )
            return dict(result) if result else None
    
    # ... implement other methods similarly
```

#### 5.4 Update `app.py` Initialization

```python
from gcp_storage import GCPStorageManager

# Initialize GCP Storage Manager
storage_manager = GCPStorageManager()

# Update database initialization
@app.on_event("startup")
async def startup():
    await db.init_pool()
    print("✅ Database connection pool initialized")

@app.on_event("shutdown")
async def shutdown():
    if db.pool:
        await db.pool.close()
    print("✅ Database connection pool closed")
```

---

### **Part 6: Create Production Dockerfile**

Create `Dockerfile.production`:

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    pkg-config \
    libssl-dev \
    libmagic1 \
    file \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create credentials directory
RUN mkdir -p /app/credentials

# Expose port (Cloud Run sets this via $PORT)
ENV PORT=8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:$PORT/test || exit 1

# Run with uvicorn (single worker for Cloud Run)
CMD uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1 --log-level info
```

---

### **Part 7: Deploy to Cloud Run**

#### 7.1 Create Deployment Script

Create `deploy-production.sh`:

```bash
#!/bin/bash

set -e

# Configuration
PROJECT_ID="medical-backend-001"
SERVICE_NAME="medical-api"
REGION="us-central1"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
CLOUD_SQL_INSTANCE="medical-backend-001:us-central1:medical-db-instance"

echo "🚀 Starting deployment to Google Cloud Run..."

# Set project
gcloud config set project ${PROJECT_ID}

# Build and push Docker image
echo "📦 Building Docker image..."
gcloud builds submit --tag ${IMAGE_NAME} --file Dockerfile.production .

# Deploy to Cloud Run with all secrets and Cloud SQL connection
echo "🌐 Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE_NAME} \
  --platform managed \
  --region ${REGION} \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --concurrency 80 \
  --max-instances 10 \
  --min-instances 0 \
  --add-cloudsql-instances ${CLOUD_SQL_INSTANCE} \
  --set-env-vars "CLOUD_SQL_CONNECTION_NAME=${CLOUD_SQL_INSTANCE}" \
  --set-env-vars "FIREBASE_CREDENTIALS_PATH=/app/credentials/firebase-key.json" \
  --set-secrets "DB_USER=DB_USER:latest" \
  --set-secrets "DB_PASSWORD=DB_PASSWORD:latest" \
  --set-secrets "DB_NAME=DB_NAME:latest" \
  --set-secrets "FIREBASE_PROJECT_ID=FIREBASE_PROJECT_ID:latest" \
  --set-secrets "FIREBASE_CREDENTIALS=/app/credentials/firebase-key.json=FIREBASE_CREDENTIALS:latest" \
  --set-secrets "TWILIO_ACCOUNT_SID=TWILIO_ACCOUNT_SID:latest" \
  --set-secrets "TWILIO_AUTH_TOKEN=TWILIO_AUTH_TOKEN:latest" \
  --set-secrets "TWILIO_WHATSAPP_NUMBER=TWILIO_WHATSAPP_NUMBER:latest" \
  --set-secrets "GOOGLE_API_KEY=GOOGLE_API_KEY:latest" \
  --set-secrets "PASSWORD_SALT=PASSWORD_SALT:latest" \
  --set-secrets "REPORTS_BUCKET=REPORTS_BUCKET:latest" \
  --set-secrets "TEMPLATES_BUCKET=TEMPLATES_BUCKET:latest" \
  --set-secrets "HANDWRITTEN_BUCKET=HANDWRITTEN_BUCKET:latest" \
  --set-secrets "PROFILES_BUCKET=PROFILES_BUCKET:latest"

# Get service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format 'value(status.url)')

echo "✅ Deployment complete!"
echo "🌐 Your API is available at: ${SERVICE_URL}"
echo "🧪 Test endpoint: ${SERVICE_URL}/test"
```

#### 7.2 Make Script Executable and Run

```bash
chmod +x deploy-production.sh
./deploy-production.sh
```

---

### **Part 8: Post-Deployment Configuration**

#### 8.1 Test Your Deployment

```bash
# Get your service URL
SERVICE_URL=$(gcloud run services describe medical-api --region us-central1 --format 'value(status.url)')

# Test health endpoint
curl ${SERVICE_URL}/test

# Expected response:
# {
#   "message": "API is working",
#   "database_connection": "success",
#   "firebase_connection": "OK",
#   "whatsapp_connection": true
# }
```

#### 8.2 Set Up Custom Domain (Optional)

```bash
# Verify domain ownership in Google Cloud Console first
# Then map domain
gcloud run domain-mappings create \
  --service medical-api \
  --domain api.yourdomain.com \
  --region us-central1

# Get DNS records to add
gcloud run domain-mappings describe \
  --domain api.yourdomain.com \
  --region us-central1
```

#### 8.3 Enable Cloud Armor (DDoS Protection - Optional)

```bash
# Create security policy
gcloud compute security-policies create medical-api-policy \
    --description "Security policy for medical API"

# Add rate limiting rule
gcloud compute security-policies rules create 1000 \
    --security-policy medical-api-policy \
    --expression "true" \
    --action "rate-based-ban" \
    --rate-limit-threshold-count 1000 \
    --rate-limit-threshold-interval-sec 60 \
    --ban-duration-sec 600

# Attach to Cloud Run service (requires Load Balancer - additional cost)
```

#### 8.4 Set Up Monitoring and Alerts

```bash
# Create uptime check
gcloud monitoring uptime-checks create http \
    --display-name="Medical API Health" \
    --resource-type=uptime-url \
    --http-check-path=/test \
    --timeout=10s \
    --period=5m

# Create alert policy for high error rate
gcloud alpha monitoring policies create \
    --display-name="High Error Rate Alert" \
    --condition-display-name="Error rate > 5%" \
    --condition-threshold-value=5 \
    --notification-channels=YOUR_NOTIFICATION_CHANNEL_ID
```

---

## 📊 **Monitoring and Logging**

### View Logs

```bash
# Real-time logs
gcloud logging tail "resource.type=cloud_run_revision AND resource.labels.service_name=medical-api"

# Filter errors only
gcloud logging read "resource.type=cloud_run_revision AND severity>=ERROR" --limit 100

# Filter by time range
gcloud logging read "resource.type=cloud_run_revision AND timestamp>=\"2024-01-01T00:00:00Z\"" --limit 100
```

### Monitor Resource Usage

```bash
# Get Cloud Run metrics
gcloud monitoring time-series list \
    --filter='metric.type="run.googleapis.com/request_count"' \
    --format=json

# Get Cloud SQL metrics
gcloud monitoring time-series list \
    --filter='metric.type="cloudsql.googleapis.com/database/cpu/utilization"' \
    --format=json
```

### Set Up Budget Alerts

```bash
# Go to: https://console.cloud.google.com/billing/budgets
# Create budget: $100/month
# Set alerts at 50%, 75%, 90%, 100%
```

---

## 🔐 **Security Best Practices**

### 1. IAM Permissions

```bash
# Create service account for Cloud Run
gcloud iam service-accounts create medical-api-sa \
    --display-name="Medical API Service Account"

# Grant necessary permissions
gcloud projects add-iam-policy-binding medical-backend-001 \
    --member="serviceAccount:medical-api-sa@medical-backend-001.iam.gserviceaccount.com" \
    --role="roles/cloudsql.client"

gcloud projects add-iam-policy-binding medical-backend-001 \
    --member="serviceAccount:medical-api-sa@medical-backend-001.iam.gserviceaccount.com" \
    --role="roles/storage.objectAdmin"

# Use in Cloud Run deployment
# Add to deploy script: --service-account medical-api-sa@medical-backend-001.iam.gserviceaccount.com
```

### 2. Enable VPC Service Controls (Enterprise Security)

```bash
# Create VPC connector
gcloud compute networks vpc-access connectors create medical-vpc-connector \
    --region=us-central1 \
    --network=default \
    --range=10.8.0.0/28

# Update Cloud Run to use VPC
# Add to deploy script: --vpc-connector medical-vpc-connector
```

### 3. Enable Binary Authorization (Container Signing)

```bash
gcloud services enable binaryauthorization.googleapis.com

# Require signed images
gcloud container binauthz policy import policy.yaml
```

---

## 🚨 **Backup and Disaster Recovery**

### Database Backups

```bash
# Cloud SQL automatically backs up daily
# To create manual backup:
gcloud sql backups create --instance=medical-db-instance

# List backups
gcloud sql backups list --instance=medical-db-instance

# Restore from backup
gcloud sql backups restore BACKUP_ID --backup-instance=medical-db-instance
```

### Storage Backups

```bash
# Enable versioning (already done)
gsutil versioning set on gs://medical-reports-storage/

# Create backup bucket
gsutil mb -p medical-backend-001 -l us-central1 gs://medical-reports-backup/

# Sync to backup
gsutil -m rsync -r gs://medical-reports-storage/ gs://medical-reports-backup/
```

---

## 🔄 **CI/CD with GitHub Actions**

Create `.github/workflows/deploy-gcp.yml`:

```yaml
name: Deploy to Google Cloud

on:
  push:
    branches:
      - main

env:
  PROJECT_ID: medical-backend-001
  SERVICE_NAME: medical-api
  REGION: us-central1

jobs:
  deploy:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v3
      
      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v1
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
      
      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v1
      
      - name: Configure Docker for GCR
        run: gcloud auth configure-docker
      
      - name: Build Docker image
        run: |
          docker build -f Dockerfile.production -t gcr.io/$PROJECT_ID/$SERVICE_NAME:$GITHUB_SHA .
      
      - name: Push to Container Registry
        run: docker push gcr.io/$PROJECT_ID/$SERVICE_NAME:$GITHUB_SHA
      
      - name: Deploy to Cloud Run
        run: |
          gcloud run deploy $SERVICE_NAME \
            --image gcr.io/$PROJECT_ID/$SERVICE_NAME:$GITHUB_SHA \
            --region $REGION \
            --platform managed \
            --allow-unauthenticated \
            --add-cloudsql-instances medical-backend-001:us-central1:medical-db-instance
      
      - name: Run smoke tests
        run: |
          SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)')
          curl -f ${SERVICE_URL}/test || exit 1
```

---

## 📱 **Mobile App Integration**

Update your Flutter app to use the new Cloud Run URL:

```dart
// lib/config/api_config.dart
class ApiConfig {
  static const String baseUrl = 'https://medical-api-xxxxx-uc.a.run.app';
  
  // All your endpoints remain the same
  static const String registerEndpoint = '$baseUrl/register';
  static const String loginEndpoint = '$baseUrl/login';
  // ...
}
```

---

## 🧪 **Testing Checklist**

After deployment, test these critical endpoints:

```bash
SERVICE_URL="https://medical-api-xxxxx-uc.a.run.app"

# 1. Health check
curl $SERVICE_URL/test

# 2. Database connection
curl -X POST $SERVICE_URL/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"test123",...}'

# 3. File upload (after getting auth token)
curl -X POST $SERVICE_URL/visits/1/generate-report-link \
  -H "Authorization: Bearer YOUR_FIREBASE_TOKEN"

# 4. Storage access
# Upload a file and verify URL is accessible

# 5. AI analysis
curl -X POST $SERVICE_URL/reports/1/analyze \
  -H "Authorization: Bearer YOUR_FIREBASE_TOKEN"
```

---

## 💡 **Cost Optimization Tips**

### 1. Right-Size Cloud SQL

```bash
# Start with db-f1-micro, monitor CPU usage
# If CPU > 80%, upgrade:
gcloud sql instances patch medical-db-instance --tier=db-g1-small
```

### 2. Implement Caching

```python
# Use Redis for caching (optional)
from google.cloud import memorystore_v1

# Or use in-memory caching in Cloud Run
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_cached_patient(patient_id):
    # Cache frequently accessed data
    pass
```

### 3. Optimize Storage Costs

```bash
# Use Standard storage for active data
# Use Nearline for archives (30-day access)
# Use Coldline for long-term backups (90-day access)

gsutil rewrite -s NEARLINE gs://medical-reports-storage/old-reports/*
```

### 4. Cloud Run Optimization

```bash
# Set minimum instances to 0 during off-hours
gcloud run services update medical-api --min-instances 0

# Set to 1 during business hours (9 AM - 6 PM)
# Use Cloud Scheduler for automation
```

---

## 🆘 **Troubleshooting Guide**

### Issue: Cloud SQL Connection Timeout

**Solution:**
```bash
# Check Cloud SQL instance status
gcloud sql instances describe medical-db-instance

# Verify Cloud Run has Cloud SQL connection
gcloud run services describe medical-api --region us-central1 | grep cloudsql
```

### Issue: Storage Upload Failures

**Solution:**
```bash
# Check service account permissions
gcloud projects get-iam-policy medical-backend-001 \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:medical-api-sa@medical-backend-001.iam.gserviceaccount.com"

# Grant storage permissions
gcloud projects add-iam-policy-binding medical-backend-001 \
  --member="serviceAccount:medical-api-sa@medical-backend-001.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

### Issue: High Costs

**Solution:**
```bash
# Check cost breakdown
gcloud billing accounts list
gcloud billing accounts get-usage [BILLING_ACCOUNT_ID]

# Review Cloud Run metrics
gcloud run services describe medical-api --region us-central1 --format=json
```

---

## ✅ **Final Deployment Checklist**

- [ ] Google Cloud project created and billing enabled
- [ ] All APIs enabled (Cloud Run, Cloud SQL, Storage, etc.)
- [ ] Cloud SQL instance created and database initialized
- [ ] Schema imported successfully
- [ ] Cloud Storage buckets created
- [ ] All secrets stored in Secret Manager
- [ ] `gcp_storage.py` implemented
- [ ] `database.py` updated for Cloud SQL
- [ ] `Dockerfile.production` created
- [ ] `deploy-production.sh` created and tested
- [ ] Application deployed to Cloud Run
- [ ] `/test` endpoint returns success
- [ ] Database queries working
- [ ] File uploads to Cloud Storage working
- [ ] AI analysis working
- [ ] Custom domain configured (optional)
- [ ] Monitoring and alerts set up
- [ ] Budget alerts configured
- [ ] Backups verified
- [ ] Mobile app updated with new URL
- [ ] All critical endpoints tested

---

## 📞 **Support Resources**

- **Cloud Run**: https://cloud.google.com/run/docs
- **Cloud SQL**: https://cloud.google.com/sql/docs
- **Cloud Storage**: https://cloud.google.com/storage/docs
- **Vertex AI**: https://cloud.google.com/vertex-ai/docs
- **Pricing Calculator**: https://cloud.google.com/products/calculator
- **GCP Support**: https://cloud.google.com/support

---

## 🎉 **Summary**

You now have a **complete, production-ready deployment** on Google Cloud:

✅ **API**: Cloud Run (serverless, auto-scaling)  
✅ **Database**: Cloud SQL PostgreSQL (managed, backed up)  
✅ **Storage**: Cloud Storage (reliable, versioned)  
✅ **AI**: Vertex AI / Gemini API (integrated)  
✅ **Security**: Secret Manager, IAM, Firebase Auth  
✅ **Monitoring**: Cloud Logging, Monitoring, Alerts  

**Estimated Cost**: $25-250/month depending on usage  
**Deployment Time**: ~2-3 hours (first time)  
**Maintenance**: Minimal (fully managed services)  

---

**Your medical practice backend is now running entirely on Google Cloud! 🚀**
