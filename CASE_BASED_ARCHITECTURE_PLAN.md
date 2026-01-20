# Case-Based Architecture Implementation Plan

## ✅ IMPLEMENTATION COMPLETE (2026-01-18)

> **Status:** All phases completed. Case-based architecture is now live.
> 
> **Completed:**
> - ✅ Database tables created (patient_cases, case_photos, ai_case_analysis)
> - ✅ visits table updated with case_id, is_case_opener columns
> - ✅ Deprecated columns removed (parent_visit_id, link_reason)
> - ✅ Backend models added (Case, CasePhoto, CaseAnalysis)
> - ✅ API endpoints implemented for cases, photos, analysis
> - ✅ AI analysis service updated for case-level analysis
> - ✅ Deprecated endpoints return 410 Gone with redirect guidance
> - ✅ Code cleanup complete - no references to removed columns

---

## Executive Summary

This document outlines the complete implementation plan for transitioning from a linear visit-based model to a **Case/Episode of Care** model. This change will enable:

- **Before/After photo tracking** for specific medical problems
- **Concurrent problem management** (multiple active cases per patient)
- **Case-based AI analysis** (contextual analysis per medical problem)
- **Treatment outcome tracking** with resolution status
- **Simplified visit structure** (removing linked visits complexity)

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Target Architecture](#2-target-architecture)
3. [Database Changes](#3-database-changes)
4. [Backend Implementation](#4-backend-implementation)
5. [AI Analysis Refactoring](#5-ai-analysis-refactoring)
6. [API Endpoints](#6-api-endpoints)
7. [Migration Strategy](#7-migration-strategy)
8. [Testing Plan](#8-testing-plan)
9. [Rollout Plan](#9-rollout-plan)
10. [Future Enhancements](#10-future-enhancements)

---

## 1. Current State Analysis

### 1.1 Current Visit Model

```
Patient
  └── Visit 1 (parent_visit_id: null)
        └── Visit 2 (parent_visit_id: 1)
              └── Visit 3 (parent_visit_id: 2)
```

**Problems:**
- Linear chain doesn't support concurrent medical problems
- No clear grouping of visits by condition
- AI analyzes all visits together without problem context
- No before/after photo capability tied to specific conditions
- `parent_visit_id` creates complexity without clear benefit

### 1.2 Tables Affected by Change

| Table | Change Type | Description |
|-------|-------------|-------------|
| `visits` | MODIFY | Remove `parent_visit_id`, `link_reason`; Add `case_id` |
| `patient_cases` | NEW | Core case/episode table |
| `case_photos` | NEW | Before/progress/after photos |
| `ai_document_analysis` | MODIFY | Add `case_id`, change analysis scope |
| `ai_consolidated_analysis` | MODIFY | Rename/refocus to case-based |
| `ai_case_analysis` | NEW | Case-level AI analysis |
| `reports` | MODIFY | Add `case_id` for case association |
| `ai_clinical_alerts` | MODIFY | Add `case_id` for case context |

### 1.3 Code Files Affected

```
Backend Files:
├── database.py          # Major changes - new case methods, modify visit methods
├── app.py               # New endpoints, modify existing visit endpoints
├── ai_analysis_service.py    # Refactor for case-based analysis
├── ai_analysis_processor.py  # Process case analyses
├── ai_schemas.py        # New schemas for case analysis
└── migrations/          # New migration files
```

---

## 2. Target Architecture

### 2.1 New Data Model

```
Patient
  ├── Case 1: "Skin Rash" (status: resolved)
  │     ├── Before Photos (Jan 1)
  │     ├── Visit 1 - Initial (Jan 1)
  │     ├── Report: Blood Test (Jan 2)
  │     ├── Progress Photos (Jan 7)
  │     ├── Visit 2 - Follow-up (Jan 7)
  │     ├── Visit 3 - Resolution (Jan 14)
  │     ├── After Photos (Jan 14)
  │     └── AI Case Analysis (treatment effectiveness, outcome)
  │
  ├── Case 2: "Diabetes Management" (status: ongoing)
  │     ├── Visit 4 - Monthly checkup (Dec 15)
  │     ├── Report: HbA1c (Dec 15)
  │     ├── Visit 5 - Monthly checkup (Jan 15)
  │     ├── Report: HbA1c (Jan 15)
  │     └── AI Case Analysis (trend analysis, risk assessment)
  │
  └── Quick Visits (no case)
        └── Visit 6 - Vaccination (Jan 10)
```

### 2.2 Key Concepts

| Concept | Definition |
|---------|------------|
| **Case** | A distinct medical problem/episode being treated |
| **Case Type** | `acute`, `chronic`, `preventive`, `procedure` |
| **Case Status** | `active`, `resolved`, `ongoing`, `referred`, `closed` |
| **Case Photos** | Before/progress/after images tied to a case |
| **Quick Visit** | One-off visit not tied to any case |
| **Case Analysis** | AI analysis scoped to a single case's data |

---

## 3. Database Changes

### 3.1 New Tables

#### 3.1.1 `patient_cases` Table

```sql
-- Migration: 001_create_patient_cases.sql

CREATE TABLE patient_cases (
    id BIGSERIAL PRIMARY KEY,
    patient_id BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid),
    
    -- Case Identification
    case_number TEXT NOT NULL,  -- Auto-generated: "CASE-2026-001"
    case_title TEXT NOT NULL,   -- "Skin Rash - Right Arm"
    case_type TEXT NOT NULL DEFAULT 'acute' 
        CHECK (case_type IN ('acute', 'chronic', 'preventive', 'procedure', 'other')),
    
    -- Medical Details
    chief_complaint TEXT NOT NULL,
    initial_diagnosis TEXT,
    final_diagnosis TEXT,
    icd10_codes JSONB DEFAULT '[]',
    body_parts_affected JSONB DEFAULT '[]',  -- ['right_arm', 'chest']
    
    -- Status & Severity
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'resolved', 'ongoing', 'referred', 'closed', 'on_hold')),
    severity TEXT DEFAULT 'moderate'
        CHECK (severity IN ('mild', 'moderate', 'severe', 'critical')),
    priority INTEGER DEFAULT 2 CHECK (priority BETWEEN 1 AND 5),  -- 1=highest
    
    -- Timeline
    started_at DATE NOT NULL DEFAULT CURRENT_DATE,
    resolved_at DATE,
    expected_resolution_date DATE,
    last_visit_date DATE,
    next_follow_up_date DATE,
    
    -- Outcome Tracking
    outcome TEXT CHECK (outcome IN (
        'fully_resolved', 'significantly_improved', 'partially_improved', 
        'unchanged', 'worsened', 'referred', 'patient_discontinued', NULL
    )),
    outcome_notes TEXT,
    patient_satisfaction INTEGER CHECK (patient_satisfaction BETWEEN 1 AND 5),
    
    -- Treatment Summary (auto-updated)
    total_visits INTEGER DEFAULT 0,
    total_reports INTEGER DEFAULT 0,
    total_photos INTEGER DEFAULT 0,
    medications_prescribed JSONB DEFAULT '[]',
    treatments_given JSONB DEFAULT '[]',
    
    -- AI Analysis Reference
    latest_ai_analysis_id BIGINT,  -- FK added after ai_case_analysis table
    ai_summary TEXT,
    ai_treatment_effectiveness NUMERIC(3,2) CHECK (ai_treatment_effectiveness BETWEEN 0 AND 1),
    
    -- Metadata
    tags JSONB DEFAULT '[]',  -- ['dermatology', 'allergic', 'recurring']
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Unique case number per doctor
    UNIQUE (doctor_firebase_uid, case_number)
);

-- Indexes for common queries
CREATE INDEX idx_cases_patient_doctor ON patient_cases(patient_id, doctor_firebase_uid);
CREATE INDEX idx_cases_status ON patient_cases(doctor_firebase_uid, status);
CREATE INDEX idx_cases_type ON patient_cases(doctor_firebase_uid, case_type);
CREATE INDEX idx_cases_started ON patient_cases(started_at DESC);
CREATE INDEX idx_cases_last_visit ON patient_cases(last_visit_date DESC);

-- Function to auto-generate case numbers
CREATE OR REPLACE FUNCTION generate_case_number()
RETURNS TRIGGER AS $$
DECLARE
    year_part TEXT;
    seq_num INTEGER;
BEGIN
    year_part := to_char(CURRENT_DATE, 'YYYY');
    
    SELECT COALESCE(MAX(
        CAST(SUBSTRING(case_number FROM 'CASE-\d{4}-(\d+)') AS INTEGER)
    ), 0) + 1
    INTO seq_num
    FROM patient_cases
    WHERE doctor_firebase_uid = NEW.doctor_firebase_uid
    AND case_number LIKE 'CASE-' || year_part || '-%';
    
    NEW.case_number := 'CASE-' || year_part || '-' || LPAD(seq_num::TEXT, 4, '0');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_case_number
    BEFORE INSERT ON patient_cases
    FOR EACH ROW
    WHEN (NEW.case_number IS NULL)
    EXECUTE FUNCTION generate_case_number();
```

#### 3.1.2 `case_photos` Table

```sql
-- Migration: 002_create_case_photos.sql

CREATE TABLE case_photos (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL REFERENCES patient_cases(id) ON DELETE CASCADE,
    visit_id BIGINT REFERENCES visits(id) ON DELETE SET NULL,
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid),
    
    -- Photo Classification
    photo_type TEXT NOT NULL CHECK (photo_type IN ('before', 'progress', 'after')),
    sequence_number INTEGER DEFAULT 1,  -- For ordering multiple photos of same type
    
    -- File Details
    file_name TEXT NOT NULL,
    file_url TEXT NOT NULL,
    file_size BIGINT,
    file_type TEXT,  -- 'image/jpeg', 'image/png'
    storage_path TEXT,
    thumbnail_url TEXT,  -- Auto-generated thumbnail for quick loading
    
    -- Medical Context
    body_part TEXT,  -- 'right_arm', 'face_front', 'back', etc.
    body_part_detail TEXT,  -- More specific: 'upper right arm, lateral view'
    description TEXT,
    clinical_notes TEXT,
    
    -- Timestamps
    photo_taken_at TIMESTAMPTZ,  -- When the photo was actually taken
    uploaded_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Comparison Flags
    is_primary BOOLEAN DEFAULT FALSE,  -- Primary photo for before/after comparison
    comparison_pair_id BIGINT REFERENCES case_photos(id),  -- Links before to its after
    
    -- AI Analysis
    ai_detected_changes TEXT,  -- AI description of changes from before
    ai_improvement_score NUMERIC(3,2),  -- 0-1 score of improvement
    
    -- Metadata
    metadata JSONB DEFAULT '{}',  -- Camera info, dimensions, etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_photos_case ON case_photos(case_id, photo_type);
CREATE INDEX idx_photos_visit ON case_photos(visit_id);
CREATE INDEX idx_photos_primary ON case_photos(case_id, is_primary) WHERE is_primary = TRUE;

-- Ensure only one primary per type per case
CREATE UNIQUE INDEX idx_one_primary_per_type 
    ON case_photos(case_id, photo_type) 
    WHERE is_primary = TRUE;
```

#### 3.1.3 `ai_case_analysis` Table

```sql
-- Migration: 003_create_ai_case_analysis.sql

CREATE TABLE ai_case_analysis (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL REFERENCES patient_cases(id) ON DELETE CASCADE,
    patient_id BIGINT NOT NULL REFERENCES patients(id),
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid),
    
    -- Analysis Scope
    analysis_type TEXT NOT NULL DEFAULT 'comprehensive'
        CHECK (analysis_type IN ('comprehensive', 'progress_review', 'outcome_assessment', 'photo_comparison')),
    visits_analyzed INTEGER[] DEFAULT '{}',  -- Array of visit IDs included
    reports_analyzed INTEGER[] DEFAULT '{}',  -- Array of report IDs included
    photos_analyzed INTEGER[] DEFAULT '{}',  -- Array of photo IDs included
    
    -- Analysis Period
    analysis_from_date DATE,
    analysis_to_date DATE,
    
    -- AI Model Info
    model_used TEXT NOT NULL DEFAULT 'gemini-2.0-flash',
    confidence_score NUMERIC(3,2) CHECK (confidence_score BETWEEN 0 AND 1),
    processing_time_ms INTEGER,
    
    -- Raw & Structured Output
    raw_analysis TEXT NOT NULL,
    structured_data JSONB,  -- Parsed structured response
    
    -- Case Summary Sections
    case_overview TEXT,
    presenting_complaint_summary TEXT,
    clinical_findings_summary TEXT,
    diagnosis_assessment TEXT,
    
    -- Treatment Analysis
    treatment_timeline JSONB,  -- [{date, treatment, response}]
    treatment_effectiveness TEXT,
    treatment_effectiveness_score NUMERIC(3,2),
    medications_analysis JSONB,
    
    -- Progress & Outcome
    progress_assessment TEXT,
    improvement_indicators JSONB,  -- [{indicator, baseline, current, change}]
    photo_comparison_analysis TEXT,
    visual_improvement_score NUMERIC(3,2),
    
    -- Recommendations
    current_status_assessment TEXT,
    recommended_next_steps JSONB,
    follow_up_recommendations TEXT,
    red_flags JSONB DEFAULT '[]',
    
    -- Patient Communication
    patient_friendly_summary TEXT,
    
    -- Metadata
    analysis_success BOOLEAN DEFAULT TRUE,
    analysis_error TEXT,
    analyzed_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_case_analysis_case ON ai_case_analysis(case_id);
CREATE INDEX idx_case_analysis_doctor ON ai_case_analysis(doctor_firebase_uid);
CREATE INDEX idx_case_analysis_type ON ai_case_analysis(analysis_type);
CREATE INDEX idx_case_analysis_date ON ai_case_analysis(analyzed_at DESC);

-- Add FK back to patient_cases for latest analysis
ALTER TABLE patient_cases 
    ADD CONSTRAINT fk_latest_analysis 
    FOREIGN KEY (latest_ai_analysis_id) 
    REFERENCES ai_case_analysis(id);
```

### 3.2 Table Modifications

#### 3.2.1 Modify `visits` Table

```sql
-- Migration: 004_modify_visits_for_cases.sql

-- Add case_id column
ALTER TABLE visits ADD COLUMN case_id BIGINT REFERENCES patient_cases(id) ON DELETE SET NULL;

-- Add flag for case opener
ALTER TABLE visits ADD COLUMN is_case_opener BOOLEAN DEFAULT FALSE;

-- Create index for case lookups
CREATE INDEX idx_visits_case ON visits(case_id) WHERE case_id IS NOT NULL;

-- Remove linked visits columns (deprecate, don't drop yet for safety)
-- We'll drop these after migration verification
ALTER TABLE visits RENAME COLUMN parent_visit_id TO deprecated_parent_visit_id;
ALTER TABLE visits RENAME COLUMN link_reason TO deprecated_link_reason;

-- Add comment for deprecation
COMMENT ON COLUMN visits.deprecated_parent_visit_id IS 'DEPRECATED: Use case_id instead. Will be removed in future migration.';
COMMENT ON COLUMN visits.deprecated_link_reason IS 'DEPRECATED: Use case_id instead. Will be removed in future migration.';
```

#### 3.2.2 Modify `reports` Table

```sql
-- Migration: 005_modify_reports_for_cases.sql

-- Add case_id column
ALTER TABLE reports ADD COLUMN case_id BIGINT REFERENCES patient_cases(id) ON DELETE SET NULL;

-- Create index
CREATE INDEX idx_reports_case ON reports(case_id) WHERE case_id IS NOT NULL;
```

#### 3.2.3 Modify `ai_document_analysis` Table

```sql
-- Migration: 006_modify_ai_analysis_for_cases.sql

-- Add case_id column
ALTER TABLE ai_document_analysis ADD COLUMN case_id BIGINT REFERENCES patient_cases(id) ON DELETE SET NULL;

-- Create index
CREATE INDEX idx_ai_doc_analysis_case ON ai_document_analysis(case_id) WHERE case_id IS NOT NULL;
```

#### 3.2.4 Modify `ai_clinical_alerts` Table

```sql
-- Migration: 007_modify_alerts_for_cases.sql

-- Add case_id column
ALTER TABLE ai_clinical_alerts ADD COLUMN case_id BIGINT REFERENCES patient_cases(id) ON DELETE SET NULL;

-- Create index
CREATE INDEX idx_alerts_case ON ai_clinical_alerts(case_id) WHERE case_id IS NOT NULL;
```

### 3.3 Helper Functions

```sql
-- Migration: 008_case_helper_functions.sql

-- Function to update case statistics when visits change
CREATE OR REPLACE FUNCTION update_case_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        IF NEW.case_id IS NOT NULL THEN
            UPDATE patient_cases SET
                total_visits = (SELECT COUNT(*) FROM visits WHERE case_id = NEW.case_id),
                last_visit_date = (SELECT MAX(visit_date) FROM visits WHERE case_id = NEW.case_id),
                updated_at = NOW()
            WHERE id = NEW.case_id;
        END IF;
        
        -- Handle case_id change on UPDATE
        IF TG_OP = 'UPDATE' AND OLD.case_id IS NOT NULL AND OLD.case_id != COALESCE(NEW.case_id, 0) THEN
            UPDATE patient_cases SET
                total_visits = (SELECT COUNT(*) FROM visits WHERE case_id = OLD.case_id),
                last_visit_date = (SELECT MAX(visit_date) FROM visits WHERE case_id = OLD.case_id),
                updated_at = NOW()
            WHERE id = OLD.case_id;
        END IF;
    END IF;
    
    IF TG_OP = 'DELETE' AND OLD.case_id IS NOT NULL THEN
        UPDATE patient_cases SET
            total_visits = (SELECT COUNT(*) FROM visits WHERE case_id = OLD.case_id),
            last_visit_date = (SELECT MAX(visit_date) FROM visits WHERE case_id = OLD.case_id),
            updated_at = NOW()
        WHERE id = OLD.case_id;
    END IF;
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_case_stats
    AFTER INSERT OR UPDATE OR DELETE ON visits
    FOR EACH ROW
    EXECUTE FUNCTION update_case_stats();

-- Function to update case report count
CREATE OR REPLACE FUNCTION update_case_report_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        IF NEW.case_id IS NOT NULL THEN
            UPDATE patient_cases SET
                total_reports = (SELECT COUNT(*) FROM reports WHERE case_id = NEW.case_id),
                updated_at = NOW()
            WHERE id = NEW.case_id;
        END IF;
    END IF;
    
    IF TG_OP = 'DELETE' AND OLD.case_id IS NOT NULL THEN
        UPDATE patient_cases SET
            total_reports = (SELECT COUNT(*) FROM reports WHERE case_id = OLD.case_id),
            updated_at = NOW()
        WHERE id = OLD.case_id;
    END IF;
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_case_report_stats
    AFTER INSERT OR UPDATE OR DELETE ON reports
    FOR EACH ROW
    EXECUTE FUNCTION update_case_report_stats();

-- Function to update case photo count
CREATE OR REPLACE FUNCTION update_case_photo_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        UPDATE patient_cases SET
            total_photos = (SELECT COUNT(*) FROM case_photos WHERE case_id = NEW.case_id),
            updated_at = NOW()
        WHERE id = NEW.case_id;
    END IF;
    
    IF TG_OP = 'DELETE' THEN
        UPDATE patient_cases SET
            total_photos = (SELECT COUNT(*) FROM case_photos WHERE case_id = OLD.case_id),
            updated_at = NOW()
        WHERE id = OLD.case_id;
    END IF;
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_case_photo_stats
    AFTER INSERT OR UPDATE OR DELETE ON case_photos
    FOR EACH ROW
    EXECUTE FUNCTION update_case_photo_stats();
```

---

## 4. Backend Implementation

### 4.1 New Pydantic Models

#### File: `app.py` (add to models section)

```python
# ============================================================
# CASE/EPISODE MODELS
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

# Create Case
class CaseCreate(BaseModel):
    case_title: str = Field(..., min_length=3, max_length=200, description="Brief title for the case")
    case_type: CaseType = Field(default=CaseType.ACUTE)
    chief_complaint: str = Field(..., min_length=5, description="Primary complaint for this case")
    initial_diagnosis: Optional[str] = None
    body_parts_affected: Optional[List[str]] = Field(default_factory=list)
    severity: CaseSeverity = Field(default=CaseSeverity.MODERATE)
    priority: int = Field(default=2, ge=1, le=5)
    expected_resolution_date: Optional[str] = None  # YYYY-MM-DD
    tags: Optional[List[str]] = Field(default_factory=list)
    notes: Optional[str] = None
    
    # Option to create first visit along with case
    create_initial_visit: bool = Field(default=False)
    initial_visit_data: Optional['VisitCreate'] = None

class CaseUpdate(BaseModel):
    case_title: Optional[str] = None
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
    final_diagnosis: Optional[str] = None
    outcome: CaseOutcome
    outcome_notes: Optional[str] = None
    patient_satisfaction: Optional[int] = Field(default=None, ge=1, le=5)

class CaseResponse(BaseModel):
    id: int
    patient_id: int
    case_number: str
    case_title: str
    case_type: str
    chief_complaint: str
    initial_diagnosis: Optional[str]
    final_diagnosis: Optional[str]
    icd10_codes: List[str]
    body_parts_affected: List[str]
    status: str
    severity: str
    priority: int
    started_at: str
    resolved_at: Optional[str]
    expected_resolution_date: Optional[str]
    last_visit_date: Optional[str]
    next_follow_up_date: Optional[str]
    outcome: Optional[str]
    outcome_notes: Optional[str]
    patient_satisfaction: Optional[int]
    total_visits: int
    total_reports: int
    total_photos: int
    medications_prescribed: List[dict]
    ai_summary: Optional[str]
    ai_treatment_effectiveness: Optional[float]
    tags: List[str]
    notes: Optional[str]
    created_at: str
    updated_at: str

class CaseWithDetails(CaseResponse):
    """Extended case response with visits and photos"""
    visits: List['Visit'] = Field(default_factory=list)
    photos: List['CasePhotoResponse'] = Field(default_factory=list)
    reports: List['Report'] = Field(default_factory=list)
    latest_analysis: Optional['CaseAnalysisResponse'] = None

class CaseSummary(BaseModel):
    """Lightweight case summary for lists"""
    id: int
    case_number: str
    case_title: str
    case_type: str
    status: str
    severity: str
    started_at: str
    last_visit_date: Optional[str]
    total_visits: int
    has_photos: bool
    primary_before_photo_url: Optional[str]
    primary_after_photo_url: Optional[str]

# Case Photos
class CasePhotoUpload(BaseModel):
    photo_type: PhotoType
    body_part: Optional[str] = None
    body_part_detail: Optional[str] = None
    description: Optional[str] = None
    clinical_notes: Optional[str] = None
    photo_taken_at: Optional[str] = None  # ISO datetime
    is_primary: bool = Field(default=False)
    visit_id: Optional[int] = None  # Associate with a specific visit

class CasePhotoResponse(BaseModel):
    id: int
    case_id: int
    visit_id: Optional[int]
    photo_type: str
    sequence_number: int
    file_name: str
    file_url: str
    thumbnail_url: Optional[str]
    body_part: Optional[str]
    body_part_detail: Optional[str]
    description: Optional[str]
    clinical_notes: Optional[str]
    photo_taken_at: Optional[str]
    uploaded_at: str
    is_primary: bool
    comparison_pair_id: Optional[int]
    ai_detected_changes: Optional[str]
    ai_improvement_score: Optional[float]

class BeforeAfterComparison(BaseModel):
    case_id: int
    case_title: str
    body_part: Optional[str]
    before_photo: Optional[CasePhotoResponse]
    after_photo: Optional[CasePhotoResponse]
    progress_photos: List[CasePhotoResponse]
    ai_comparison_analysis: Optional[str]
    visual_improvement_score: Optional[float]
    days_between: Optional[int]

# Case Analysis
class CaseAnalysisRequest(BaseModel):
    analysis_type: str = Field(default="comprehensive")  # comprehensive, progress_review, outcome_assessment, photo_comparison
    include_photos: bool = Field(default=True)
    include_reports: bool = Field(default=True)
    from_date: Optional[str] = None
    to_date: Optional[str] = None

class CaseAnalysisResponse(BaseModel):
    id: int
    case_id: int
    analysis_type: str
    model_used: str
    confidence_score: Optional[float]
    case_overview: Optional[str]
    presenting_complaint_summary: Optional[str]
    clinical_findings_summary: Optional[str]
    diagnosis_assessment: Optional[str]
    treatment_timeline: Optional[List[dict]]
    treatment_effectiveness: Optional[str]
    treatment_effectiveness_score: Optional[float]
    progress_assessment: Optional[str]
    improvement_indicators: Optional[List[dict]]
    photo_comparison_analysis: Optional[str]
    visual_improvement_score: Optional[float]
    current_status_assessment: Optional[str]
    recommended_next_steps: Optional[List[dict]]
    follow_up_recommendations: Optional[str]
    red_flags: List[dict]
    patient_friendly_summary: Optional[str]
    analyzed_at: str
```

### 4.2 Database Manager Methods

#### File: `database.py` (add new methods)

```python
# ============================================================
# CASE MANAGEMENT METHODS
# ============================================================

async def create_case(self, case_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Create a new patient case/episode"""
    try:
        response = await self.supabase.table("patient_cases").insert(case_data).execute()
        if response.data:
            # Invalidate patient cases cache
            if self.cache:
                await self.cache.delete(f"patient_cases:{case_data['patient_id']}:{case_data['doctor_firebase_uid']}")
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error creating case: {e}")
        return None

async def get_case_by_id(self, case_id: int, doctor_firebase_uid: str) -> Optional[Dict[str, Any]]:
    """Get case by ID (CACHED)"""
    try:
        if self.cache:
            cache_key = f"case:{case_id}:{doctor_firebase_uid}"
            cached = await self.cache.get(cache_key)
            if cached:
                return cached
        
        response = await self.supabase.table("patient_cases") \
            .select("*") \
            .eq("id", case_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .execute()
        
        result = response.data[0] if response.data else None
        
        if self.cache and result:
            await self.cache.set(cache_key, result, ttl=300)
        
        return result
    except Exception as e:
        print(f"Error fetching case: {e}")
        return None

async def get_cases_by_patient(
    self, 
    patient_id: int, 
    doctor_firebase_uid: str,
    status: str = None,
    case_type: str = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get all cases for a patient"""
    try:
        query = self.supabase.table("patient_cases") \
            .select("*") \
            .eq("patient_id", patient_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid)
        
        if status:
            query = query.eq("status", status)
        if case_type:
            query = query.eq("case_type", case_type)
        
        response = await query.order("started_at", desc=True).limit(limit).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching patient cases: {e}")
        return []

async def get_active_cases_for_doctor(
    self, 
    doctor_firebase_uid: str,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Get all active cases for a doctor"""
    try:
        response = await self.supabase.table("patient_cases") \
            .select("*, patients(first_name, last_name, phone)") \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .in_("status", ["active", "ongoing"]) \
            .order("last_visit_date", desc=True, nullsfirst=False) \
            .limit(limit) \
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching active cases: {e}")
        return []

async def update_case(
    self, 
    case_id: int, 
    doctor_firebase_uid: str, 
    update_data: Dict[str, Any]
) -> bool:
    """Update a case"""
    try:
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        response = await self.supabase.table("patient_cases") \
            .update(update_data) \
            .eq("id", case_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .execute()
        
        if response.data and self.cache:
            await self.cache.delete(f"case:{case_id}:{doctor_firebase_uid}")
        
        return bool(response.data)
    except Exception as e:
        print(f"Error updating case: {e}")
        return False

async def resolve_case(
    self, 
    case_id: int, 
    doctor_firebase_uid: str,
    resolution_data: Dict[str, Any]
) -> bool:
    """Mark a case as resolved"""
    try:
        update_data = {
            "status": "resolved",
            "resolved_at": datetime.now(timezone.utc).date().isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **resolution_data
        }
        
        return await self.update_case(case_id, doctor_firebase_uid, update_data)
    except Exception as e:
        print(f"Error resolving case: {e}")
        return False

async def delete_case(self, case_id: int, doctor_firebase_uid: str) -> bool:
    """Delete a case and unlink its visits (visits remain, just unlinked)"""
    try:
        # First unlink all visits from this case
        await self.supabase.table("visits") \
            .update({"case_id": None, "is_case_opener": False}) \
            .eq("case_id", case_id) \
            .execute()
        
        # Delete case photos (cascade should handle this, but being explicit)
        await self.supabase.table("case_photos") \
            .delete() \
            .eq("case_id", case_id) \
            .execute()
        
        # Delete case analyses
        await self.supabase.table("ai_case_analysis") \
            .delete() \
            .eq("case_id", case_id) \
            .execute()
        
        # Delete the case
        response = await self.supabase.table("patient_cases") \
            .delete() \
            .eq("id", case_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .execute()
        
        if response.data and self.cache:
            await self.cache.delete(f"case:{case_id}:{doctor_firebase_uid}")
        
        return bool(response.data)
    except Exception as e:
        print(f"Error deleting case: {e}")
        return False

async def get_case_with_details(
    self, 
    case_id: int, 
    doctor_firebase_uid: str
) -> Optional[Dict[str, Any]]:
    """Get case with visits, photos, and reports"""
    try:
        # Get case
        case = await self.get_case_by_id(case_id, doctor_firebase_uid)
        if not case:
            return None
        
        # Get related data in parallel
        visits_task = self.get_visits_by_case(case_id, doctor_firebase_uid)
        photos_task = self.get_case_photos(case_id, doctor_firebase_uid)
        reports_task = self.get_reports_by_case(case_id, doctor_firebase_uid)
        analysis_task = self.get_latest_case_analysis(case_id, doctor_firebase_uid)
        
        visits, photos, reports, analysis = await asyncio.gather(
            visits_task, photos_task, reports_task, analysis_task
        )
        
        return {
            **case,
            "visits": visits,
            "photos": photos,
            "reports": reports,
            "latest_analysis": analysis
        }
    except Exception as e:
        print(f"Error fetching case with details: {e}")
        return None

# ============================================================
# CASE PHOTOS METHODS
# ============================================================

async def create_case_photo(self, photo_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Create a case photo record"""
    try:
        # Get next sequence number for this photo type
        existing = await self.supabase.table("case_photos") \
            .select("sequence_number") \
            .eq("case_id", photo_data["case_id"]) \
            .eq("photo_type", photo_data["photo_type"]) \
            .order("sequence_number", desc=True) \
            .limit(1) \
            .execute()
        
        photo_data["sequence_number"] = (existing.data[0]["sequence_number"] + 1) if existing.data else 1
        
        response = await self.supabase.table("case_photos").insert(photo_data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error creating case photo: {e}")
        return None

async def get_case_photos(
    self, 
    case_id: int, 
    doctor_firebase_uid: str,
    photo_type: str = None
) -> List[Dict[str, Any]]:
    """Get all photos for a case"""
    try:
        query = self.supabase.table("case_photos") \
            .select("*") \
            .eq("case_id", case_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid)
        
        if photo_type:
            query = query.eq("photo_type", photo_type)
        
        response = await query.order("photo_type").order("sequence_number").execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching case photos: {e}")
        return []

async def get_case_comparison_photos(
    self, 
    case_id: int, 
    doctor_firebase_uid: str
) -> Dict[str, Any]:
    """Get before/after comparison for a case"""
    try:
        photos = await self.get_case_photos(case_id, doctor_firebase_uid)
        
        before_photos = [p for p in photos if p["photo_type"] == "before"]
        progress_photos = [p for p in photos if p["photo_type"] == "progress"]
        after_photos = [p for p in photos if p["photo_type"] == "after"]
        
        # Get primary photos
        primary_before = next((p for p in before_photos if p["is_primary"]), before_photos[0] if before_photos else None)
        primary_after = next((p for p in after_photos if p["is_primary"]), after_photos[0] if after_photos else None)
        
        days_between = None
        if primary_before and primary_after:
            before_date = datetime.fromisoformat(primary_before["uploaded_at"].replace("Z", "+00:00"))
            after_date = datetime.fromisoformat(primary_after["uploaded_at"].replace("Z", "+00:00"))
            days_between = (after_date - before_date).days
        
        return {
            "before_photo": primary_before,
            "after_photo": primary_after,
            "progress_photos": progress_photos,
            "all_before": before_photos,
            "all_after": after_photos,
            "days_between": days_between
        }
    except Exception as e:
        print(f"Error fetching comparison photos: {e}")
        return {}

async def delete_case_photo(
    self, 
    photo_id: int, 
    doctor_firebase_uid: str
) -> Optional[str]:
    """Delete a case photo, returns storage_path for file cleanup"""
    try:
        # Get photo first to return storage path
        photo_response = await self.supabase.table("case_photos") \
            .select("storage_path") \
            .eq("id", photo_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .execute()
        
        storage_path = photo_response.data[0]["storage_path"] if photo_response.data else None
        
        # Delete record
        await self.supabase.table("case_photos") \
            .delete() \
            .eq("id", photo_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .execute()
        
        return storage_path
    except Exception as e:
        print(f"Error deleting case photo: {e}")
        return None

# ============================================================
# VISIT METHODS (MODIFIED FOR CASES)
# ============================================================

async def get_visits_by_case(
    self, 
    case_id: int, 
    doctor_firebase_uid: str
) -> List[Dict[str, Any]]:
    """Get all visits for a specific case"""
    try:
        response = await self.supabase.table("visits") \
            .select("*") \
            .eq("case_id", case_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .order("visit_date", desc=True) \
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching visits by case: {e}")
        return []

async def assign_visit_to_case(
    self, 
    visit_id: int, 
    case_id: int, 
    doctor_firebase_uid: str,
    is_case_opener: bool = False
) -> bool:
    """Assign an existing visit to a case"""
    try:
        # Verify visit and case belong to same patient and doctor
        visit = await self.get_visit_by_id(visit_id, doctor_firebase_uid)
        case = await self.get_case_by_id(case_id, doctor_firebase_uid)
        
        if not visit or not case:
            return False
        if visit["patient_id"] != case["patient_id"]:
            return False
        
        response = await self.supabase.table("visits") \
            .update({
                "case_id": case_id,
                "is_case_opener": is_case_opener,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }) \
            .eq("id", visit_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .execute()
        
        return bool(response.data)
    except Exception as e:
        print(f"Error assigning visit to case: {e}")
        return False

async def unassign_visit_from_case(
    self, 
    visit_id: int, 
    doctor_firebase_uid: str
) -> bool:
    """Remove a visit from its case"""
    try:
        response = await self.supabase.table("visits") \
            .update({
                "case_id": None,
                "is_case_opener": False,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }) \
            .eq("id", visit_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .execute()
        
        return bool(response.data)
    except Exception as e:
        print(f"Error unassigning visit from case: {e}")
        return False

async def get_unassigned_visits(
    self, 
    patient_id: int, 
    doctor_firebase_uid: str,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get visits not assigned to any case"""
    try:
        response = await self.supabase.table("visits") \
            .select("*") \
            .eq("patient_id", patient_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .is_("case_id", "null") \
            .order("visit_date", desc=True) \
            .limit(limit) \
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching unassigned visits: {e}")
        return []

# ============================================================
# REPORTS BY CASE
# ============================================================

async def get_reports_by_case(
    self, 
    case_id: int, 
    doctor_firebase_uid: str
) -> List[Dict[str, Any]]:
    """Get all reports for a case"""
    try:
        response = await self.supabase.table("reports") \
            .select("*") \
            .eq("case_id", case_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .order("uploaded_at", desc=True) \
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching reports by case: {e}")
        return []

async def assign_report_to_case(
    self, 
    report_id: int, 
    case_id: int, 
    doctor_firebase_uid: str
) -> bool:
    """Assign a report to a case"""
    try:
        response = await self.supabase.table("reports") \
            .update({"case_id": case_id}) \
            .eq("id", report_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .execute()
        return bool(response.data)
    except Exception as e:
        print(f"Error assigning report to case: {e}")
        return False

# ============================================================
# CASE ANALYSIS METHODS
# ============================================================

async def create_case_analysis(
    self, 
    analysis_data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Create a case analysis record"""
    try:
        response = await self.supabase.table("ai_case_analysis").insert(analysis_data).execute()
        
        if response.data:
            # Update case with latest analysis reference
            await self.supabase.table("patient_cases") \
                .update({
                    "latest_ai_analysis_id": response.data[0]["id"],
                    "ai_summary": analysis_data.get("patient_friendly_summary"),
                    "ai_treatment_effectiveness": analysis_data.get("treatment_effectiveness_score")
                }) \
                .eq("id", analysis_data["case_id"]) \
                .execute()
            
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error creating case analysis: {e}")
        return None

async def get_latest_case_analysis(
    self, 
    case_id: int, 
    doctor_firebase_uid: str
) -> Optional[Dict[str, Any]]:
    """Get the most recent analysis for a case"""
    try:
        response = await self.supabase.table("ai_case_analysis") \
            .select("*") \
            .eq("case_id", case_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .order("analyzed_at", desc=True) \
            .limit(1) \
            .execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error fetching case analysis: {e}")
        return None

async def get_case_analysis_history(
    self, 
    case_id: int, 
    doctor_firebase_uid: str,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Get analysis history for a case"""
    try:
        response = await self.supabase.table("ai_case_analysis") \
            .select("*") \
            .eq("case_id", case_id) \
            .eq("doctor_firebase_uid", doctor_firebase_uid) \
            .order("analyzed_at", desc=True) \
            .limit(limit) \
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching case analysis history: {e}")
        return []
```

### 4.3 Remove Linked Visits Code

#### Files to modify:

1. **`app.py`**: Remove these endpoints:
   - `GET /visits/{visit_id}/linked-visits`
   - `POST /visits/{visit_id}/link-to-visit`
   - `DELETE /visits/{visit_id}/unlink`
   - `GET /visits/{visit_id}/context-for-analysis` (replace with case context)

2. **`database.py`**: Remove these methods:
   - `get_child_visits()`
   - `get_visit_chain()`
   - `link_visit_to_parent()`

3. **`VisitCreate` model**: Remove:
   - `parent_visit_id`
   - `link_reason`

4. **`VisitUpdate` model**: Remove:
   - `parent_visit_id`
   - `link_reason`

5. **`Visit` model**: Remove:
   - `parent_visit_id`
   - `link_reason`

---

## 5. AI Analysis Refactoring

### 5.1 New AI Schemas

#### File: `ai_schemas.py` (add new schemas)

```python
# ============================================================
# CASE-BASED AI ANALYSIS SCHEMAS
# ============================================================

CASE_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "case_overview": {
            "type": "string",
            "description": "Brief overview of the case and medical problem"
        },
        "presenting_complaint_summary": {
            "type": "string",
            "description": "Summary of initial presenting symptoms and complaints"
        },
        "clinical_findings_summary": {
            "type": "string",
            "description": "Summary of clinical examination findings across all visits"
        },
        "diagnosis_assessment": {
            "type": "string",
            "description": "Assessment of diagnosis accuracy and evolution"
        },
        "treatment_timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "treatment": {"type": "string"},
                    "response": {"type": "string"},
                    "adjustments_made": {"type": "string"}
                }
            },
            "description": "Timeline of treatments and patient responses"
        },
        "treatment_effectiveness": {
            "type": "string",
            "description": "Overall assessment of treatment effectiveness"
        },
        "treatment_effectiveness_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Score from 0-1 indicating treatment effectiveness"
        },
        "medications_analysis": {
            "type": "object",
            "properties": {
                "medications_used": {"type": "array", "items": {"type": "string"}},
                "effectiveness_notes": {"type": "string"},
                "side_effects_noted": {"type": "array", "items": {"type": "string"}},
                "recommendations": {"type": "string"}
            }
        },
        "progress_assessment": {
            "type": "string",
            "description": "Assessment of patient's progress over the case duration"
        },
        "improvement_indicators": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "indicator": {"type": "string"},
                    "baseline": {"type": "string"},
                    "current": {"type": "string"},
                    "change_direction": {"type": "string", "enum": ["improved", "worsened", "unchanged"]},
                    "significance": {"type": "string"}
                }
            }
        },
        "photo_comparison_analysis": {
            "type": "string",
            "description": "Analysis of visual changes between before/after photos"
        },
        "visual_improvement_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Score from 0-1 indicating visual improvement"
        },
        "current_status_assessment": {
            "type": "string",
            "description": "Current status of the condition"
        },
        "recommended_next_steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "timeframe": {"type": "string"},
                    "rationale": {"type": "string"}
                }
            }
        },
        "follow_up_recommendations": {
            "type": "string",
            "description": "Specific follow-up recommendations"
        },
        "red_flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "flag": {"type": "string"},
                    "severity": {"type": "string", "enum": ["critical", "high", "medium"]},
                    "recommended_action": {"type": "string"}
                }
            }
        },
        "patient_friendly_summary": {
            "type": "string",
            "description": "Summary in simple language suitable for sharing with patient"
        },
        "confidence_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
        }
    },
    "required": [
        "case_overview",
        "treatment_effectiveness",
        "progress_assessment",
        "current_status_assessment",
        "patient_friendly_summary",
        "confidence_score"
    ]
}

PHOTO_COMPARISON_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_assessment": {
            "type": "string",
            "description": "Overall assessment of visual changes"
        },
        "visible_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "area": {"type": "string"},
                    "change_description": {"type": "string"},
                    "improvement_level": {"type": "string", "enum": ["significant", "moderate", "mild", "none", "worsened"]}
                }
            }
        },
        "improvement_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Overall visual improvement score"
        },
        "healing_stage": {
            "type": "string",
            "description": "Current healing stage based on visual appearance"
        },
        "concerns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Any visual concerns that need attention"
        },
        "patient_summary": {
            "type": "string",
            "description": "Patient-friendly description of progress"
        }
    },
    "required": ["overall_assessment", "improvement_score", "patient_summary"]
}
```

### 5.2 AI Analysis Service Changes

#### File: `ai_analysis_service.py` (add new methods)

```python
async def analyze_case(
    self,
    case: Dict[str, Any],
    visits: List[Dict[str, Any]],
    reports: List[Dict[str, Any]],
    photos: List[Dict[str, Any]],
    patient: Dict[str, Any],
    analysis_type: str = "comprehensive"
) -> Dict[str, Any]:
    """
    Perform comprehensive AI analysis on a case.
    This replaces visit-chain analysis with case-focused analysis.
    """
    try:
        # Build context prompt
        context = self._build_case_context(case, visits, reports, patient)
        
        # Include photos if available
        photo_urls = []
        if photos:
            before_photos = [p for p in photos if p["photo_type"] == "before"]
            after_photos = [p for p in photos if p["photo_type"] == "after"]
            progress_photos = [p for p in photos if p["photo_type"] == "progress"]
            
            # Add photos for vision analysis
            for p in before_photos[:2]:  # Limit to 2 before photos
                photo_urls.append({"url": p["file_url"], "label": f"BEFORE ({p.get('body_part', 'N/A')})"})
            for p in progress_photos[:3]:  # Limit to 3 progress photos
                photo_urls.append({"url": p["file_url"], "label": f"PROGRESS ({p.get('uploaded_at', 'N/A')[:10]})"})
            for p in after_photos[:2]:  # Limit to 2 after photos
                photo_urls.append({"url": p["file_url"], "label": f"AFTER ({p.get('body_part', 'N/A')})"})
        
        prompt = f"""
You are analyzing a medical case (episode of care) for a patient.

CASE INFORMATION:
- Case Title: {case['case_title']}
- Case Type: {case['case_type']}
- Status: {case['status']}
- Started: {case['started_at']}
- Chief Complaint: {case['chief_complaint']}
- Initial Diagnosis: {case.get('initial_diagnosis', 'Not specified')}
- Severity: {case.get('severity', 'Not specified')}

PATIENT CONTEXT:
{context['patient_summary']}

VISIT HISTORY FOR THIS CASE ({len(visits)} visits):
{context['visits_summary']}

REPORTS/TESTS FOR THIS CASE ({len(reports)} reports):
{context['reports_summary']}

{"PHOTOS AVAILABLE: " + str(len(photos)) + " photos (before/progress/after)" if photos else "NO PHOTOS AVAILABLE"}

Please provide a comprehensive analysis of this case following the structured format.
Focus on:
1. Treatment effectiveness and patient response
2. Progress over time
3. Visual changes (if photos provided)
4. Recommended next steps
5. Any red flags or concerns
"""

        # Call Gemini with schema
        if photo_urls:
            result = await self._call_gemini_with_vision(
                prompt=prompt,
                image_urls=photo_urls,
                schema=CASE_ANALYSIS_SCHEMA
            )
        else:
            result = await self._call_gemini_with_schema(
                prompt=prompt,
                schema=CASE_ANALYSIS_SCHEMA
            )
        
        return result
        
    except Exception as e:
        print(f"Error analyzing case: {e}")
        return {"error": str(e), "analysis_success": False}

async def compare_case_photos(
    self,
    case: Dict[str, Any],
    before_photo: Dict[str, Any],
    after_photo: Dict[str, Any],
    progress_photos: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    AI comparison of before/after photos for a case.
    """
    try:
        photo_urls = [
            {"url": before_photo["file_url"], "label": "BEFORE"},
            {"url": after_photo["file_url"], "label": "AFTER"}
        ]
        
        if progress_photos:
            for i, p in enumerate(progress_photos[:3]):
                photo_urls.insert(-1, {"url": p["file_url"], "label": f"PROGRESS {i+1}"})
        
        prompt = f"""
Analyze the visual progression of this medical condition.

CASE: {case['case_title']}
CONDITION: {case['chief_complaint']}
DIAGNOSIS: {case.get('initial_diagnosis', 'Not specified')}
BODY PART: {before_photo.get('body_part', 'Not specified')}

Compare the BEFORE and AFTER images (and any PROGRESS images) to assess:
1. Visual changes and improvements
2. Healing progress
3. Any concerning areas
4. Overall improvement score

Provide analysis suitable for medical documentation and patient communication.
"""

        result = await self._call_gemini_with_vision(
            prompt=prompt,
            image_urls=photo_urls,
            schema=PHOTO_COMPARISON_SCHEMA
        )
        
        return result
        
    except Exception as e:
        print(f"Error comparing photos: {e}")
        return {"error": str(e)}

def _build_case_context(
    self, 
    case: Dict[str, Any],
    visits: List[Dict[str, Any]],
    reports: List[Dict[str, Any]],
    patient: Dict[str, Any]
) -> Dict[str, str]:
    """Build context strings for case analysis"""
    
    # Patient summary
    age = self._calculate_age(patient.get("date_of_birth"))
    patient_summary = f"""
- Name: {patient['first_name']} {patient['last_name']}
- Age: {age} years
- Gender: {patient.get('gender', 'Unknown')}
- Blood Group: {patient.get('blood_group', 'Unknown')}
- Allergies: {patient.get('allergies', 'None reported')}
- Medical History: {patient.get('medical_history', 'None reported')}
"""
    
    # Visits summary (chronological)
    visits_sorted = sorted(visits, key=lambda v: v['visit_date'])
    visits_lines = []
    for v in visits_sorted:
        visits_lines.append(f"""
Visit Date: {v['visit_date']}
Type: {v['visit_type']}
Complaint: {v['chief_complaint']}
Symptoms: {v.get('symptoms', 'N/A')}
Diagnosis: {v.get('diagnosis', 'N/A')}
Medications: {v.get('medications', 'N/A')}
Clinical Notes: {v.get('clinical_examination', 'N/A')}
---""")
    visits_summary = "\n".join(visits_lines) if visits_lines else "No visits recorded"
    
    # Reports summary
    reports_lines = []
    for r in reports:
        reports_lines.append(f"- {r.get('test_type', 'Unknown')} ({r['file_name']}) - {r['uploaded_at'][:10]}")
    reports_summary = "\n".join(reports_lines) if reports_lines else "No reports uploaded"
    
    return {
        "patient_summary": patient_summary,
        "visits_summary": visits_summary,
        "reports_summary": reports_summary
    }
```

### 5.3 Background Processor Changes

#### File: `ai_analysis_processor.py`

Add case analysis processing:

```python
async def process_case_analysis(self, case_id: int, doctor_firebase_uid: str):
    """Process AI analysis for a case"""
    try:
        # Get case with all details
        case = await self.db.get_case_with_details(case_id, doctor_firebase_uid)
        if not case:
            return None
        
        # Get patient
        patient = await self.db.get_patient_by_id(case["patient_id"], doctor_firebase_uid)
        
        # Run analysis
        result = await self.ai_service.analyze_case(
            case=case,
            visits=case.get("visits", []),
            reports=case.get("reports", []),
            photos=case.get("photos", []),
            patient=patient
        )
        
        # Store analysis
        analysis_data = {
            "case_id": case_id,
            "patient_id": case["patient_id"],
            "doctor_firebase_uid": doctor_firebase_uid,
            "analysis_type": "comprehensive",
            "visits_analyzed": [v["id"] for v in case.get("visits", [])],
            "reports_analyzed": [r["id"] for r in case.get("reports", [])],
            "photos_analyzed": [p["id"] for p in case.get("photos", [])],
            "model_used": "gemini-2.0-flash",
            "raw_analysis": json.dumps(result),
            "structured_data": result,
            **self._extract_analysis_fields(result)
        }
        
        created = await self.db.create_case_analysis(analysis_data)
        return created
        
    except Exception as e:
        print(f"Error processing case analysis: {e}")
        return None
```

---

## 6. API Endpoints

### 6.1 Case Management Endpoints

```python
# ============================================================
# CASE ENDPOINTS
# ============================================================

@app.post("/patients/{patient_id}/cases", response_model=dict, tags=["Cases"])
async def create_case(
    patient_id: int,
    case_data: CaseCreate,
    current_doctor = Depends(get_current_doctor)
):
    """Create a new case for a patient"""
    pass

@app.get("/patients/{patient_id}/cases", response_model=List[CaseSummary], tags=["Cases"])
async def get_patient_cases(
    patient_id: int,
    status: Optional[str] = Query(None, description="Filter by status: active, resolved, ongoing"),
    case_type: Optional[str] = Query(None, description="Filter by type: acute, chronic, preventive"),
    current_doctor = Depends(get_current_doctor)
):
    """Get all cases for a patient"""
    pass

@app.get("/cases/active", response_model=List[CaseSummary], tags=["Cases"])
async def get_active_cases(
    current_doctor = Depends(get_current_doctor)
):
    """Get all active cases for the doctor"""
    pass

@app.get("/cases/{case_id}", response_model=CaseWithDetails, tags=["Cases"])
async def get_case_details(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get full case details including visits, photos, and reports"""
    pass

@app.put("/cases/{case_id}", response_model=dict, tags=["Cases"])
async def update_case(
    case_id: int,
    case_update: CaseUpdate,
    current_doctor = Depends(get_current_doctor)
):
    """Update case details"""
    pass

@app.post("/cases/{case_id}/resolve", response_model=dict, tags=["Cases"])
async def resolve_case(
    case_id: int,
    resolution: CaseResolve,
    current_doctor = Depends(get_current_doctor)
):
    """Mark a case as resolved"""
    pass

@app.delete("/cases/{case_id}", response_model=dict, tags=["Cases"])
async def delete_case(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Delete a case (visits remain unlinked)"""
    pass

@app.get("/cases/{case_id}/timeline", response_model=dict, tags=["Cases"])
async def get_case_timeline(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get chronological timeline of case events"""
    pass

# ============================================================
# CASE PHOTOS ENDPOINTS
# ============================================================

@app.post("/cases/{case_id}/photos", response_model=CasePhotoResponse, tags=["Case Photos"])
async def upload_case_photo(
    case_id: int,
    photo_type: PhotoType = Form(...),
    body_part: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    is_primary: bool = Form(False),
    file: UploadFile = File(...),
    current_doctor = Depends(get_current_doctor)
):
    """Upload a photo for a case"""
    pass

@app.get("/cases/{case_id}/photos", response_model=List[CasePhotoResponse], tags=["Case Photos"])
async def get_case_photos(
    case_id: int,
    photo_type: Optional[str] = Query(None),
    current_doctor = Depends(get_current_doctor)
):
    """Get all photos for a case"""
    pass

@app.get("/cases/{case_id}/comparison", response_model=BeforeAfterComparison, tags=["Case Photos"])
async def get_before_after_comparison(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get before/after photo comparison for a case"""
    pass

@app.delete("/cases/{case_id}/photos/{photo_id}", response_model=dict, tags=["Case Photos"])
async def delete_case_photo(
    case_id: int,
    photo_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Delete a case photo"""
    pass

@app.put("/cases/{case_id}/photos/{photo_id}/set-primary", response_model=dict, tags=["Case Photos"])
async def set_primary_photo(
    case_id: int,
    photo_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Set a photo as the primary for its type"""
    pass

# ============================================================
# CASE-VISIT ASSIGNMENT ENDPOINTS
# ============================================================

@app.post("/visits/{visit_id}/assign-to-case", response_model=dict, tags=["Cases"])
async def assign_visit_to_case(
    visit_id: int,
    case_id: int = Body(..., embed=True),
    current_doctor = Depends(get_current_doctor)
):
    """Assign an existing visit to a case"""
    pass

@app.delete("/visits/{visit_id}/unassign-from-case", response_model=dict, tags=["Cases"])
async def unassign_visit_from_case(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Remove a visit from its case"""
    pass

@app.get("/patients/{patient_id}/unassigned-visits", response_model=List[Visit], tags=["Cases"])
async def get_unassigned_visits(
    patient_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get visits not assigned to any case"""
    pass

# ============================================================
# CASE AI ANALYSIS ENDPOINTS
# ============================================================

@app.post("/cases/{case_id}/analyze", response_model=dict, tags=["Case Analysis"])
async def trigger_case_analysis(
    case_id: int,
    request: CaseAnalysisRequest = Body(default=CaseAnalysisRequest()),
    current_doctor = Depends(get_current_doctor)
):
    """Trigger AI analysis for a case"""
    pass

@app.get("/cases/{case_id}/analysis", response_model=CaseAnalysisResponse, tags=["Case Analysis"])
async def get_case_analysis(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Get latest AI analysis for a case"""
    pass

@app.get("/cases/{case_id}/analysis/history", response_model=List[CaseAnalysisResponse], tags=["Case Analysis"])
async def get_case_analysis_history(
    case_id: int,
    limit: int = Query(10, le=50),
    current_doctor = Depends(get_current_doctor)
):
    """Get analysis history for a case"""
    pass

@app.post("/cases/{case_id}/compare-photos", response_model=dict, tags=["Case Analysis"])
async def analyze_photo_comparison(
    case_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """AI analysis of before/after photos"""
    pass
```

### 6.2 Modified Existing Endpoints

```python
# ============================================================
# MODIFIED VISIT ENDPOINTS
# ============================================================

# VisitCreate model now includes case_id instead of parent_visit_id
class VisitCreate(BaseModel):
    patient_id: int
    case_id: Optional[int] = None  # NEW: Link to case
    visit_date: str
    visit_time: Optional[str] = None
    visit_type: str
    chief_complaint: str
    # ... rest of fields (remove parent_visit_id, link_reason)

@app.post("/patients/{patient_id}/visits", response_model=dict)
async def create_visit(
    patient_id: int,
    visit: VisitCreate,
    current_doctor = Depends(get_current_doctor)
):
    """Create a new visit, optionally linked to a case"""
    # If case_id provided, validate case belongs to same patient
    # If case_id provided and first visit for case, mark is_case_opener=True
    pass
```

---

## 7. Migration Strategy

### 7.1 Data Migration Steps

#### Step 1: Create New Tables (Non-Breaking)
```bash
# Apply migrations 001-008 to create new tables and columns
# This doesn't break existing functionality
```

#### Step 2: Migrate Linked Visits to Cases (Optional)
```sql
-- Migration script to convert linked visit chains to cases
-- Run this only if doctor wants to preserve linked visit data

DO $$
DECLARE
    root_visit RECORD;
    new_case_id BIGINT;
    chain_visits INTEGER[];
BEGIN
    -- Find all root visits (have children but no parent)
    FOR root_visit IN 
        SELECT DISTINCT v.* 
        FROM visits v
        WHERE v.deprecated_parent_visit_id IS NULL
        AND EXISTS (
            SELECT 1 FROM visits child 
            WHERE child.deprecated_parent_visit_id = v.id
        )
    LOOP
        -- Create a case for this visit chain
        INSERT INTO patient_cases (
            patient_id,
            doctor_firebase_uid,
            case_title,
            case_type,
            chief_complaint,
            initial_diagnosis,
            status,
            started_at
        ) VALUES (
            root_visit.patient_id,
            root_visit.doctor_firebase_uid,
            COALESCE(root_visit.diagnosis, root_visit.chief_complaint),
            'acute',
            root_visit.chief_complaint,
            root_visit.diagnosis,
            'active',
            root_visit.visit_date
        ) RETURNING id INTO new_case_id;
        
        -- Link root visit to case
        UPDATE visits SET case_id = new_case_id, is_case_opener = TRUE
        WHERE id = root_visit.id;
        
        -- Link all child visits recursively
        WITH RECURSIVE visit_chain AS (
            SELECT id FROM visits WHERE deprecated_parent_visit_id = root_visit.id
            UNION ALL
            SELECT v.id FROM visits v
            INNER JOIN visit_chain vc ON v.deprecated_parent_visit_id = vc.id
        )
        UPDATE visits SET case_id = new_case_id
        WHERE id IN (SELECT id FROM visit_chain);
        
    END LOOP;
END $$;
```

#### Step 3: Update Application Code
1. Deploy backend with new case endpoints
2. Keep linked visit endpoints temporarily (deprecated)
3. New visits use case_id
4. Frontend migrates to case-based UI

#### Step 4: Remove Deprecated Code
```sql
-- After confirming migration success (e.g., 30 days)
ALTER TABLE visits DROP COLUMN deprecated_parent_visit_id;
ALTER TABLE visits DROP COLUMN deprecated_link_reason;
```

### 7.2 Rollout Timeline

| Week | Action |
|------|--------|
| Week 1 | Deploy database migrations (new tables) |
| Week 1 | Deploy backend with case endpoints (both old and new work) |
| Week 2 | Frontend team implements case UI |
| Week 2-3 | Beta testing with select doctors |
| Week 3 | Run data migration for linked visits → cases |
| Week 4 | Full rollout of case-based UI |
| Week 5 | Deprecation notices for linked visit endpoints |
| Week 8 | Remove deprecated columns and endpoints |

---

## 8. Testing Plan

### 8.1 Unit Tests

```python
# test_cases.py

class TestCaseManagement:
    async def test_create_case(self):
        """Test creating a new case"""
        pass
    
    async def test_create_case_with_initial_visit(self):
        """Test creating case and first visit together"""
        pass
    
    async def test_assign_visit_to_case(self):
        """Test assigning existing visit to case"""
        pass
    
    async def test_case_stats_update(self):
        """Test that case stats update when visits added"""
        pass
    
    async def test_resolve_case(self):
        """Test case resolution"""
        pass

class TestCasePhotos:
    async def test_upload_before_photo(self):
        """Test uploading before photo"""
        pass
    
    async def test_upload_after_photo(self):
        """Test uploading after photo"""
        pass
    
    async def test_get_comparison(self):
        """Test before/after comparison retrieval"""
        pass
    
    async def test_primary_photo_uniqueness(self):
        """Test only one primary photo per type"""
        pass

class TestCaseAnalysis:
    async def test_case_analysis(self):
        """Test AI case analysis"""
        pass
    
    async def test_photo_comparison_analysis(self):
        """Test AI photo comparison"""
        pass
    
    async def test_analysis_without_photos(self):
        """Test analysis works without photos"""
        pass
```

### 8.2 Integration Tests

```python
class TestCaseWorkflow:
    async def test_complete_case_lifecycle(self):
        """
        Full workflow:
        1. Create patient
        2. Create case
        3. Create initial visit
        4. Upload before photo
        5. Add follow-up visits
        6. Upload progress photos
        7. Add reports
        8. Run AI analysis
        9. Upload after photo
        10. Resolve case
        11. Get comparison
        """
        pass
    
    async def test_concurrent_cases(self):
        """Test patient with multiple active cases"""
        pass
    
    async def test_case_deletion(self):
        """Test case deletion preserves visits"""
        pass
```

### 8.3 Load Tests

- Create 1000 cases with 5 visits each
- Upload 3000 photos
- Run concurrent analysis requests
- Measure response times

---

## 9. Rollout Plan

### 9.1 Phase 1: Backend Infrastructure (Week 1)

- [ ] Create database migrations
- [ ] Apply migrations to staging
- [ ] Implement case CRUD operations
- [ ] Implement photo management
- [ ] Write unit tests
- [ ] Deploy to staging

### 9.2 Phase 2: AI Integration (Week 2)

- [ ] Implement case analysis schemas
- [ ] Implement case analysis service
- [ ] Implement photo comparison analysis
- [ ] Test AI analysis quality
- [ ] Deploy to staging

### 9.3 Phase 3: API Completion (Week 2-3)

- [ ] Implement all case endpoints
- [ ] Modify visit endpoints for case support
- [ ] Update API documentation
- [ ] Integration testing
- [ ] Performance testing

### 9.4 Phase 4: Data Migration (Week 3)

- [ ] Backup production database
- [ ] Run linked visit → case migration
- [ ] Verify migration accuracy
- [ ] Keep deprecated columns for rollback

### 9.5 Phase 5: Frontend Integration (Week 3-4)

- [ ] Case list UI
- [ ] Case detail UI
- [ ] Photo upload UI
- [ ] Before/after comparison UI
- [ ] Case analysis display

### 9.6 Phase 6: Full Rollout (Week 4-5)

- [ ] Deploy to production
- [ ] Monitor for issues
- [ ] Gather user feedback
- [ ] Fine-tune AI analysis prompts

### 9.7 Phase 7: Cleanup (Week 8)

- [ ] Remove deprecated endpoints
- [ ] Remove deprecated columns
- [ ] Update documentation
- [ ] Final performance optimization

---

## 10. Future Enhancements

### 10.1 Short-term (1-3 months)

1. **Case Templates**: Pre-defined case types for common conditions
2. **AI Case Suggestions**: AI suggests creating cases based on visit patterns
3. **Case Sharing**: Share case summary with patient via WhatsApp
4. **Bulk Photo Upload**: Upload multiple photos at once

### 10.2 Medium-term (3-6 months)

1. **Case Comparison**: Compare treatment effectiveness across similar cases
2. **AI Treatment Recommendations**: AI suggests treatments based on similar resolved cases
3. **Patient Portal**: Patients can view their case progress
4. **Outcome Analytics**: Dashboard showing case outcomes and effectiveness rates

### 10.3 Long-term (6-12 months)

1. **Multi-doctor Cases**: Cases that span multiple specialists
2. **AI Predictive Analysis**: Predict case outcomes based on early data
3. **Clinical Decision Support**: AI-powered treatment suggestions
4. **Research Data Export**: Anonymized case data for research

---

## Appendix A: API Response Examples

### Create Case Response
```json
{
    "message": "Case created successfully",
    "case_id": 123,
    "case_number": "CASE-2026-0042",
    "initial_visit_id": 456
}
```

### Case with Details Response
```json
{
    "id": 123,
    "case_number": "CASE-2026-0042",
    "case_title": "Skin Rash - Right Arm",
    "case_type": "acute",
    "status": "active",
    "started_at": "2026-01-15",
    "total_visits": 3,
    "total_photos": 5,
    "visits": [...],
    "photos": [...],
    "reports": [...],
    "latest_analysis": {...}
}
```

### Before/After Comparison Response
```json
{
    "case_id": 123,
    "case_title": "Skin Rash - Right Arm",
    "before_photo": {
        "id": 1,
        "file_url": "https://...",
        "uploaded_at": "2026-01-15T10:00:00Z"
    },
    "after_photo": {
        "id": 5,
        "file_url": "https://...",
        "uploaded_at": "2026-01-28T14:00:00Z"
    },
    "progress_photos": [...],
    "ai_comparison_analysis": "Significant improvement observed...",
    "visual_improvement_score": 0.85,
    "days_between": 13
}
```

---

## Appendix B: Database ERD

```
┌─────────────────┐       ┌─────────────────┐
│    patients     │       │     doctors     │
├─────────────────┤       ├─────────────────┤
│ id (PK)         │       │ firebase_uid(PK)│
│ first_name      │       │ email           │
│ last_name       │       │ first_name      │
│ ...             │       │ ...             │
└────────┬────────┘       └────────┬────────┘
         │                         │
         │    ┌────────────────────┴────────────────┐
         │    │                                     │
         ▼    ▼                                     │
┌─────────────────────────────┐                    │
│      patient_cases          │                    │
├─────────────────────────────┤                    │
│ id (PK)                     │                    │
│ patient_id (FK)             │                    │
│ doctor_firebase_uid (FK)    │◄───────────────────┤
│ case_number                 │                    │
│ case_title                  │                    │
│ case_type                   │                    │
│ status                      │                    │
│ ...                         │                    │
└─────────────┬───────────────┘                    │
              │                                     │
    ┌─────────┼─────────┬────────────┐             │
    │         │         │            │             │
    ▼         ▼         ▼            ▼             │
┌────────┐ ┌────────┐ ┌────────┐ ┌────────────┐   │
│ visits │ │case_   │ │reports │ │ai_case_    │   │
│        │ │photos  │ │        │ │analysis    │   │
├────────┤ ├────────┤ ├────────┤ ├────────────┤   │
│id (PK) │ │id (PK) │ │id (PK) │ │id (PK)     │   │
│case_id │ │case_id │ │case_id │ │case_id (FK)│   │
│(FK)    │ │(FK)    │ │(FK)    │ │...         │   │
│...     │ │...     │ │...     │ └────────────┘   │
└────────┘ └────────┘ └────────┘                   │
    │                                              │
    └──────────────────────────────────────────────┘
```

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-18 | System | Initial draft |

---

**END OF DOCUMENT**
