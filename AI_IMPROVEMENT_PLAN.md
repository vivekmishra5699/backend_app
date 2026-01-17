# 🚀 AI System Improvement Plan
## Complete Implementation Roadmap

**Created:** January 17, 2026  
**Estimated Total Duration:** 6-8 weeks  
**Priority:** High - Improves patient care quality and system reliability

---

## 📋 Table of Contents

1. [Phase 1: Foundation Fixes (Week 1-2)](#phase-1-foundation-fixes)
2. [Phase 2: Clinical Intelligence (Week 3-4)](#phase-2-clinical-intelligence)
3. [Phase 3: Performance & UX (Week 5-6)](#phase-3-performance--ux)
4. [Phase 4: Advanced Features (Week 7-8)](#phase-4-advanced-features)
5. [Database Migrations](#database-migrations)
6. [API Changes](#api-changes)
7. [Testing Strategy](#testing-strategy)

---

## Phase 1: Foundation Fixes
### Week 1-2 | Priority: CRITICAL

### 1.1 Switch to Structured JSON Output
**Problem:** Current text parsing in `_parse_analysis_response()` is unreliable.

**Files to Modify:**
- `ai_analysis_service.py`

**Changes:**

```python
# BEFORE (unreliable text parsing):
def _parse_analysis_response(self, analysis_text: str) -> Dict[str, Any]:
    if "DOCUMENT IDENTIFICATION" in line.upper():
        current_section = "document_summary"
    # ... string matching

# AFTER (structured JSON output):
async def _perform_gemini_analysis(self, prompt: str, document_data: Dict[str, Any]) -> Dict[str, Any]:
    response = self.client.models.generate_content(
        model=self.model_name,
        contents=content_parts,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            response_mime_type="application/json",
            response_schema=DOCUMENT_ANALYSIS_SCHEMA  # New schema
        )
    )
```

**New Schema Definition:**
```python
DOCUMENT_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "description": "Type of medical document (CBC, LFT, X-Ray, etc.)"},
        "document_date": {"type": "string", "description": "Date of test/report if available"},
        "document_summary": {"type": "string", "description": "Overall summary of findings"},
        "clinical_correlation": {
            "type": "object",
            "properties": {
                "relevance_to_complaint": {"type": "string"},
                "supports_diagnosis": {"type": "boolean"},
                "diagnosis_validation": {"type": "string"},
                "symptom_explanation": {"type": "string"}
            }
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "parameter": {"type": "string"},
                    "value": {"type": "string"},
                    "reference_range": {"type": "string"},
                    "status": {"type": "string", "enum": ["normal", "borderline", "low", "high", "critical"]},
                    "clinical_significance": {"type": "string"}
                }
            }
        },
        "critical_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding": {"type": "string"},
                    "urgency": {"type": "string", "enum": ["immediate", "24_hours", "48_hours", "routine"]},
                    "recommended_action": {"type": "string"}
                }
            }
        },
        "treatment_evaluation": {
            "type": "object",
            "properties": {
                "current_treatment_appropriate": {"type": "boolean"},
                "modification_needed": {"type": "boolean"},
                "suggestions": {"type": "array", "items": {"type": "string"}}
            }
        },
        "actionable_insights": {
            "type": "array",
            "items": {"type": "string"}
        },
        "patient_communication": {
            "type": "object",
            "properties": {
                "summary_for_patient": {"type": "string"},
                "key_points": {"type": "array", "items": {"type": "string"}},
                "reassurance_needed": {"type": "boolean"}
            }
        },
        "follow_up_recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "test_name": {"type": "string"},
                    "timeframe": {"type": "string"},
                    "reason": {"type": "string"}
                }
            }
        },
        "confidence_score": {"type": "number", "minimum": 0, "maximum": 1}
    },
    "required": ["document_type", "document_summary", "findings", "confidence_score"]
}
```

**Tasks:**
- [ ] Create `ai_schemas.py` with all JSON schemas
- [ ] Modify `_perform_gemini_analysis()` to use JSON mode
- [ ] Update prompt to request JSON format
- [ ] Remove `_parse_analysis_response()` method
- [ ] Update database insert to handle JSON structure
- [ ] Add backward compatibility for existing text analyses

---

### 1.2 Add Critical Findings Alert System
**Problem:** Critical lab values go unnoticed until doctor manually reviews.

**Database Migration:**
```sql
-- Migration: 001_add_clinical_alerts.sql
CREATE TABLE ai_clinical_alerts (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    visit_id INTEGER REFERENCES visits(id),
    report_id INTEGER REFERENCES reports(id),
    analysis_id INTEGER REFERENCES ai_document_analysis(id),
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid),
    
    -- Alert details
    alert_type VARCHAR(50) NOT NULL CHECK (alert_type IN (
        'critical_value', 'abnormal_trend', 'drug_interaction', 
        'allergy_warning', 'urgent_followup', 'diagnosis_change'
    )),
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('critical', 'urgent', 'high', 'medium', 'low')),
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    
    -- Clinical context
    parameter_name VARCHAR(100),
    parameter_value VARCHAR(50),
    reference_range VARCHAR(50),
    
    -- Status tracking
    is_acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    acknowledged_by TEXT,
    action_taken TEXT,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Index for fast lookups
CREATE INDEX idx_alerts_doctor_unack ON ai_clinical_alerts(doctor_firebase_uid, is_acknowledged) 
    WHERE is_acknowledged = FALSE;
CREATE INDEX idx_alerts_patient ON ai_clinical_alerts(patient_id);
CREATE INDEX idx_alerts_severity ON ai_clinical_alerts(severity, created_at DESC);
```

**New Service: `alert_service.py`**
```python
class ClinicalAlertService:
    """Service for creating and managing clinical alerts from AI analyses"""
    
    CRITICAL_VALUES = {
        # Lab values that require immediate attention
        "glucose": {"critical_low": 50, "critical_high": 400, "unit": "mg/dL"},
        "potassium": {"critical_low": 2.5, "critical_high": 6.5, "unit": "mEq/L"},
        "sodium": {"critical_low": 120, "critical_high": 160, "unit": "mEq/L"},
        "hemoglobin": {"critical_low": 7.0, "critical_high": 20, "unit": "g/dL"},
        "platelets": {"critical_low": 20000, "critical_high": 1000000, "unit": "/µL"},
        "creatinine": {"critical_high": 10, "unit": "mg/dL"},
        "inr": {"critical_high": 5, "unit": "ratio"},
        # Add more as needed
    }
    
    async def process_analysis_for_alerts(
        self, 
        analysis_result: Dict, 
        patient_context: Dict,
        visit_context: Dict,
        report_id: int
    ) -> List[Dict]:
        """Extract alerts from structured AI analysis"""
        alerts = []
        
        # 1. Check critical findings from AI
        for finding in analysis_result.get("critical_findings", []):
            alerts.append({
                "alert_type": "critical_value",
                "severity": self._map_urgency_to_severity(finding["urgency"]),
                "title": f"Critical Finding: {finding['finding'][:50]}",
                "message": finding["finding"],
                "recommended_action": finding.get("recommended_action")
            })
        
        # 2. Check for allergy conflicts
        patient_allergies = patient_context.get("allergies", "").lower()
        # ... allergy checking logic
        
        # 3. Check treatment evaluation warnings
        treatment_eval = analysis_result.get("treatment_evaluation", {})
        if treatment_eval.get("modification_needed"):
            alerts.append({
                "alert_type": "urgent_followup",
                "severity": "high",
                "title": "Treatment Modification Recommended",
                "message": "\n".join(treatment_eval.get("suggestions", []))
            })
        
        return alerts
```

**API Endpoints to Add:**
```python
# In app.py

@app.get("/alerts", response_model=List[ClinicalAlert])
async def get_unacknowledged_alerts(current_doctor = Depends(get_current_doctor)):
    """Get all unacknowledged clinical alerts for the doctor"""
    
@app.get("/alerts/count", response_model=dict)
async def get_alert_counts(current_doctor = Depends(get_current_doctor)):
    """Get alert counts by severity for dashboard badge"""

@app.post("/alerts/{alert_id}/acknowledge", response_model=dict)
async def acknowledge_alert(alert_id: int, action_taken: Optional[str] = None):
    """Mark an alert as acknowledged with optional action note"""

@app.get("/patients/{patient_id}/alerts", response_model=List[ClinicalAlert])
async def get_patient_alerts(patient_id: int):
    """Get all alerts for a specific patient"""
```

**Tasks:**
- [ ] Create database migration for `ai_clinical_alerts` table
- [ ] Create `alert_service.py` with `ClinicalAlertService` class
- [ ] Define critical value thresholds
- [ ] Modify `ai_analysis_processor.py` to call alert service after analysis
- [ ] Add API endpoints for alerts
- [ ] Create Pydantic models for alerts
- [ ] Add real-time notification via WebSocket (optional)

---

### 1.3 Fix Analysis Caching
**Problem:** Repeated DB calls for same analysis data.

**Implementation:**
```python
# In database.py - Add caching decorator

from functools import lru_cache
from cachetools import TTLCache
import asyncio

# In-memory cache with TTL
_analysis_cache = TTLCache(maxsize=1000, ttl=300)  # 5 min TTL
_cache_lock = asyncio.Lock()

class DatabaseManager:
    async def get_ai_analysis_by_report_id_cached(
        self, 
        report_id: int, 
        doctor_firebase_uid: str
    ) -> Optional[Dict[str, Any]]:
        """Get AI analysis with caching"""
        cache_key = f"analysis:{report_id}:{doctor_firebase_uid}"
        
        # Check cache first
        if cache_key in _analysis_cache:
            return _analysis_cache[cache_key]
        
        # Fetch from database
        result = await self.get_ai_analysis_by_report_id(report_id, doctor_firebase_uid)
        
        # Cache the result
        if result:
            async with _cache_lock:
                _analysis_cache[cache_key] = result
        
        return result
    
    def invalidate_analysis_cache(self, report_id: int, doctor_firebase_uid: str):
        """Invalidate cache when analysis is updated"""
        cache_key = f"analysis:{report_id}:{doctor_firebase_uid}"
        _analysis_cache.pop(cache_key, None)
```

**Tasks:**
- [ ] Add `cachetools` to requirements.txt
- [ ] Implement caching layer in `database.py`
- [ ] Add cache invalidation on analysis create/update
- [ ] Update API endpoints to use cached methods
- [ ] Add cache statistics endpoint for monitoring

---

### 1.4 Simplify ai_document_analysis Table
**Problem:** Redundant columns storing parsed text that's already in `raw_analysis`.

**Migration:**
```sql
-- Migration: 002_simplify_document_analysis.sql
-- Store structured JSON instead of separate text columns

-- Add new JSON column
ALTER TABLE ai_document_analysis 
ADD COLUMN structured_data JSONB;

-- Migrate existing data (optional - run in batches)
-- UPDATE ai_document_analysis SET structured_data = jsonb_build_object(
--     'document_summary', document_summary,
--     'clinical_significance', clinical_significance,
--     ...
-- );

-- After migration is verified, drop redundant columns:
-- ALTER TABLE ai_document_analysis 
-- DROP COLUMN document_summary,
-- DROP COLUMN clinical_significance,
-- DROP COLUMN correlation_with_patient,
-- DROP COLUMN actionable_insights,
-- DROP COLUMN patient_communication,
-- DROP COLUMN clinical_notes,
-- DROP COLUMN clinical_correlation,
-- DROP COLUMN detailed_findings,
-- DROP COLUMN critical_findings,
-- DROP COLUMN treatment_evaluation;
```

**Tasks:**
- [ ] Create migration to add `structured_data` JSONB column
- [ ] Update `create_ai_analysis()` to store JSON in new column
- [ ] Update API response models to read from JSON
- [ ] Test backward compatibility with old records
- [ ] Create migration to drop old columns (after verification)

---

## Phase 2: Clinical Intelligence
### Week 3-4 | Priority: HIGH

### 2.1 Medication Interaction Checking
**Problem:** No automatic checking for drug interactions.

**New File: `medication_service.py`**
```python
class MedicationInteractionService:
    """Service for checking drug interactions and contraindications"""
    
    # Common interaction database (expand as needed)
    INTERACTIONS = {
        ("warfarin", "aspirin"): {
            "severity": "high",
            "effect": "Increased bleeding risk",
            "recommendation": "Monitor INR closely, consider dose adjustment"
        },
        ("metformin", "contrast_dye"): {
            "severity": "high", 
            "effect": "Risk of lactic acidosis",
            "recommendation": "Hold metformin 48h before and after contrast"
        },
        # ... more interactions
    }
    
    async def check_interactions(
        self,
        current_medications: List[str],
        new_medications: List[str],
        patient_allergies: str
    ) -> List[Dict]:
        """Check for drug-drug and drug-allergy interactions"""
        warnings = []
        
        all_meds = set(m.lower() for m in current_medications + new_medications)
        
        # Check drug-drug interactions
        for (drug1, drug2), interaction in self.INTERACTIONS.items():
            if drug1 in all_meds and drug2 in all_meds:
                warnings.append({
                    "type": "drug_interaction",
                    "drugs": [drug1, drug2],
                    **interaction
                })
        
        # Check allergies
        allergies = [a.strip().lower() for a in patient_allergies.split(",")]
        for med in new_medications:
            if any(allergy in med.lower() for allergy in allergies):
                warnings.append({
                    "type": "allergy_warning",
                    "severity": "critical",
                    "drug": med,
                    "allergy": next(a for a in allergies if a in med.lower()),
                    "recommendation": "DO NOT prescribe - patient has documented allergy"
                })
        
        return warnings
    
    async def enhance_analysis_with_interactions(
        self,
        analysis_result: Dict,
        patient_context: Dict
    ) -> Dict:
        """Add medication interaction warnings to AI analysis"""
        current_meds = patient_context.get("current_medications", [])
        # Extract medications from AI analysis
        extracted_meds = analysis_result.get("extracted_medications", [])
        
        interactions = await self.check_interactions(
            current_meds, 
            extracted_meds,
            patient_context.get("allergies", "")
        )
        
        analysis_result["medication_warnings"] = interactions
        return analysis_result
```

**Integration Points:**
1. Call after document analysis completes
2. Call when prescriptions are created
3. Include in handwritten prescription analysis

**Tasks:**
- [ ] Create `medication_service.py`
- [ ] Build initial interaction database (start with 50 common interactions)
- [ ] Integrate with `ai_analysis_processor.py`
- [ ] Add medication warnings to analysis response
- [ ] Create alerts for critical interactions

---

### 2.2 Historical Trend Analysis
**Problem:** Lab reports analyzed in isolation without historical context.

**Modification to Analysis Prompt:**
```python
def _create_analysis_prompt_with_trends(
    self,
    patient_context: Dict,
    visit_context: Dict,
    doctor_context: Dict,
    file_name: str,
    historical_values: Dict[str, List[Dict]]  # NEW PARAMETER
) -> str:
    """Create prompt with historical lab values for trend analysis"""
    
    # Build trend section
    trend_section = ""
    if historical_values:
        trend_section = """
**📊 HISTORICAL VALUES FOR TREND ANALYSIS:**
Compare current results with these previous values:

"""
        for parameter, history in historical_values.items():
            trend_section += f"**{parameter}:**\n"
            for entry in history[-5:]:  # Last 5 values
                trend_section += f"  - {entry['date']}: {entry['value']} {entry.get('unit', '')}\n"
            trend_section += "\n"
        
        trend_section += """
⚠️ TREND ANALYSIS INSTRUCTIONS:
1. Calculate the trend direction (improving/worsening/stable)
2. Calculate rate of change if concerning
3. Flag any values crossing from normal to abnormal
4. Note if trends indicate treatment effectiveness
5. Predict trajectory if trend continues

"""
    
    # Include in main prompt
    prompt = f"""
... existing prompt content ...

{trend_section}

... rest of prompt ...
"""
    return prompt
```

**New Database Query:**
```python
async def get_historical_lab_values(
    self, 
    patient_id: int, 
    doctor_firebase_uid: str,
    parameters: List[str] = None,
    months_back: int = 12
) -> Dict[str, List[Dict]]:
    """Get historical lab values from previous analyses"""
    
    # Query previous analyses
    analyses = await self.get_ai_analyses_by_patient_id(patient_id, doctor_firebase_uid)
    
    historical = {}
    for analysis in analyses:
        structured = analysis.get("structured_data", {})
        findings = structured.get("findings", [])
        
        for finding in findings:
            param = finding.get("parameter", "").lower()
            if parameters and param not in [p.lower() for p in parameters]:
                continue
            
            if param not in historical:
                historical[param] = []
            
            historical[param].append({
                "date": analysis.get("analyzed_at"),
                "value": finding.get("value"),
                "unit": finding.get("unit"),
                "status": finding.get("status")
            })
    
    # Sort by date
    for param in historical:
        historical[param].sort(key=lambda x: x["date"])
    
    return historical
```

**Tasks:**
- [ ] Modify `_create_analysis_prompt()` to accept historical values
- [ ] Create `get_historical_lab_values()` database method
- [ ] Update `analyze_document()` to fetch and include history
- [ ] Add trend visualization data to API response
- [ ] Update JSON schema to include trend analysis section

---

### 2.3 Smart Visit Summary Generation
**Problem:** Doctors spend time writing visit summaries manually.

**New Endpoint:**
```python
@app.post("/visits/{visit_id}/generate-summary", response_model=dict)
async def generate_visit_summary(
    visit_id: int,
    current_doctor = Depends(get_current_doctor)
):
    """Generate AI-powered visit summary for documentation"""
    
    # Get visit with all related data
    visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
    patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
    reports = await db.get_reports_by_visit_id(visit_id, current_doctor["firebase_uid"])
    analyses = await db.get_ai_analyses_by_visit_id(visit_id, current_doctor["firebase_uid"])
    handwritten_notes = await db.get_handwritten_visit_notes_by_visit_id(visit_id, current_doctor["firebase_uid"])
    
    # Generate summary using AI
    summary = await ai_analysis_service.generate_visit_summary(
        patient_context=patient,
        visit_context=visit,
        reports=reports,
        analyses=analyses,
        handwritten_notes=handwritten_notes,
        doctor_context=current_doctor
    )
    
    return {
        "visit_id": visit_id,
        "summary": summary,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }
```

**New Method in `ai_analysis_service.py`:**
```python
async def generate_visit_summary(
    self,
    patient_context: Dict,
    visit_context: Dict,
    reports: List[Dict],
    analyses: List[Dict],
    handwritten_notes: List[Dict],
    doctor_context: Dict
) -> Dict:
    """Generate structured visit summary for medical records"""
    
    prompt = f"""
Generate a professional medical visit summary in SOAP format for documentation.

PATIENT: {patient_context.get('first_name')} {patient_context.get('last_name')}
VISIT DATE: {visit_context.get('visit_date')}
DOCTOR: Dr. {doctor_context.get('first_name')} {doctor_context.get('last_name')}

VISIT DATA:
- Chief Complaint: {visit_context.get('chief_complaint')}
- Symptoms: {visit_context.get('symptoms')}
- Vitals: {visit_context.get('vitals')}
- Clinical Examination: {visit_context.get('clinical_examination')}
- Diagnosis: {visit_context.get('diagnosis')}
- Treatment Plan: {visit_context.get('treatment_plan')}
- Medications: {visit_context.get('medications')}

REPORTS ANALYZED: {len(reports)}
AI ANALYSES AVAILABLE: {len(analyses)}

Generate a concise, professional SOAP note including:
1. Subjective - Patient's complaints and history
2. Objective - Examination findings and test results
3. Assessment - Diagnosis and clinical reasoning
4. Plan - Treatment plan and follow-up

Also provide:
- ICD-10 codes (if determinable)
- CPT codes for procedures
- Follow-up instructions
"""
    
    # Use structured output
    response = await self._generate_structured_response(prompt, SOAP_NOTE_SCHEMA)
    return response
```

**Tasks:**
- [ ] Create `generate_visit_summary()` method
- [ ] Define SOAP note JSON schema
- [ ] Add API endpoint
- [ ] Store generated summaries in visits table (new column)
- [ ] Add option to edit/approve generated summary

---

### 2.4 Patient Risk Scoring
**Problem:** No quick way to identify high-risk patients.

**New Table:**
```sql
-- Migration: 003_add_patient_risk_scores.sql
CREATE TABLE patient_risk_scores (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid),
    
    -- Risk scores (0-100)
    overall_risk_score INTEGER CHECK (overall_risk_score >= 0 AND overall_risk_score <= 100),
    cardiovascular_risk INTEGER,
    diabetes_risk INTEGER,
    kidney_risk INTEGER,
    liver_risk INTEGER,
    
    -- Risk factors identified
    risk_factors JSONB DEFAULT '[]'::jsonb,
    protective_factors JSONB DEFAULT '[]'::jsonb,
    
    -- Recommendations
    recommendations JSONB DEFAULT '[]'::jsonb,
    
    -- Metadata
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    data_points_used INTEGER,
    confidence_score NUMERIC(3,2),
    
    UNIQUE(patient_id, doctor_firebase_uid)
);
```

**Risk Score Calculation:**
```python
async def calculate_patient_risk_score(
    self,
    patient_context: Dict,
    visits: List[Dict],
    analyses: List[Dict]
) -> Dict:
    """Calculate comprehensive patient risk score using AI"""
    
    prompt = f"""
Analyze this patient's complete medical data and calculate risk scores.

PATIENT DEMOGRAPHICS:
- Age: {self._calculate_age(patient_context.get('date_of_birth'))}
- Gender: {patient_context.get('gender')}
- Blood Group: {patient_context.get('blood_group')}
- Known Allergies: {patient_context.get('allergies')}
- Medical History: {patient_context.get('medical_history')}

VISIT HISTORY: {len(visits)} visits
ANALYSES AVAILABLE: {len(analyses)} AI analyses

Based on all available data, calculate:
1. Overall health risk score (0-100, where 100 is highest risk)
2. Cardiovascular risk score
3. Diabetes risk score  
4. Kidney disease risk score
5. Liver disease risk score

Identify:
- Top risk factors
- Protective factors
- Recommended interventions

Use established medical risk calculators as reference (Framingham, ASCVD, etc.)
"""
    
    return await self._generate_structured_response(prompt, RISK_SCORE_SCHEMA)
```

**Tasks:**
- [ ] Create migration for `patient_risk_scores` table
- [ ] Implement `calculate_patient_risk_score()` method
- [ ] Add API endpoint to get/calculate risk score
- [ ] Add risk score to patient dashboard response
- [ ] Create background job to recalculate scores periodically

---

## Phase 3: Performance & UX
### Week 5-6 | Priority: MEDIUM-HIGH

### 3.1 Optimized Queue Processing
**Problem:** Current queue processes slowly with rate limit issues.

**Improvements to `ai_analysis_processor.py`:**
```python
class AIAnalysisProcessor:
    def __init__(self, db_manager, ai_service):
        self.db = db_manager
        self.ai_service = ai_service
        self.is_running = False
        
        # IMPROVED CONFIGURATION
        self.process_interval = 5  # Reduced from 10 to 5 seconds
        self.max_concurrent = 5    # Increased from 3 to 5
        self.delay_between_analyses = 1  # Reduced from 2 to 1 second
        
        # Priority-based processing
        self.priority_delays = {
            3: 0,    # Urgent - no delay
            2: 0.5,  # Normal - 0.5s delay
            1: 1     # Batch - 1s delay
        }
        
        # Adaptive rate limiting
        self.consecutive_rate_limits = 0
        self.max_rate_limit_backoff = 60  # Max 60 second backoff
        
        # Metrics
        self.metrics = {
            "processed_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "avg_processing_time": 0
        }
    
    async def process_with_adaptive_rate_limiting(self, queue_item: Dict):
        """Process with intelligent rate limit handling"""
        try:
            result = await self.process_single_analysis(queue_item)
            
            # Success - reset rate limit counter
            self.consecutive_rate_limits = 0
            return result
            
        except RateLimitException:
            self.consecutive_rate_limits += 1
            backoff = min(
                2 ** self.consecutive_rate_limits,
                self.max_rate_limit_backoff
            )
            print(f"⚠️ Rate limited. Backing off for {backoff}s")
            await asyncio.sleep(backoff)
            
            # Re-queue with higher priority
            await self.requeue_with_priority(queue_item, priority=3)
```

**Tasks:**
- [ ] Implement adaptive rate limiting
- [ ] Add priority-based delay system
- [ ] Add processing metrics collection
- [ ] Create metrics dashboard endpoint
- [ ] Implement circuit breaker pattern for repeated failures

---

### 3.2 Streaming Responses for Long Operations
**Problem:** Comprehensive history analysis can take 30+ seconds.

**Implementation:**
```python
from fastapi.responses import StreamingResponse
import json

@app.post("/patients/{patient_id}/analyze-comprehensive-history-stream")
async def analyze_patient_history_streaming(
    patient_id: int,
    request_data: PatientHistoryAnalysisRequest,
    current_doctor = Depends(get_current_doctor)
):
    """Stream comprehensive analysis with progress updates"""
    
    async def generate_stream():
        try:
            # Step 1: Loading data
            yield json.dumps({"status": "loading", "message": "Loading patient data...", "progress": 10}) + "\n"
            
            patient = await db.get_patient_by_id(patient_id, current_doctor["firebase_uid"])
            visits = await db.get_visits_by_patient_id(patient_id, current_doctor["firebase_uid"])
            
            yield json.dumps({"status": "loading", "message": f"Found {len(visits)} visits", "progress": 30}) + "\n"
            
            # Step 2: Downloading files
            yield json.dumps({"status": "downloading", "message": "Downloading reports...", "progress": 40}) + "\n"
            
            # ... download logic ...
            
            yield json.dumps({"status": "downloading", "message": "Downloads complete", "progress": 60}) + "\n"
            
            # Step 3: AI Analysis
            yield json.dumps({"status": "analyzing", "message": "Running AI analysis...", "progress": 70}) + "\n"
            
            # Stream AI response chunks
            async for chunk in ai_analysis_service.stream_comprehensive_analysis(...):
                yield json.dumps({"status": "analyzing", "chunk": chunk, "progress": 80}) + "\n"
            
            # Step 4: Saving results
            yield json.dumps({"status": "saving", "message": "Saving results...", "progress": 95}) + "\n"
            
            # ... save logic ...
            
            yield json.dumps({"status": "complete", "message": "Analysis complete", "progress": 100, "result": analysis}) + "\n"
            
        except Exception as e:
            yield json.dumps({"status": "error", "message": str(e)}) + "\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="application/x-ndjson"
    )
```

**Tasks:**
- [ ] Add streaming endpoint for comprehensive analysis
- [ ] Implement `stream_comprehensive_analysis()` in AI service
- [ ] Add progress tracking
- [ ] Update frontend to handle streaming responses

---

### 3.3 Prompt Optimization
**Problem:** Prompts are too long (10,000+ tokens), increasing cost and latency.

**Strategies:**

1. **Context Compression:**
```python
def _compress_visit_context(self, visits: List[Dict], max_visits: int = 10) -> str:
    """Compress visit history to essential information"""
    
    if len(visits) <= max_visits:
        return self._format_visits_detailed(visits)
    
    # For many visits, summarize older ones
    recent_visits = visits[:5]
    older_visits = visits[5:]
    
    # Detailed format for recent
    result = "**RECENT VISITS (Detailed):**\n"
    result += self._format_visits_detailed(recent_visits)
    
    # Summary format for older
    result += "\n**OLDER VISITS (Summary):**\n"
    for v in older_visits[:10]:
        result += f"- {v['visit_date']}: {v['chief_complaint'][:50]} → {v['diagnosis'][:50]}\n"
    
    if len(older_visits) > 10:
        result += f"... and {len(older_visits) - 10} more visits\n"
    
    return result
```

2. **Dynamic Prompt Building:**
```python
def _create_adaptive_prompt(
    self,
    patient_context: Dict,
    visit_context: Dict,
    include_sections: List[str] = None
) -> str:
    """Build prompt with only necessary sections"""
    
    # Base sections always included
    prompt = self._get_base_prompt_section(patient_context, visit_context)
    
    # Optional sections based on context
    if visit_context.get("parent_visit_id"):
        prompt += self._get_followup_section(visit_context)
    
    if patient_context.get("consulted_other_doctor"):
        prompt += self._get_prior_treatment_section(patient_context)
    
    if patient_context.get("allergies"):
        prompt += self._get_allergy_check_section(patient_context)
    
    # Only include sections that are relevant
    return prompt
```

**Tasks:**
- [ ] Audit current prompt token usage
- [ ] Implement context compression for large histories
- [ ] Create adaptive prompt builder
- [ ] A/B test shorter prompts for quality impact
- [ ] Target: 50% reduction in average prompt length

---

### 3.4 Batch Processing API
**Problem:** Analyzing multiple reports requires multiple API calls.

**New Endpoint:**
```python
@app.post("/batch/analyze-reports", response_model=dict)
async def batch_analyze_reports_immediate(
    request: BatchAnalysisRequest,
    current_doctor = Depends(get_current_doctor)
):
    """Analyze multiple reports in a single request"""
    
    results = []
    
    # Process in parallel with concurrency limit
    semaphore = asyncio.Semaphore(3)
    
    async def analyze_with_semaphore(report_id):
        async with semaphore:
            return await analyze_single_report(report_id, current_doctor)
    
    tasks = [analyze_with_semaphore(rid) for rid in request.report_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    return {
        "total_requested": len(request.report_ids),
        "successful": len([r for r in results if not isinstance(r, Exception)]),
        "failed": len([r for r in results if isinstance(r, Exception)]),
        "results": results
    }
```

**Tasks:**
- [ ] Create `BatchAnalysisRequest` model
- [ ] Implement batch endpoint with parallel processing
- [ ] Add progress tracking for batch operations
- [ ] Implement batch result storage

---

## Phase 4: Advanced Features
### Week 7-8 | Priority: MEDIUM

### 4.1 Natural Language Query Interface
**Problem:** Doctors can't easily query patient data naturally.

**Implementation:**
```python
@app.post("/ai/query", response_model=dict)
async def natural_language_query(
    query: str,
    current_doctor = Depends(get_current_doctor)
):
    """
    Answer natural language questions about patients/data.
    
    Examples:
    - "Show me diabetic patients with HbA1c > 8"
    - "Which patients need follow-up this week?"
    - "Find patients on warfarin with recent INR tests"
    """
    
    # Use AI to parse query intent
    intent = await ai_analysis_service.parse_query_intent(query)
    
    # Execute appropriate database query
    if intent["type"] == "patient_search":
        results = await db.search_patients_by_criteria(
            doctor_uid=current_doctor["firebase_uid"],
            criteria=intent["criteria"]
        )
    elif intent["type"] == "analytics":
        results = await db.get_analytics(
            doctor_uid=current_doctor["firebase_uid"],
            metric=intent["metric"]
        )
    
    # Format response with AI
    response = await ai_analysis_service.format_query_response(query, results)
    
    return {
        "query": query,
        "intent": intent,
        "results": results,
        "formatted_response": response
    }
```

**Tasks:**
- [ ] Create query intent parser
- [ ] Build flexible database query builder
- [ ] Implement response formatter
- [ ] Add query history tracking
- [ ] Create common query templates

---

### 4.2 Differential Diagnosis Assistant
**Problem:** No AI support for uncertain diagnoses.

**New Endpoint:**
```python
@app.post("/visits/{visit_id}/differential-diagnosis", response_model=dict)
async def generate_differential_diagnosis(
    visit_id: int,
    symptoms: List[str],
    current_doctor = Depends(get_current_doctor)
):
    """Generate differential diagnosis based on symptoms and test results"""
    
    visit = await db.get_visit_by_id(visit_id, current_doctor["firebase_uid"])
    patient = await db.get_patient_by_id(visit["patient_id"], current_doctor["firebase_uid"])
    analyses = await db.get_ai_analyses_by_visit_id(visit_id, current_doctor["firebase_uid"])
    
    result = await ai_analysis_service.generate_differential_diagnosis(
        patient_context=patient,
        visit_context=visit,
        symptoms=symptoms,
        test_results=analyses,
        doctor_context=current_doctor
    )
    
    return {
        "visit_id": visit_id,
        "differential_diagnoses": result["diagnoses"],
        "recommended_tests": result["tests_to_confirm"],
        "red_flags": result["red_flags"],
        "reasoning": result["clinical_reasoning"]
    }
```

**Tasks:**
- [ ] Create differential diagnosis prompt
- [ ] Define output schema with probability rankings
- [ ] Add recommended confirmatory tests
- [ ] Include red flag symptoms
- [ ] Link to medical references

---

### 4.3 Treatment Effectiveness Tracking
**Problem:** No way to track if treatments are working over time.

**New Table:**
```sql
-- Migration: 004_add_treatment_tracking.sql
CREATE TABLE treatment_effectiveness (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    doctor_firebase_uid TEXT NOT NULL REFERENCES doctors(firebase_uid),
    
    -- Treatment details
    condition VARCHAR(255) NOT NULL,
    treatment_start_date DATE NOT NULL,
    treatment_end_date DATE,
    medications JSONB DEFAULT '[]'::jsonb,
    
    -- Effectiveness metrics
    baseline_metrics JSONB,  -- Metrics at start
    current_metrics JSONB,   -- Latest metrics
    improvement_score INTEGER CHECK (improvement_score >= -100 AND improvement_score <= 100),
    
    -- AI analysis
    ai_assessment TEXT,
    recommendation VARCHAR(50) CHECK (recommendation IN (
        'continue', 'modify', 'discontinue', 'escalate', 'review'
    )),
    
    -- Metadata
    last_evaluated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**Tasks:**
- [ ] Create treatment tracking table
- [ ] Implement effectiveness calculation logic
- [ ] Add AI-powered treatment assessment
- [ ] Create treatment history visualization endpoint
- [ ] Add alerts for ineffective treatments

---

### 4.4 Automated Follow-Up Scheduling
**Problem:** AI recommendations for follow-up aren't automatically scheduled.

**Implementation:**
```python
async def process_followup_recommendations(
    analysis_result: Dict,
    patient_id: int,
    visit_id: int,
    doctor_firebase_uid: str
) -> List[Dict]:
    """Create follow-up tasks from AI recommendations"""
    
    followups = analysis_result.get("follow_up_recommendations", [])
    created_reminders = []
    
    for followup in followups:
        # Parse timeframe
        days = parse_timeframe_to_days(followup["timeframe"])
        follow_up_date = datetime.now() + timedelta(days=days)
        
        # Create calendar notification
        reminder = await db.create_calendar_notification({
            "doctor_firebase_uid": doctor_firebase_uid,
            "patient_id": patient_id,
            "visit_id": visit_id,
            "notification_type": "follow_up",
            "scheduled_date": follow_up_date.date().isoformat(),
            "title": f"Follow-up: {followup['test_name']}",
            "message": followup["reason"],
            "auto_generated": True,
            "source": "ai_analysis"
        })
        
        created_reminders.append(reminder)
    
    return created_reminders
```

**Tasks:**
- [ ] Create follow-up recommendation parser
- [ ] Integrate with calendar/notification system
- [ ] Add patient notification option
- [ ] Create follow-up dashboard view

---

## Database Migrations

### Migration Order:
1. `001_add_clinical_alerts.sql` - Critical alerts table
2. `002_simplify_document_analysis.sql` - Add structured_data column
3. `003_add_patient_risk_scores.sql` - Risk scoring table
4. `004_add_treatment_tracking.sql` - Treatment effectiveness
5. `005_add_visit_summaries.sql` - Generated summaries
6. `006_add_query_history.sql` - NLP query tracking
7. `007_cleanup_redundant_columns.sql` - Remove old text columns

### Migration Commands:
```bash
# Create migrations folder structure
mkdir -p migrations/ai_improvements

# Run migrations (example with your setup)
# Apply each migration in order via Supabase dashboard or CLI
```

---

## API Changes Summary

### New Endpoints:
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/alerts` | Get unacknowledged alerts |
| GET | `/alerts/count` | Get alert counts by severity |
| POST | `/alerts/{id}/acknowledge` | Acknowledge alert |
| GET | `/patients/{id}/alerts` | Get patient alerts |
| POST | `/visits/{id}/generate-summary` | Generate SOAP note |
| GET | `/patients/{id}/risk-score` | Get risk score |
| POST | `/patients/{id}/calculate-risk-score` | Calculate risk score |
| POST | `/patients/{id}/analyze-comprehensive-history-stream` | Streaming analysis |
| POST | `/batch/analyze-reports` | Batch analysis |
| POST | `/ai/query` | Natural language query |
| POST | `/visits/{id}/differential-diagnosis` | Differential diagnosis |
| GET | `/patients/{id}/treatment-effectiveness` | Treatment tracking |
| GET | `/ai/metrics` | Processing metrics |

### Modified Endpoints:
| Endpoint | Changes |
|----------|---------|
| `/reports/{id}/analyze` | Add medication warnings, use JSON output |
| `/visits/{id}/analyses` | Include alerts, use caching |
| `/patients/{id}/analyses` | Include risk score |

---

## Testing Strategy

### Unit Tests:
```python
# tests/test_ai_analysis.py

class TestStructuredOutput:
    async def test_json_schema_validation(self):
        """Verify AI returns valid JSON matching schema"""
        
    async def test_fallback_on_invalid_json(self):
        """Verify graceful handling of malformed responses"""

class TestAlertGeneration:
    async def test_critical_value_detection(self):
        """Verify critical values trigger alerts"""
        
    async def test_allergy_warning(self):
        """Verify allergy conflicts are detected"""

class TestMedicationInteractions:
    async def test_known_interaction_detected(self):
        """Verify known drug interactions are flagged"""
        
    async def test_no_false_positives(self):
        """Verify safe combinations don't trigger warnings"""
```

### Integration Tests:
```python
class TestEndToEndAnalysis:
    async def test_complete_analysis_flow(self):
        """Test upload → queue → analyze → alert → retrieve"""
        
    async def test_batch_processing(self):
        """Test batch analysis with multiple reports"""
```

### Load Tests:
```python
# Using locust or similar
class AIAnalysisLoadTest:
    def test_concurrent_analyses(self):
        """Verify system handles 50 concurrent analyses"""
        
    def test_queue_under_load(self):
        """Verify queue processes efficiently under load"""
```

---

## Success Metrics

### Phase 1 Success Criteria:
- [ ] JSON output parsing success rate > 99%
- [ ] Critical alerts generated within 5 minutes of analysis
- [ ] Cache hit rate > 70% for repeated queries
- [ ] No redundant data in new analyses

### Phase 2 Success Criteria:
- [ ] Medication interactions detected with > 95% accuracy
- [ ] Trend analysis included in > 90% of lab report analyses
- [ ] Visit summaries generated in < 10 seconds
- [ ] Risk scores calculated for all patients with > 3 visits

### Phase 3 Success Criteria:
- [ ] Average processing time reduced by 30%
- [ ] Prompt token usage reduced by 50%
- [ ] Streaming responses for analyses > 15 seconds
- [ ] Batch processing handles 20 reports in < 2 minutes

### Phase 4 Success Criteria:
- [ ] Natural language queries answer > 80% of common questions
- [ ] Differential diagnosis accuracy > 85% for top-3 suggestions
- [ ] Treatment effectiveness tracked for chronic conditions
- [ ] Follow-up compliance improved by 20%

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| JSON output mode fails | Fallback to text parsing + logging |
| Rate limits increase | Implement exponential backoff + queue priority |
| Large prompts cause timeouts | Context compression + chunking |
| Migration breaks existing data | Backward-compatible changes + rollback scripts |
| AI hallucinations in alerts | Require confidence threshold for critical alerts |

---

## Timeline Summary

| Week | Phase | Key Deliverables |
|------|-------|------------------|
| 1 | Foundation | JSON output, alert table, caching |
| 2 | Foundation | Alert service integration, table simplification |
| 3 | Clinical | Medication interactions, trend analysis |
| 4 | Clinical | Visit summaries, risk scoring |
| 5 | Performance | Queue optimization, streaming |
| 6 | Performance | Prompt optimization, batch processing |
| 7 | Advanced | NLP queries, differential diagnosis |
| 8 | Advanced | Treatment tracking, auto-scheduling |

---

## Next Steps

1. **Review this plan** and prioritize features
2. **Set up development branch** for AI improvements
3. **Create database migrations** (Phase 1)
4. **Implement JSON schema output** (highest impact)
5. **Add clinical alerts** (highest patient safety impact)

Ready to begin implementation? Start with Phase 1, Task 1.1 (Structured JSON Output).
