from google import genai
from google.genai import types
import os
import asyncio
import traceback
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import magic
import PyPDF2
from PIL import Image
import io
import base64
import requests
from pathlib import Path
import tempfile
import concurrent.futures
import json
import logging

# Import JSON schemas for structured output
from ai_schemas import (
    DOCUMENT_ANALYSIS_SCHEMA,
    HANDWRITTEN_ANALYSIS_SCHEMA,
    COMPREHENSIVE_HISTORY_SCHEMA,
    CONSOLIDATED_ANALYSIS_SCHEMA
)

logger = logging.getLogger(__name__)

class AIAnalysisService:
    def __init__(self):
        """Initialize the AI Analysis Service with Gemini 3 Pro via Vertex AI"""
        # Load configuration from environment variables (no hardcoded values)
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
        
        if not self.project_id:
            raise ValueError("GOOGLE_CLOUD_PROJECT environment variable is required")
        
        # Set environment variables for Gen AI SDK to use Vertex AI
        os.environ["GOOGLE_CLOUD_PROJECT"] = self.project_id
        os.environ["GOOGLE_CLOUD_LOCATION"] = self.location
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
        
        # Set up Google Cloud credentials from environment variable
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not credentials_path:
            raise ValueError("GOOGLE_APPLICATION_CREDENTIALS environment variable is required")
        
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"GCP credentials file not found: {credentials_path}")
        
        print(f"Using GCP credentials from: {credentials_path}")
        
        # Initialize the Gen AI client for Vertex AI
        self.client = genai.Client()
        
        # Model name for Gemini 3 Pro Preview
        self.model_name = "gemini-3-pro-preview"
        
        # Create thread pool for sync operations
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        
        print(f"AI Analysis Service initialized with Gemini 3 Pro via Vertex AI")
        print(f"Project: {self.project_id}, Location: {self.location}")
    
    async def analyze_document(
        self, 
        file_content: bytes, 
        file_name: str, 
        file_type: str,
        patient_context: Dict[str, Any],
        visit_context: Dict[str, Any],
        doctor_context: Dict[str, Any],
        visit_chain_context: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Analyze a medical document using Gemini 3 Pro with patient, visit, and linked visit chain context
        
        Args:
            file_content: The binary content of the file
            file_name: Name of the file
            file_type: MIME type of the file
            patient_context: Patient information (name, age, medical history, etc.)
            visit_context: Visit information (complaints, symptoms, recommended tests, etc.)
            doctor_context: Doctor information (name, specialization, etc.)
        
        Returns:
            Dict containing analysis results
        """
        try:
            print(f"Starting AI analysis for file: {file_name}")
            
            # Prepare the document for analysis
            document_data = await self._prepare_document(file_content, file_name, file_type)
            if not document_data:
                return {
                    "success": False,
                    "error": "Unable to process document format",
                    "analysis": None
                }
            
            # Create context-aware prompt with linked visit history
            prompt = self._create_analysis_prompt(
                patient_context, 
                visit_context, 
                doctor_context, 
                file_name,
                visit_chain_context
            )
            
            # Perform AI analysis
            analysis_result = await self._perform_gemini_analysis(prompt, document_data)
            
            # Check if analysis failed (e.g. rate limit)
            if "error" in analysis_result:
                return {
                    "success": False,
                    "error": analysis_result["error"],
                    "analysis": None
                }
            
            return {
                "success": True,
                "analysis": analysis_result,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "model_used": self.model_name
            }
            
        except Exception as e:
            print(f"Error in AI document analysis: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
                "analysis": None
            }
    
    async def _prepare_document(
        self, 
        file_content: bytes, 
        file_name: str, 
        file_type: str
    ) -> Optional[Dict[str, Any]]:
        """Prepare document content for AI analysis"""
        try:
            # Handle different file types
            if file_type.startswith('image/'):
                return await self._prepare_image(file_content, file_type)
            elif file_type == 'application/pdf':
                return await self._prepare_pdf(file_content)
            elif file_type.startswith('text/'):
                return await self._prepare_text(file_content)
            else:
                # Try to detect file type if not recognized
                detected_type = magic.from_buffer(file_content, mime=True)
                if detected_type.startswith('image/'):
                    return await self._prepare_image(file_content, detected_type)
                elif detected_type == 'application/pdf':
                    return await self._prepare_pdf(file_content)
                else:
                    print(f"Unsupported file type: {file_type} (detected: {detected_type})")
                    return None
                    
        except Exception as e:
            print(f"Error preparing document: {e}")
            return None
    
    async def _prepare_image(self, file_content: bytes, file_type: str) -> Dict[str, Any]:
        """Prepare image for AI analysis"""
        try:
            # Convert to PIL Image
            image = Image.open(io.BytesIO(file_content))
            
            # Convert to RGB if necessary
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Resize if too large (Gemini has size limits)
            max_size = (1024, 1024)
            if image.size[0] > max_size[0] or image.size[1] > max_size[1]:
                image.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Convert back to bytes
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=85)
            processed_content = output.getvalue()
            
            return {
                "type": "image",
                "content": processed_content,
                "mime_type": "image/jpeg"
            }
            
        except Exception as e:
            print(f"Error preparing image: {e}")
            return None
    
    async def _prepare_pdf(self, file_content: bytes) -> Dict[str, Any]:
        """Prepare PDF for AI analysis"""
        try:
            # Extract text from PDF
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
            text_content = ""
            
            for page in pdf_reader.pages:
                text_content += page.extract_text() + "\n"
            
            # If text extraction is successful, use text
            if text_content.strip():
                return {
                    "type": "text",
                    "content": text_content.strip()
                }
            else:
                # If no text, try to convert first page to image
                # Note: This would require additional libraries like pdf2image
                # For now, return the raw content and let Gemini handle it
                return {
                    "type": "pdf",
                    "content": file_content[:1024000],  # Limit size
                    "mime_type": "application/pdf"
                }
                
        except Exception as e:
            print(f"Error preparing PDF: {e}")
            return None
    
    async def _prepare_text(self, file_content: bytes) -> Dict[str, Any]:
        """Prepare text file for AI analysis"""
        try:
            text_content = file_content.decode('utf-8')
            return {
                "type": "text",
                "content": text_content
            }
        except UnicodeDecodeError:
            try:
                text_content = file_content.decode('latin-1')
                return {
                    "type": "text",
                    "content": text_content
                }
            except Exception as e:
                print(f"Error decoding text: {e}")
                return None
    
    def _create_analysis_prompt(
        self, 
        patient_context: Dict[str, Any], 
        visit_context: Dict[str, Any], 
        doctor_context: Dict[str, Any], 
        file_name: str,
        visit_chain_context: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Create a comprehensive analysis prompt with context including linked visit history"""
        
        # Extract patient information
        patient_name = f"{patient_context.get('first_name', '')} {patient_context.get('last_name', '')}"
        patient_age = self._calculate_age(patient_context.get('date_of_birth', ''))
        patient_gender = patient_context.get('gender', 'Not specified')
        medical_history = patient_context.get('medical_history', 'None provided')
        allergies = patient_context.get('allergies', 'None known')
        blood_group = patient_context.get('blood_group', 'Not specified')
        
        # Extract prior medical history (from previous doctor consultations)
        prior_history_section = ""
        if patient_context.get('consulted_other_doctor'):
            prior_history_parts = []
            prior_history_parts.append("**Patient has previously consulted another doctor for this condition.**")
            
            if patient_context.get('previous_doctor_name'):
                doc_info = patient_context.get('previous_doctor_name')
                if patient_context.get('previous_doctor_specialization'):
                    doc_info += f" ({patient_context.get('previous_doctor_specialization')})"
                prior_history_parts.append(f"- Previous Doctor: {doc_info}")
            
            if patient_context.get('previous_clinic_hospital'):
                prior_history_parts.append(f"- Previous Clinic/Hospital: {patient_context.get('previous_clinic_hospital')}")
            
            if patient_context.get('previous_consultation_date'):
                prior_history_parts.append(f"- Previous Consultation Date: {patient_context.get('previous_consultation_date')}")
            
            if patient_context.get('previous_symptoms'):
                prior_history_parts.append(f"- Previous Symptoms: {patient_context.get('previous_symptoms')}")
            
            if patient_context.get('previous_diagnosis'):
                prior_history_parts.append(f"- Previous Diagnosis: {patient_context.get('previous_diagnosis')}")
            
            if patient_context.get('previous_medications'):
                meds = patient_context.get('previous_medications')
                if isinstance(meds, list):
                    meds = ', '.join(meds)
                prior_history_parts.append(f"- Previous Medications: {meds}")
                if patient_context.get('previous_medications_duration'):
                    prior_history_parts.append(f"- Medication Duration: {patient_context.get('previous_medications_duration')}")
            
            if patient_context.get('medication_response'):
                prior_history_parts.append(f"- Response to Previous Treatment: {patient_context.get('medication_response')}")
            
            if patient_context.get('previous_tests_done'):
                prior_history_parts.append(f"- Previous Tests Done: {patient_context.get('previous_tests_done')}")
                if patient_context.get('previous_test_results'):
                    prior_history_parts.append(f"- Previous Test Results: {patient_context.get('previous_test_results')}")
            
            if patient_context.get('reason_for_new_consultation'):
                prior_history_parts.append(f"- Reason for Seeking New Consultation: {patient_context.get('reason_for_new_consultation')}")
            
            prior_history_section = "\n".join(prior_history_parts)
        
        # Check for ongoing treatment
        ongoing_treatment_section = ""
        if patient_context.get('ongoing_treatment'):
            ongoing_treatment_section = "\n**⚠️ PATIENT IS CURRENTLY ON ONGOING TREATMENT**"
            if patient_context.get('current_medications'):
                meds = patient_context.get('current_medications')
                if isinstance(meds, list):
                    meds = ', '.join(meds)
                ongoing_treatment_section += f"\n- Current Medications: {meds}"
        
        # Extract visit information with more detail
        visit_date = visit_context.get('visit_date', 'Not specified')
        visit_type = visit_context.get('visit_type', 'General consultation')
        chief_complaint = visit_context.get('chief_complaint', 'Not specified')
        symptoms = visit_context.get('symptoms', 'None specified')
        tests_recommended = visit_context.get('tests_recommended', 'General tests')
        diagnosis = visit_context.get('diagnosis', 'Pending')
        clinical_examination = visit_context.get('clinical_examination', 'Not documented')
        treatment_plan = visit_context.get('treatment_plan', 'Not specified')
        medications = visit_context.get('medications', 'None prescribed')
        
        # Extract vitals if available
        vitals_text = "Not recorded"
        if visit_context.get('vitals'):
            vitals = visit_context.get('vitals', {})
            vitals_parts = []
            # Blood pressure (handle both formats)
            if vitals.get('blood_pressure'):
                vitals_parts.append(f"BP: {vitals['blood_pressure']}")
            elif vitals.get('blood_pressure_systolic') and vitals.get('blood_pressure_diastolic'):
                vitals_parts.append(f"BP: {vitals['blood_pressure_systolic']}/{vitals['blood_pressure_diastolic']} mmHg")
            # Heart rate
            if vitals.get('heart_rate'):
                vitals_parts.append(f"Heart Rate: {vitals['heart_rate']} bpm")
            # Pulse rate (handle both field names)
            if vitals.get('pulse_rate'):
                vitals_parts.append(f"Pulse Rate: {vitals['pulse_rate']} bpm")
            elif vitals.get('pulse'):
                vitals_parts.append(f"Pulse: {vitals['pulse']} bpm")
            # Temperature
            if vitals.get('temperature'):
                vitals_parts.append(f"Temp: {vitals['temperature']}°C")
            # Respiratory rate
            if vitals.get('respiratory_rate'):
                vitals_parts.append(f"Resp Rate: {vitals['respiratory_rate']}/min")
            # Weight
            if vitals.get('weight'):
                vitals_parts.append(f"Weight: {vitals['weight']} kg")
            # Height
            if vitals.get('height'):
                vitals_parts.append(f"Height: {vitals['height']} cm")
            # BMI
            if vitals.get('bmi'):
                vitals_parts.append(f"BMI: {vitals['bmi']}")
            # Oxygen saturation (handle both field names)
            if vitals.get('oxygen_saturation'):
                vitals_parts.append(f"SpO2: {vitals['oxygen_saturation']}%")
            elif vitals.get('spo2'):
                vitals_parts.append(f"SpO2: {vitals['spo2']}%")
            if vitals_parts:
                vitals_text = ", ".join(vitals_parts)
        
        # Extract doctor information
        doctor_name = f"Dr. {doctor_context.get('first_name', '')} {doctor_context.get('last_name', '')}"
        specialization = doctor_context.get('specialization', 'General Medicine')
        
        # Build visit chain context section if available
        visit_chain_section = ""
        if visit_chain_context and len(visit_chain_context) > 0:
            visit_chain_section = """
**🔗 LINKED VISIT HISTORY (CRITICAL - THIS IS A FOLLOW-UP VISIT):**
This visit is linked to previous visits. The patient has been seen before for related concerns.
IMPORTANT: Use this history to provide continuity of care analysis.

"""
            for i, prev_visit in enumerate(visit_chain_context, 1):
                prev_date = prev_visit.get('visit_date', 'Unknown date')
                prev_complaint = prev_visit.get('chief_complaint', 'Not recorded')
                prev_diagnosis = prev_visit.get('diagnosis', 'Not recorded')
                prev_treatment = prev_visit.get('treatment_plan', 'Not recorded')
                prev_medications = prev_visit.get('medications', 'None')
                prev_tests = prev_visit.get('tests_recommended', 'None')
                # Use visit_type as context indicator (case-based architecture)
                visit_context_label = prev_visit.get('visit_type', 'Follow-up')
                
                # Include AI analysis summary if available
                ai_summary = ""
                if prev_visit.get('ai_analyses_summary'):
                    ai_findings = prev_visit.get('ai_analyses_summary', [])
                    if ai_findings:
                        ai_summary = "\\n    - Previous AI Findings: " + "; ".join([
                            f"{a.get('document_summary', '')[:100]}" for a in ai_findings[:2]
                        ])
                
                # Include reports info if available
                reports_info = ""
                if prev_visit.get('reports'):
                    reports = prev_visit.get('reports', [])
                    if reports:
                        reports_info = f"\\n    - Reports Uploaded: {', '.join([r.get('file_name', 'Unknown') for r in reports[:3]])}"
                
                visit_chain_section += f"""
  **Previous Visit #{i} ({visit_context_label}):**
    - Date: {prev_date}
    - Chief Complaint: {prev_complaint}
    - Diagnosis: {prev_diagnosis}
    - Treatment Given: {prev_treatment}
    - Medications: {prev_medications}
    - Tests Ordered: {prev_tests}{ai_summary}{reports_info}
"""
            
            visit_chain_section += """
⚠️ **CONTINUITY OF CARE INSTRUCTIONS:**
- Compare current findings with previous visit data
- Note any progression or regression of condition
- Evaluate if previous treatment was effective
- Consider if diagnosis needs to be updated based on new findings
- Check if previously ordered tests are now being reviewed

"""
        
        prompt = f"""
You are an advanced AI medical assistant helping {doctor_name} ({specialization}) analyze a medical document within the context of a specific patient visit. This analysis should be DIRECTLY RELEVANT to the doctor's clinical observations and treatment decisions.

**PATIENT INFORMATION:**
- Name: {patient_name}
- Age: {patient_age}
- Gender: {patient_gender}
- Blood Group: {blood_group}
- Known Allergies: {allergies}
- Medical History: {medical_history}
{ongoing_treatment_section}

{prior_history_section}
{visit_chain_section}
**CURRENT VISIT CONTEXT (CRITICAL FOR ANALYSIS):**
- Visit Date: {visit_date}
- Visit Type: {visit_type}
- **Chief Complaint:** {chief_complaint}
- **Presenting Symptoms:** {symptoms}
- **Vitals Recorded:** {vitals_text}
- **Clinical Examination Findings:** {clinical_examination}
- **Doctor's Working Diagnosis:** {diagnosis}
- **Tests Recommended by Doctor:** {tests_recommended}
- **Treatment Plan:** {treatment_plan}
- **Medications Prescribed:** {medications}

**DOCUMENT TO ANALYZE:**
- File Name: {file_name}

**ANALYSIS INSTRUCTIONS:**

Your analysis MUST be contextual and personalized. This is not a standalone report analysis - it's an analysis to help the doctor validate their clinical decisions and adjust treatment if needed.
{self._get_prior_treatment_instruction(prior_history_section)}
Please provide analysis in this ENHANCED format:

**1. DOCUMENT IDENTIFICATION & SUMMARY:**
- Type of medical document (CBC, LFT, X-Ray, CT scan, etc.)
- Date of test/report (if available)
- Key parameters measured and their values
- Overall quality of the document

**2. CLINICAL CORRELATION WITH VISIT:**
⚠️ **MOST IMPORTANT SECTION** - This should be the most detailed part.
- **Direct Relevance to Chief Complaint:** How do the report findings specifically relate to "{chief_complaint}"?
- **Validation of Clinical Examination:** Do the report findings support or contradict Dr. {doctor_name}'s examination findings of: "{clinical_examination}"?
- **Support for Working Diagnosis:** How do these results confirm, refute, or modify the diagnosis of "{diagnosis}"?
- **Explanation of Symptoms:** Which findings in this report could explain the patient's symptoms: "{symptoms}"?
- **Appropriateness of Test:** Was this the right test to order given the presentation? Are the results what you'd expect?

**3. DETAILED FINDINGS ANALYSIS:**
For each significant parameter/finding:
- **Value found** vs **Normal reference range**
- **Clinical significance** in general medical context
- **Specific relevance** to this patient's age ({patient_age}), gender ({patient_gender}), and medical history
- **Severity assessment** (normal, borderline, mildly abnormal, significantly abnormal, critical)
- **Trends** if previous values are mentioned in medical history

**4. CRITICAL & URGENT FINDINGS:**
🚨 Flag any values that require:
- Immediate medical attention
- Urgent follow-up within 24-48 hours
- Careful monitoring
- Medication adjustments

**5. TREATMENT PLAN EVALUATION:**
Given the current treatment plan: "{treatment_plan}" and medications: "{medications}"
- Are the test results consistent with continuing this treatment?
- Do findings suggest need for treatment modification?
- Are there any contraindications revealed by this report?
- Should any medications be adjusted based on these findings?

**6. CONTINUITY OF CARE ANALYSIS (IF FOLLOW-UP VISIT):**
⚠️ If this is a follow-up visit with linked visit history:
- **Treatment Response:** How do current findings compare to previous visit? Is the patient improving?
- **Diagnosis Validation:** Do current results confirm or change the previous diagnosis?
- **Medication Effectiveness:** Are the previously prescribed medications working?
- **Test Correlation:** If this test was ordered in a previous visit, what do results indicate?
- **Disease Progression:** Any signs of progression or regression of the condition?
- **Previous vs Current:** Direct comparison of any overlapping parameters from past reports

**7. ACTIONABLE NEXT STEPS:**
Based on BOTH the report findings AND the visit context (including previous visits):
- Immediate actions for Dr. {doctor_name} to consider
- Follow-up tests recommended (with justification)
- Specialist referrals if indicated
- Patient lifestyle modifications
- Monitoring schedule recommendations
- Treatment modifications based on previous visit outcomes

**8. PATIENT COMMUNICATION GUIDANCE:**
- How should Dr. {doctor_name} explain these results to {patient_name}?
- Key points to emphasize during patient consultation
- Reassurance points if results are normal/mild
- Concerns to discuss if results are abnormal
- Simple, non-technical explanation of findings
- Progress explanation if this is a follow-up

**9. CLINICAL DOCUMENTATION NOTES:**
- Important observations to add to medical records
- Trends to monitor in future visits
- Red flags for future reference
- Quality/limitations of this test

**CRITICAL ANALYSIS PRINCIPLES:**
✓ Always connect findings back to the chief complaint and symptoms
✓ Consider the doctor's working diagnosis in your interpretation
✓ Think about "why did the doctor order this test?" and answer that question
✓ Be specific about clinical implications, not just lab values
✓ Prioritize findings that impact immediate patient management
✓ Consider the complete clinical picture, not isolated lab values
✓ Flag discrepancies between clinical findings and lab results
✓ Provide decision support, not just data interpretation
✓ **If follow-up visit: ALWAYS compare with previous visit findings and treatments**
✓ **Track treatment effectiveness across linked visits**

This analysis should help Dr. {doctor_name} provide better care for {patient_name} by connecting the diagnostic data with the clinical presentation and treatment plan.
"""
        
        return prompt
    
    def _calculate_age(self, date_of_birth: str) -> str:
        """Calculate age from date of birth"""
        try:
            if not date_of_birth:
                return "Not specified"
            
            from datetime import date
            birth_date = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
            today = date.today()
            age = today.year - birth_date.year
            
            # Adjust if birthday hasn't occurred this year
            if today < birth_date.replace(year=today.year):
                age -= 1
                
            return f"{age} years"
        except:
            return "Unable to calculate"
    
    def _format_prior_medical_history_for_prompt(self, patient_context: Dict[str, Any]) -> str:
        """Format prior medical history (from previous doctor consultations) for AI prompts"""
        if not patient_context.get('consulted_other_doctor'):
            return ""
        
        lines = [
            "",
            "═══════════════════════════════════════════════════════════════",
            "**🩺 PRIOR MEDICAL HISTORY (FROM PREVIOUS DOCTOR CONSULTATION)**",
            "═══════════════════════════════════════════════════════════════",
            "┌─────────────────────────────────────────────────────────────────",
            "│ ⚠️ IMPORTANT: Patient has previously consulted another doctor",
        ]
        
        if patient_context.get('previous_doctor_name'):
            doc_info = f"│ 👨‍⚕️ Previous Doctor: {patient_context.get('previous_doctor_name')}"
            if patient_context.get('previous_doctor_specialization'):
                doc_info += f" ({patient_context.get('previous_doctor_specialization')})"
            lines.append(doc_info)
        
        if patient_context.get('previous_clinic_hospital'):
            lines.append(f"│ 🏥 Previous Clinic/Hospital: {patient_context.get('previous_clinic_hospital')}")
        
        if patient_context.get('previous_consultation_date'):
            lines.append(f"│ 📅 Previous Consultation Date: {patient_context.get('previous_consultation_date')}")
        
        if patient_context.get('previous_symptoms'):
            lines.append(f"│ 🤒 Previous Symptoms: {patient_context.get('previous_symptoms')}")
        
        if patient_context.get('previous_diagnosis'):
            lines.append(f"│ 📋 Previous Diagnosis: {patient_context.get('previous_diagnosis')}")
        
        if patient_context.get('previous_medications'):
            meds = patient_context.get('previous_medications')
            if isinstance(meds, list):
                meds = ', '.join(meds)
            lines.append(f"│ 💊 Previous Medications: {meds}")
            if patient_context.get('previous_medications_duration'):
                lines.append(f"│ ⏱️ Medication Duration: {patient_context.get('previous_medications_duration')}")
        
        if patient_context.get('medication_response'):
            response = patient_context.get('medication_response')
            emoji = "✅" if response == "improved" else "⚠️" if response == "partial improvement" else "❌" if response in ["no change", "worsened"] else "❓"
            lines.append(f"│ {emoji} Response to Previous Treatment: {response.title()}")
        
        if patient_context.get('previous_tests_done'):
            lines.append(f"│ 🧪 Previous Tests Done: {patient_context.get('previous_tests_done')}")
            if patient_context.get('previous_test_results'):
                lines.append(f"│ 📊 Previous Test Results: {patient_context.get('previous_test_results')}")
        
        if patient_context.get('reason_for_new_consultation'):
            lines.append(f"│ ❓ Reason for Seeking New Consultation: {patient_context.get('reason_for_new_consultation')}")
        
        if patient_context.get('ongoing_treatment'):
            lines.append("│ 🔄 Patient is currently on ONGOING TREATMENT")
            if patient_context.get('current_medications'):
                curr_meds = patient_context.get('current_medications')
                if isinstance(curr_meds, list):
                    curr_meds = ', '.join(curr_meds)
                lines.append(f"│ 💊 Current Medications: {curr_meds}")
        
        lines.append("└─────────────────────────────────────────────────────────────────")
        lines.append("")
        
        return "\n".join(lines)
    
    def _get_prior_treatment_instruction(self, prior_history_section: str) -> str:
        """Return instruction text if patient has prior treatment history"""
        if prior_history_section:
            return """
**⚠️ IMPORTANT - PRIOR TREATMENT CONTEXT:** This patient has previously been treated by another doctor. Consider the prior diagnosis, previous medications, and treatment response when analyzing this document. Evaluate if the current findings suggest the previous treatment was effective, partially effective, or if a different approach may be needed.
"""
        return ""

    async def _perform_gemini_analysis(
        self, 
        prompt: str, 
        document_data: Dict[str, Any],
        max_retries: int = 3,
        use_json_mode: bool = True
    ) -> Dict[str, Any]:
        """
        Perform the actual AI analysis using Gemini 3 Pro with retry logic for rate limits.
        
        Now uses JSON structured output mode for reliable parsing.
        Falls back to text mode only if JSON parsing fails.
        """
        
        for attempt in range(max_retries):
            try:
                loop = asyncio.get_event_loop()
                
                # Prepare content for Gemini 3 Pro using Gen AI SDK
                content_parts = []
                
                if document_data["type"] == "text":
                    content_parts = [prompt, document_data["content"]]
                elif document_data["type"] == "image":
                    # Create image part using types.Part for Gemini 3
                    image_part = types.Part.from_bytes(
                        data=document_data["content"],
                        mime_type=document_data["mime_type"]
                    )
                    content_parts = [prompt, image_part]
                else:
                    # For PDF or other types, include as text if possible
                    content_parts = [prompt, f"Document content: {document_data.get('content', 'Unable to extract content')}"]
                
                # Generate response using Gemini 3 Pro via Vertex AI
                # Using LOW thinking level for faster responses in document analysis
                # Now with JSON structured output for reliable parsing
                def generate_sync():
                    if use_json_mode:
                        # Use JSON mode with structured schema
                        return self.client.models.generate_content(
                            model=self.model_name,
                            contents=content_parts,
                            config=types.GenerateContentConfig(
                                thinking_config=types.ThinkingConfig(
                                    thinking_level=types.ThinkingLevel.LOW
                                ),
                                response_mime_type="application/json",
                                response_schema=DOCUMENT_ANALYSIS_SCHEMA
                            )
                        )
                    else:
                        # Fallback to text mode
                        return self.client.models.generate_content(
                            model=self.model_name,
                            contents=content_parts,
                            config=types.GenerateContentConfig(
                                thinking_config=types.ThinkingConfig(
                                    thinking_level=types.ThinkingLevel.LOW
                                )
                            )
                        )
                
                response = await loop.run_in_executor(
                    self.executor,
                    generate_sync
                )
                
                if response and response.text:
                    analysis_text = response.text
                    
                    if use_json_mode:
                        # Parse JSON response directly
                        try:
                            structured_analysis = json.loads(analysis_text)
                            
                            # Calculate confidence from structured data
                            confidence_score = self._calculate_confidence_from_structured(structured_analysis)
                            
                            # Extract key findings from structured data
                            key_findings = self._extract_key_findings_from_structured(structured_analysis)
                            
                            return {
                                "raw_analysis": analysis_text,
                                "structured_analysis": structured_analysis,
                                "confidence_score": confidence_score,
                                "analysis_length": len(analysis_text),
                                "key_findings": key_findings,
                                "structured_data": structured_analysis,  # New field for direct storage
                                "parsing_method": "json_mode"
                            }
                        except json.JSONDecodeError as je:
                            logger.warning(f"JSON parsing failed, falling back to text parsing: {je}")
                            # Fall back to text parsing
                            parsed_analysis = self._parse_analysis_response(analysis_text)
                            return {
                                "raw_analysis": analysis_text,
                                "structured_analysis": parsed_analysis,
                                "confidence_score": self._calculate_confidence(analysis_text),
                                "analysis_length": len(analysis_text),
                                "key_findings": self._extract_key_findings(parsed_analysis),
                                "parsing_method": "text_fallback"
                            }
                    else:
                        # Legacy text parsing mode
                        parsed_analysis = self._parse_analysis_response(analysis_text)
                        return {
                            "raw_analysis": analysis_text,
                            "structured_analysis": parsed_analysis,
                            "confidence_score": self._calculate_confidence(analysis_text),
                            "analysis_length": len(analysis_text),
                            "key_findings": self._extract_key_findings(parsed_analysis),
                            "parsing_method": "text_mode"
                        }
                else:
                    return {
                        "error": "No response from AI model",
                        "raw_analysis": "",
                        "structured_analysis": {},
                        "confidence_score": 0.0,
                        "key_findings": []
                    }
                    
            except Exception as e:
                error_message = str(e)
                
                # Check if it's a rate limit error (429)
                if "429" in error_message or "Resource exhausted" in error_message or "RESOURCE_EXHAUSTED" in error_message:
                    if attempt < max_retries - 1:
                        # Exponential backoff: 2, 4, 8 seconds
                        wait_time = 2 ** (attempt + 1)
                        logger.warning(f"Rate limit hit. Retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Rate limit exceeded after {max_retries} attempts")
                        return {
                            "error": "Rate limit exceeded. Please try again later.",
                            "raw_analysis": "",
                            "structured_analysis": {},
                            "confidence_score": 0.0,
                            "key_findings": []
                        }
                else:
                    # Other errors - don't retry
                    logger.error(f"Error in Gemini 3 Pro analysis: {e}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    return {
                        "error": error_message,
                        "raw_analysis": "",
                        "structured_analysis": {},
                        "confidence_score": 0.0,
                        "key_findings": []
                    }
        
        # Should never reach here, but just in case
        return {
            "error": "Analysis failed after retries",
            "raw_analysis": "",
            "structured_analysis": {},
            "confidence_score": 0.0,
            "key_findings": []
        }
    
    def _calculate_confidence_from_structured(self, structured_data: Dict[str, Any]) -> float:
        """Calculate confidence score from structured JSON response"""
        try:
            base_score = 0.75
            
            # Check for presence of key fields
            if structured_data.get("findings") and len(structured_data["findings"]) > 0:
                base_score += 0.05
            
            if structured_data.get("critical_findings") is not None:
                base_score += 0.03
            
            if structured_data.get("clinical_correlation"):
                base_score += 0.05
            
            if structured_data.get("treatment_evaluation"):
                base_score += 0.03
            
            if structured_data.get("actionable_insights") and len(structured_data["actionable_insights"]) > 0:
                base_score += 0.04
            
            # Deduct for critical findings (indicates serious condition, lower confidence in good outcome)
            critical_count = len(structured_data.get("critical_findings", []))
            if critical_count > 0:
                # More critical findings = slightly lower confidence due to complexity
                base_score -= min(0.05, critical_count * 0.01)
            
            return min(0.95, max(0.5, base_score))
            
        except Exception as e:
            logger.warning(f"Error calculating confidence from structured data: {e}")
            return 0.7
    
    def _extract_key_findings_from_structured(self, structured_data: Dict[str, Any]) -> List[str]:
        """Extract key findings from structured JSON response"""
        try:
            key_findings = []
            
            # Add critical findings first
            for critical in structured_data.get("critical_findings", [])[:3]:
                finding = critical.get("finding", "")
                if finding:
                    key_findings.append(f"⚠️ {finding}")
            
            # Add treatment evaluation summary
            treatment = structured_data.get("treatment_evaluation", {})
            if treatment:
                if not treatment.get("current_treatment_appropriate"):
                    key_findings.append("Treatment modification may be needed")
                elif treatment.get("treatment_response") in ["excellent", "good"]:
                    key_findings.append("Good response to current treatment")
            
            # Add high-priority actionable insights
            for insight in structured_data.get("actionable_insights", [])[:2]:
                if insight.get("priority") in ["immediate", "high"]:
                    key_findings.append(insight.get("action", ""))
            
            # Add clinical correlation summary
            correlation = structured_data.get("clinical_correlation", {})
            if correlation.get("supports_diagnosis"):
                key_findings.append("Results support working diagnosis")
            elif correlation.get("supports_diagnosis") is False:
                key_findings.append("Results may not support current diagnosis")
            
            # Default if no findings
            if not key_findings:
                key_findings.append("Analysis completed successfully")
            
            return key_findings[:5]
            
        except Exception as e:
            logger.warning(f"Error extracting key findings from structured data: {e}")
            return ["Analysis completed"]
    
    def _parse_analysis_response(self, analysis_text: str) -> Dict[str, Any]:
        """Parse the structured analysis response from Gemini.
        
        OPTIMIZED: 
        - Single .upper() call per line instead of 10+ calls
        - Pre-defined pattern matching with early exit
        - Uses list collection + join instead of string concatenation (O(N) vs O(N²))
        """
        try:
            # Use lists for O(N) collection instead of O(N²) string concatenation
            section_parts = {
                "document_summary": [],
                "clinical_correlation": [],
                "detailed_findings": [],
                "critical_findings": [],
                "treatment_evaluation": [],
                "clinical_significance": [],
                "correlation_with_patient": [],
                "actionable_insights": [],
                "patient_communication": [],
                "clinical_notes": []
            }
            
            # Pre-defined section patterns (checked in order, first match wins)
            # Format: (pattern_to_check, section_name, requires_secondary_check, secondary_pattern)
            SECTION_PATTERNS = [
                ("DOCUMENT IDENTIFICATION", "document_summary", False, None),
                ("DOCUMENT SUMMARY", "document_summary", False, None),
                ("CLINICAL CORRELATION WITH VISIT", "clinical_correlation", False, None),
                ("CORRELATION WITH VISIT", "clinical_correlation", False, None),
                ("DETAILED FINDINGS", "detailed_findings", False, None),
                ("CRITICAL", "critical_findings", True, "URGENT"),  # Requires both CRITICAL and URGENT
                ("TREATMENT PLAN EVALUATION", "treatment_evaluation", False, None),
                ("CLINICAL SIGNIFICANCE", "clinical_significance", False, None),
                ("CORRELATION WITH PATIENT", "correlation_with_patient", False, None),
                ("ACTIONABLE", "actionable_insights", False, None),
                ("NEXT STEPS", "actionable_insights", False, None),
                ("PATIENT COMMUNICATION", "patient_communication", False, None),
            ]
            
            current_section = None
            lines = analysis_text.split('\n')
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # OPTIMIZATION: Single .upper() call per line
                line_upper = line.upper()
                
                # Check for section headers with early exit
                matched_section = None
                for pattern, section, requires_secondary, secondary in SECTION_PATTERNS:
                    if pattern in line_upper:
                        if requires_secondary:
                            if secondary and secondary in line_upper:
                                matched_section = section
                                break
                        else:
                            matched_section = section
                            break
                
                # Special case for clinical notes (compound check)
                if not matched_section and "CLINICAL" in line_upper and ("NOTES" in line_upper or "DOCUMENTATION" in line_upper):
                    matched_section = "clinical_notes"
                
                if matched_section:
                    current_section = matched_section
                elif current_section and not line.startswith('**') and not line.startswith('⚠️') and not line.startswith('🚨'):
                    # Add content to current section (skip emoji markers)
                    clean_line = line.lstrip('✓-•*').strip()
                    if clean_line:
                        section_parts[current_section].append(clean_line)
            
            # OPTIMIZATION: Single join at the end instead of repeated concatenation
            sections = {key: " ".join(parts) for key, parts in section_parts.items()}
            
            return sections
            
        except Exception as e:
            print(f"Error parsing analysis response: {e}")
            return {
                "document_summary": analysis_text[:500] + "..." if len(analysis_text) > 500 else analysis_text,
                "clinical_correlation": "",
                "detailed_findings": "",
                "critical_findings": "",
                "treatment_evaluation": "",
                "clinical_significance": "",
                "correlation_with_patient": "",
                "actionable_insights": "",
                "patient_communication": "",
                "clinical_notes": ""
            }
    
    def _calculate_confidence(self, analysis_text: str) -> float:
        """Calculate a confidence score based on analysis quality"""
        try:
            # Simple heuristic based on length and content
            base_score = 0.7
            
            # Increase score based on length (more detailed = higher confidence)
            if len(analysis_text) > 1000:
                base_score += 0.1
            if len(analysis_text) > 2000:
                base_score += 0.1
            
            # Increase score if specific medical terms are present
            medical_indicators = [
                'normal', 'abnormal', 'reference range', 'significant',
                'recommend', 'follow-up', 'critical', 'within limits'
            ]
            
            found_indicators = sum(1 for indicator in medical_indicators 
                                 if indicator.lower() in analysis_text.lower())
            
            confidence_bonus = min(0.1, found_indicators * 0.02)
            
            return min(0.95, base_score + confidence_bonus)
            
        except:
            return 0.7
    
    def _extract_key_findings(self, structured_analysis: Dict[str, Any]) -> List[str]:
        """Extract key findings from the structured analysis"""
        try:
            key_findings = []
            
            # Extract from document summary
            summary = structured_analysis.get("document_summary", "")
            if "abnormal" in summary.lower() or "critical" in summary.lower():
                key_findings.append("Abnormal findings detected")
            
            # Extract from clinical significance
            significance = structured_analysis.get("clinical_significance", "")
            if "immediate attention" in significance.lower():
                key_findings.append("Requires immediate attention")
            
            # Extract from actionable insights
            insights = structured_analysis.get("actionable_insights", "")
            if "follow-up" in insights.lower():
                key_findings.append("Follow-up recommended")
            
            # If no specific findings, add a general one
            if not key_findings:
                key_findings.append("Analysis completed")
            
            return key_findings[:5]  # Limit to 5 key findings
            
        except:
            return ["Analysis completed"]
    
    async def analyze_multiple_documents(
        self,
        documents: List[Dict[str, Any]],
        patient_context: Dict[str, Any],
        visit_context: Dict[str, Any],
        doctor_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze multiple documents and provide a consolidated analysis"""
        try:
            individual_analyses = []
            
            # Analyze each document
            for doc in documents:
                analysis = await self.analyze_document(
                    doc["content"],
                    doc["file_name"],
                    doc["file_type"],
                    patient_context,
                    visit_context,
                    doctor_context
                )
                individual_analyses.append({
                    "file_name": doc["file_name"],
                    "analysis": analysis
                })
            
            # Create consolidated analysis
            consolidated_prompt = self._create_consolidated_prompt(
                individual_analyses, patient_context, visit_context, doctor_context
            )
            
            # Generate consolidated insights using Gemini 3 Pro with JSON mode
            loop = asyncio.get_event_loop()
            
            def generate_consolidated():
                return self.client.models.generate_content(
                    model=self.model_name,
                    contents=consolidated_prompt,
                    config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.HIGH  # High reasoning for consolidated analysis
                        ),
                        response_mime_type="application/json",
                        response_schema=CONSOLIDATED_ANALYSIS_SCHEMA
                    )
                )
            
            response = await loop.run_in_executor(
                self.executor,
                generate_consolidated
            )
            
            return {
                "success": True,
                "individual_analyses": individual_analyses,
                "consolidated_analysis": response.text if response and response.text else "Unable to generate consolidated analysis",
                "total_documents": len(documents),
                "processed_at": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            print(f"Error in multi-document analysis: {e}")
            return {
                "success": False,
                "error": str(e),
                "individual_analyses": individual_analyses if 'individual_analyses' in locals() else [],
                "consolidated_analysis": None
            }
    
    def _create_consolidated_prompt(
        self,
        analyses: List[Dict[str, Any]],
        patient_context: Dict[str, Any],
        visit_context: Dict[str, Any],
        doctor_context: Dict[str, Any]
    ) -> str:
        """Create prompt for consolidated analysis of multiple documents"""
        
        patient_name = f"{patient_context.get('first_name', '')} {patient_context.get('last_name', '')}"
        doctor_name = f"Dr. {doctor_context.get('first_name', '')} {doctor_context.get('last_name', '')}"
        
        analyses_summary = ""
        for i, analysis in enumerate(analyses, 1):
            analyses_summary += f"\n**Document {i}: {analysis['file_name']}**\n"
            if analysis['analysis']['success']:
                # Access the raw_analysis from the analysis result
                raw_analysis = analysis['analysis']['analysis']['raw_analysis']
                analyses_summary += raw_analysis[:500] + "...\n"
            else:
                analyses_summary += f"Analysis failed: {analysis['analysis']['error']}\n"
        
        prompt = f"""
You are helping {doctor_name} create a consolidated analysis of multiple medical documents for patient {patient_name}.

**INDIVIDUAL DOCUMENT ANALYSES:**
{analyses_summary}

**PATIENT CONTEXT:**
- Chief Complaint: {visit_context.get('chief_complaint', 'Not specified')}
- Current Symptoms: {visit_context.get('symptoms', 'None specified')}
- Medical History: {patient_context.get('medical_history', 'None provided')}

Please provide a **CONSOLIDATED MEDICAL ANALYSIS** that:

1. **OVERALL ASSESSMENT:**
   - Synthesize findings across all documents
   - Identify patterns and correlations
   - Highlight any conflicting information

2. **COMPREHENSIVE CLINICAL PICTURE:**
   - How all results relate to the patient's presentation
   - Complete diagnostic picture
   - Risk assessment

3. **INTEGRATED RECOMMENDATIONS:**
   - Prioritized action items
   - Coordinated treatment approach
   - Next steps based on all findings

4. **SUMMARY FOR PATIENT:**
   - Unified explanation of all test results
   - Key takeaways in simple terms
   - Coordinated care plan

Focus on creating a cohesive medical narrative that helps Dr. {doctor_name} make comprehensive clinical decisions for {patient_name}.
"""
        
        return prompt
    
    async def analyze_patient_comprehensive_history(
        self,
        patient_context: Dict[str, Any],
        visits: List[Dict[str, Any]],
        reports: List[Dict[str, Any]],
        existing_analyses: List[Dict[str, Any]],
        doctor_context: Dict[str, Any],
        analysis_period_months: Optional[int] = None,
        handwritten_notes: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Perform comprehensive analysis of patient's complete medical history
        including visits, reports, handwritten notes, and all available medical data.
        
        Args:
            patient_context: Patient information and demographics
            visits: List of all patient visits with full details
            reports: List of all medical reports/documents with content
            existing_analyses: Previous AI analyses for this patient
            doctor_context: Doctor information
            analysis_period_months: Optional time period limit
            handwritten_notes: List of handwritten prescription/note documents
        
        Returns:
            Dict containing comprehensive analysis results
        """
        try:
            print(f"🔍 Starting comprehensive history analysis for patient {patient_context.get('id')}")
            print(f"   📊 Data points: {len(visits)} visits, {len(reports)} reports, {len(handwritten_notes or [])} handwritten notes, {len(existing_analyses)} AI analyses")
            
            # Prepare comprehensive prompt with ALL data
            prompt = self._create_comprehensive_history_prompt(
                patient_context,
                visits,
                reports,
                existing_analyses,
                doctor_context,
                analysis_period_months,
                handwritten_notes
            )
            
            # Perform analysis using Gemini 3 Pro with HIGH thinking for complex reasoning
            # Now using JSON mode for structured output
            loop = asyncio.get_event_loop()
            
            def generate_comprehensive():
                return self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.HIGH  # High reasoning for comprehensive history analysis
                        ),
                        response_mime_type="application/json",
                        response_schema=COMPREHENSIVE_HISTORY_SCHEMA
                    )
                )
            
            response = await loop.run_in_executor(
                self.executor,
                generate_comprehensive
            )
            
            if response and response.text:
                analysis_text = response.text
                
                # Try to parse as JSON for structured data
                try:
                    structured_analysis = json.loads(analysis_text)
                    return {
                        "success": True,
                        "comprehensive_analysis": analysis_text,
                        "structured_data": structured_analysis,
                        "confidence_score": 0.85,
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                        "parsing_method": "json_mode"
                    }
                except json.JSONDecodeError:
                    # Fall back to raw text
                    return {
                        "success": True,
                        "comprehensive_analysis": analysis_text,
                        "confidence_score": 0.80,
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                        "parsing_method": "text_fallback"
                    }
            else:
                return {
                    "success": False,
                    "error": "No response from AI model"
                }
            
        except Exception as e:
            logger.error(f"Error in comprehensive history analysis: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _create_comprehensive_history_prompt(
        self,
        patient_context: Dict[str, Any],
        visits: List[Dict[str, Any]],
        reports: List[Dict[str, Any]],
        existing_analyses: List[Dict[str, Any]],
        doctor_context: Dict[str, Any],
        analysis_period_months: Optional[int] = None,
        handwritten_notes: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Create a comprehensive prompt for patient history analysis with ALL available data"""
        
        patient_name = f"{patient_context.get('first_name', '')} {patient_context.get('last_name', '')}"
        doctor_name = f"Dr. {doctor_context.get('first_name', '')} {doctor_context.get('last_name', '')}"
        doctor_specialization = doctor_context.get('specialization', 'General Practice')
        
        # Calculate patient age
        patient_age = "Unknown"
        if patient_context.get('date_of_birth'):
            try:
                dob = datetime.strptime(patient_context['date_of_birth'], '%Y-%m-%d')
                age = (datetime.now() - dob).days // 365
                patient_age = f"{age} years old"
            except:
                pass
        
        # Format time period
        period_text = ""
        if analysis_period_months:
            period_text = f" over the last {analysis_period_months} months"
        else:
            period_text = " across their complete medical history"
        
        # Prepare DETAILED visits summary with ALL information
        visits_summary = ""
        if visits:
            visits_summary = f"\n\n═══════════════════════════════════════════════════════════════\n**📋 COMPLETE MEDICAL VISITS ({len(visits)} total)**\n═══════════════════════════════════════════════════════════════\n"
            for i, visit in enumerate(visits, 1):
                visit_date = visit.get('visit_date', 'Unknown date')
                visit_type = visit.get('visit_type', 'General')
                chief_complaint = visit.get('chief_complaint', 'Not specified')
                symptoms = visit.get('symptoms', 'Not documented')
                diagnosis = visit.get('diagnosis', 'Not specified')
                treatment = visit.get('treatment_plan', 'Not specified')
                medications = visit.get('medications', 'None prescribed')
                clinical_exam = visit.get('clinical_examination', 'Not documented')
                tests_recommended = visit.get('tests_recommended', 'None')
                follow_up = visit.get('follow_up_date', 'Not scheduled')
                notes = visit.get('notes', '')
                
                # Extract vitals with all measurements
                vitals_text = "Not recorded"
                vitals = visit.get('vitals', {})
                if vitals:
                    vitals_parts = []
                    if vitals.get('temperature'):
                        vitals_parts.append(f"Temp: {vitals['temperature']}°C")
                    if vitals.get('blood_pressure_systolic') and vitals.get('blood_pressure_diastolic'):
                        vitals_parts.append(f"BP: {vitals['blood_pressure_systolic']}/{vitals['blood_pressure_diastolic']} mmHg")
                    if vitals.get('heart_rate'):
                        vitals_parts.append(f"HR: {vitals['heart_rate']} bpm")
                    if vitals.get('pulse_rate'):
                        vitals_parts.append(f"Pulse: {vitals['pulse_rate']} bpm")
                    if vitals.get('respiratory_rate'):
                        vitals_parts.append(f"RR: {vitals['respiratory_rate']}/min")
                    if vitals.get('oxygen_saturation'):
                        vitals_parts.append(f"SpO2: {vitals['oxygen_saturation']}%")
                    if vitals.get('weight'):
                        vitals_parts.append(f"Weight: {vitals['weight']} kg")
                    if vitals.get('height'):
                        vitals_parts.append(f"Height: {vitals['height']} cm")
                    if vitals.get('bmi'):
                        vitals_parts.append(f"BMI: {vitals['bmi']}")
                    if vitals_parts:
                        vitals_text = " | ".join(vitals_parts)
                
                visits_summary += f"""
┌─────────────────────────────────────────────────────────────────
│ 📅 VISIT #{i}: {visit_date} ({visit_type})
├─────────────────────────────────────────────────────────────────
│ 🔴 Chief Complaint: {chief_complaint}
│ 📝 Symptoms: {symptoms}
│ 🩺 Vitals: {vitals_text}
│ 🔍 Clinical Examination: {clinical_exam}
│ ✅ Diagnosis: {diagnosis}
│ 💊 Medications Prescribed: {medications}
│ 📋 Treatment Plan: {treatment}
│ 🧪 Tests Recommended: {tests_recommended}
│ 📆 Follow-up Date: {follow_up}
│ 📝 Additional Notes: {notes if notes else 'None'}
└─────────────────────────────────────────────────────────────────
"""
        
        # Prepare DETAILED reports summary with content
        reports_summary = ""
        if reports:
            reports_summary = f"\n\n═══════════════════════════════════════════════════════════════\n**🔬 MEDICAL REPORTS & LAB TESTS ({len(reports)} total)**\n═══════════════════════════════════════════════════════════════\n"
            for i, report in enumerate(reports, 1):
                file_name = report.get('file_name', 'Unknown file')
                test_type = report.get('test_type', 'General Report')
                uploaded_date = report.get('uploaded_at', 'Unknown date')
                visit_id = report.get('visit_id', 'N/A')
                
                # Extract text content from the report if available
                content_preview = ""
                if report.get('content'):
                    try:
                        # Try to decode content
                        raw_content = report['content']
                        if isinstance(raw_content, bytes):
                            # For PDFs, extract text using PyPDF2
                            import io
                            try:
                                import PyPDF2
                                pdf_reader = PyPDF2.PdfReader(io.BytesIO(raw_content))
                                text_content = ""
                                for page in pdf_reader.pages[:3]:  # First 3 pages
                                    text_content += page.extract_text() + "\n"
                                if text_content.strip():
                                    content_preview = text_content[:2000]  # Limit to 2000 chars
                            except:
                                pass
                        elif isinstance(raw_content, str):
                            content_preview = raw_content[:2000]
                    except:
                        pass
                
                reports_summary += f"""
┌─────────────────────────────────────────────────────────────────
│ 📄 REPORT #{i}: {file_name}
├─────────────────────────────────────────────────────────────────
│ 🏷️ Test Type: {test_type}
│ 📅 Uploaded: {uploaded_date}
│ 🔗 Associated Visit ID: {visit_id}
"""
                if content_preview:
                    reports_summary += f"""│ 📊 REPORT CONTENT/FINDINGS:
│ {content_preview[:1500]}{'...' if len(content_preview) > 1500 else ''}
"""
                reports_summary += "└─────────────────────────────────────────────────────────────────\n"
        
        # Prepare handwritten notes summary
        handwritten_summary = ""
        if handwritten_notes:
            handwritten_summary = f"\n\n═══════════════════════════════════════════════════════════════\n**✍️ HANDWRITTEN NOTES & PRESCRIPTIONS ({len(handwritten_notes)} total)**\n═══════════════════════════════════════════════════════════════\n"
            for i, note in enumerate(handwritten_notes, 1):
                file_name = note.get('file_name', 'Handwritten Note')
                created_at = note.get('created_at', 'Unknown date')
                visit_id = note.get('visit_id', 'N/A')
                
                # Extract text from handwritten note PDF
                content_preview = ""
                if note.get('content'):
                    try:
                        raw_content = note['content']
                        if isinstance(raw_content, bytes):
                            import io
                            try:
                                import PyPDF2
                                pdf_reader = PyPDF2.PdfReader(io.BytesIO(raw_content))
                                text_content = ""
                                for page in pdf_reader.pages[:2]:
                                    text_content += page.extract_text() + "\n"
                                if text_content.strip():
                                    content_preview = text_content[:1500]
                            except:
                                pass
                    except:
                        pass
                
                handwritten_summary += f"""
┌─────────────────────────────────────────────────────────────────
│ ✍️ HANDWRITTEN NOTE #{i}: {file_name}
├─────────────────────────────────────────────────────────────────
│ 📅 Created: {created_at}
│ 🔗 Associated Visit ID: {visit_id}
"""
                if content_preview:
                    handwritten_summary += f"""│ 📝 EXTRACTED CONTENT:
│ {content_preview}
"""
                handwritten_summary += "└─────────────────────────────────────────────────────────────────\n"
        
        # Prepare existing analyses summary
        analyses_summary = ""
        if existing_analyses:
            analyses_summary = f"\n\n═══════════════════════════════════════════════════════════════\n**🤖 PREVIOUS AI ANALYSES ({len(existing_analyses)} total)**\n═══════════════════════════════════════════════════════════════\n"
            for i, analysis in enumerate(existing_analyses[:5], 1):
                analyzed_date = analysis.get('analyzed_at', 'Unknown date')
                document_summary = analysis.get('document_summary', 'Not available')
                clinical_significance = analysis.get('clinical_significance', 'Not available')
                key_findings = analysis.get('key_findings', [])
                actionable_insights = analysis.get('actionable_insights', 'Not available')
                
                analyses_summary += f"""
┌─────────────────────────────────────────────────────────────────
│ 🤖 AI ANALYSIS #{i}: {analyzed_date}
├─────────────────────────────────────────────────────────────────
│ 📋 Document Summary: {str(document_summary)[:500]}...
│ 🎯 Clinical Significance: {str(clinical_significance)[:500]}...
│ 🔑 Key Findings: {', '.join(key_findings[:5]) if key_findings else 'None identified'}
│ 💡 Actionable Insights: {str(actionable_insights)[:300]}...
└─────────────────────────────────────────────────────────────────
"""
        
        # Build the comprehensive mega-prompt
        prompt = f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                    🏥 COMPREHENSIVE PATIENT HISTORY ANALYSIS                   ║
║                         DEEP MEDICAL PATTERN DETECTION                         ║
╚═══════════════════════════════════════════════════════════════════════════════╝

You are an advanced AI medical assistant with expertise in pattern recognition, clinical correlation, and comprehensive medical history analysis. You are helping {doctor_name} ({doctor_specialization}) analyze the COMPLETE medical history of {patient_name} ({patient_age}){period_text}.

Your task is to find patterns, correlations, missed opportunities, and provide insights that a human might overlook by reviewing ALL the data together.

═══════════════════════════════════════════════════════════════
**👤 PATIENT DEMOGRAPHICS**
═══════════════════════════════════════════════════════════════
┌─────────────────────────────────────────────────────────────────
│ 📛 Name: {patient_name}
│ 🎂 Age: {patient_age}
│ 👤 Gender: {patient_context.get('gender', 'Not specified')}
│ 🩸 Blood Group: {patient_context.get('blood_group', 'Not specified')}
│ ⚠️ Known Allergies: {patient_context.get('allergies', 'None reported')}
│ 🏥 Medical History: {patient_context.get('medical_history', 'None provided')}
│ 📞 Emergency Contact: {patient_context.get('emergency_contact_name', 'Not provided')}
│ 📧 Email: {patient_context.get('email', 'Not provided')}
│ 📱 Phone: {patient_context.get('phone', 'Not provided')}
└─────────────────────────────────────────────────────────────────
{self._format_prior_medical_history_for_prompt(patient_context)}
{visits_summary}
{reports_summary}
{handwritten_summary}
{analyses_summary}

═══════════════════════════════════════════════════════════════════════════════
                    🎯 COMPREHENSIVE ANALYSIS INSTRUCTIONS
═══════════════════════════════════════════════════════════════════════════════

**YOUR MISSION: Analyze ALL the above data to provide insights that would be impossible to see by looking at individual pieces. Think like a detective connecting clues across time.**

Please provide an extremely thorough analysis covering:

## 1. 🏥 COMPREHENSIVE MEDICAL SUMMARY
- Create a complete narrative of this patient's health journey
- Summarize the key medical events and their significance
- What is the overall "story" of this patient's health?

## 2. 📈 MEDICAL TRAJECTORY & TRENDS
- How has the patient's health changed over time?
- Are they getting better, worse, or stable?
- What trends do you see in vitals, symptoms, or conditions?
- Graph-like description of health trajectory (improving/declining/stable periods)

## 3. 🔄 CHRONIC CONDITIONS & RECURRING ISSUES
- Identify any chronic or recurring conditions
- Which symptoms keep appearing?
- Are there seasonal or cyclical patterns?
- What conditions require ongoing management?

## 4. 🔍 PATTERN DETECTION (CRITICAL!)
**Look for patterns that might be missed:**
- Are there correlations between symptoms and timing?
- Do certain medications seem to trigger new symptoms?
- Are there environmental or lifestyle factors triggering issues?
- What clusters of symptoms appear together?
- Are there warning signs that appeared before major health events?

## 5. ⚠️ MISSED OPPORTUNITIES & CONCERNS
**This is crucial - what might have been overlooked?**
- Are there test results that should have prompted action?
- Were there symptoms that might indicate something more serious?
- Are there recommended tests that were never done?
- Are there medication interactions to be concerned about?
- What diagnoses might have been missed?

## 6. 💊 TREATMENT EFFECTIVENESS REVIEW
- Which treatments have worked well?
- Which treatments haven't shown improvement?
- Are there alternative treatments to consider?
- Is the patient responding to current medication regimens?
- Medication compliance patterns (if detectable)

## 7. 🚨 RISK FACTOR IDENTIFICATION
- Current health risks
- Emerging risks based on trends
- Lifestyle factors affecting health
- Age-appropriate health concerns
- Genetic/hereditary risk indicators

## 8. 📊 SIGNIFICANT FINDINGS SUMMARY
- List the most important findings across ALL data
- What would you definitely want to discuss with the patient?
- What requires immediate attention?

## 9. ✨ ACTIONABLE RECOMMENDATIONS
**Specific, prioritized recommendations:**
- Immediate actions (within 1 week)
- Short-term actions (within 1 month)
- Long-term health management strategies
- Preventive care recommendations
- Lifestyle modification suggestions
- Screening tests to consider

## 10. 💬 PATIENT COMMUNICATION GUIDE
- How to explain the overall health status to the patient
- Key points to emphasize in patient consultation
- Areas where patient education is needed
- Motivational approaches for lifestyle changes

## 11. 📅 FOLLOW-UP & MONITORING PLAN
- Recommended monitoring schedule
- Tests that should be repeated and when
- Specialist referrals if indicated
- Red flags to watch for

## 12. 🔗 DATA CORRELATION INSIGHTS
**Connect the dots between different pieces of data:**
- How do lab results relate to symptoms?
- Do physical exam findings match test results?
- Are there inconsistencies that need clarification?
- How do different visits relate to each other?

═══════════════════════════════════════════════════════════════════════════════
                            ⚡ CRITICAL PRINCIPLES
═══════════════════════════════════════════════════════════════════════════════

✓ Think holistically - every piece of data might connect to another
✓ Look for what's NOT there as much as what IS there
✓ Consider time relationships between events
✓ Flag anything that seems unusual or worth investigating
✓ Be specific and actionable in recommendations
✓ Consider the patient's age, gender, and overall context
✓ If something doesn't make sense, mention it as a concern
✓ Prioritize findings by clinical importance
✓ Think about quality of life, not just medical metrics

This comprehensive analysis will help {doctor_name} provide the best possible care for {patient_name}, especially if they're returning after a gap or if this is a complex case requiring a holistic view.

═══════════════════════════════════════════════════════════════════════════════
                         📝 FORMAT YOUR RESPONSE
═══════════════════════════════════════════════════════════════════════════════

Use clear markdown formatting with:
- **Bold** for important points
- Bullet points for lists
- Clear section headers
- Numbered items for prioritized recommendations
- ⚠️ for warnings/concerns
- ✅ for positive findings
- 🔍 for insights that require further investigation

"""
        
        return prompt
    
    def _parse_comprehensive_analysis(self, analysis_text: str) -> Dict[str, Any]:
        """Parse the comprehensive analysis text into structured components"""
        try:
            # Simple parsing - in a real implementation, you might want more sophisticated parsing
            sections = {
                "summary": "",
                "medical_trajectory": "",
                "chronic_conditions": [],
                "recurring_patterns": [],
                "treatment_effectiveness": "",
                "risk_factors": [],
                "recommendations": [],
                "significant_findings": [],
                "lifestyle_factors": "",
                "medication_history": "",
                "follow_up_suggestions": []
            }
            
            # Extract key information from analysis text
            # This is a simplified version - you might want to implement more sophisticated parsing
            lines = analysis_text.split('\n')
            current_section = None
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Look for section headers
                if "COMPREHENSIVE MEDICAL SUMMARY" in line.upper():
                    current_section = "summary"
                elif "MEDICAL TRAJECTORY" in line.upper():
                    current_section = "medical_trajectory"
                elif "CHRONIC CONDITIONS" in line.upper() or "PATTERNS" in line.upper():
                    current_section = "chronic_conditions"
                elif "TREATMENT EFFECTIVENESS" in line.upper():
                    current_section = "treatment_effectiveness"
                elif "RISK FACTORS" in line.upper():
                    current_section = "risk_factors"
                elif "RECOMMENDATIONS" in line.upper():
                    current_section = "recommendations"
                elif "SIGNIFICANT" in line.upper() and "FINDINGS" in line.upper():
                    current_section = "significant_findings"
                elif "LIFESTYLE" in line.upper():
                    current_section = "lifestyle_factors"
                elif "MEDICATION HISTORY" in line.upper():
                    current_section = "medication_history"
                elif "FOLLOW-UP" in line.upper():
                    current_section = "follow_up_suggestions"
                elif current_section and line:
                    # Add content to current section
                    if current_section in ["chronic_conditions", "risk_factors", "recommendations", "significant_findings", "follow_up_suggestions"]:
                        # For list sections, extract bullet points
                        if line.startswith(('- ', '• ', '* ', '1. ', '2. ', '3. ')):
                            clean_line = line.lstrip('- •*123456789. ').strip()
                            if clean_line:
                                sections[current_section].append(clean_line)
                    else:
                        # For text sections, append to string
                        if sections[current_section]:
                            sections[current_section] += " " + line
                        else:
                            sections[current_section] = line
            
            # Clean up text sections (limit length)
            for key in ["summary", "medical_trajectory", "treatment_effectiveness", "lifestyle_factors", "medication_history"]:
                if len(sections[key]) > 1000:
                    sections[key] = sections[key][:1000] + "..."
            
            return sections
            
        except Exception as e:
            print(f"Error parsing comprehensive analysis: {e}")
            return {
                "summary": analysis_text[:500] + "..." if len(analysis_text) > 500 else analysis_text,
                "medical_trajectory": "",
                "chronic_conditions": [],
                "recurring_patterns": [],
                "treatment_effectiveness": "",
                "risk_factors": [],
                "recommendations": [],
                "significant_findings": [],
                "lifestyle_factors": "",
                "medication_history": "",
                "follow_up_suggestions": []
            }
    
    def _generate_text_response(self, prompt: str) -> str:
        """Generate text response using Gemini 3 Pro model"""
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(
                        thinking_level=types.ThinkingLevel.LOW  # Fast response for simple text generation
                    )
                )
            )
            if response and response.text:
                return response.text
            else:
                return ""
        except Exception as e:
            print(f"Error generating text response: {e}")
            return ""
    
    async def analyze_handwritten_prescription(
        self,
        file_content: bytes,
        file_name: str,
        patient_context: Dict[str, Any],
        visit_context: Dict[str, Any],
        doctor_context: Dict[str, Any],
        visit_chain_context: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Analyze a handwritten prescription PDF using Gemini 3 Pro's multimodal capabilities.
        This extracts and interprets handwritten medical notes from the prescription pad.
        
        Args:
            file_content: The binary content of the PDF file
            file_name: Name of the file
            patient_context: Patient information
            visit_context: Visit information (may be minimal if doctor only wrote on prescription)
            doctor_context: Doctor information
            visit_chain_context: List of linked previous visits for continuity of care
        
        Returns:
            Dict containing analysis results including extracted content and medical interpretation
        """
        try:
            print(f"🖊️ Starting handwritten prescription analysis for: {file_name}")
            
            # Prepare the PDF document - Gemini 3 Pro can directly handle PDFs
            document_data = {
                "type": "pdf",
                "content": file_content,
                "mime_type": "application/pdf"
            }
            
            # Create specialized prompt for handwritten prescription analysis
            prompt = self._create_handwritten_prescription_prompt(
                patient_context,
                visit_context,
                doctor_context,
                file_name,
                visit_chain_context
            )
            
            # Perform AI analysis using multimodal capabilities
            analysis_result = await self._perform_handwritten_analysis(prompt, document_data)
            
            if "error" in analysis_result and analysis_result.get("error"):
                return {
                    "success": False,
                    "error": analysis_result["error"],
                    "analysis": None
                }
            
            return {
                "success": True,
                "analysis": analysis_result,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "model_used": self.model_name,
                "analysis_type": "handwritten_prescription"
            }
            
        except Exception as e:
            print(f"❌ Error in handwritten prescription analysis: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
                "analysis": None
            }
    
    def _create_handwritten_prescription_prompt(
        self,
        patient_context: Dict[str, Any],
        visit_context: Dict[str, Any],
        doctor_context: Dict[str, Any],
        file_name: str,
        visit_chain_context: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Create a specialized prompt for analyzing handwritten prescription PDFs with linked visit context"""
        
        # Extract patient information
        patient_name = f"{patient_context.get('first_name', '')} {patient_context.get('last_name', '')}"
        patient_age = self._calculate_age(patient_context.get('date_of_birth', ''))
        patient_gender = patient_context.get('gender', 'Not specified')
        medical_history = patient_context.get('medical_history', 'None provided')
        allergies = patient_context.get('allergies', 'None known')
        blood_group = patient_context.get('blood_group', 'Not specified')
        
        # Extract visit information (may be partial since doctor wrote on prescription)
        visit_date = visit_context.get('visit_date', 'Not specified')
        visit_type = visit_context.get('visit_type', 'General consultation')
        chief_complaint = visit_context.get('chief_complaint', 'See handwritten notes')
        symptoms = visit_context.get('symptoms', 'See handwritten notes')
        
        # Extract vitals if available
        vitals_text = "Not recorded digitally"
        if visit_context.get('vitals'):
            vitals = visit_context.get('vitals', {})
            vitals_parts = []
            if vitals.get('blood_pressure'):
                vitals_parts.append(f"BP: {vitals['blood_pressure']}")
            if vitals.get('pulse'):
                vitals_parts.append(f"Pulse: {vitals['pulse']} bpm")
            if vitals.get('temperature'):
                vitals_parts.append(f"Temp: {vitals['temperature']}°F")
            if vitals.get('weight'):
                vitals_parts.append(f"Weight: {vitals['weight']} kg")
            if vitals.get('spo2'):
                vitals_parts.append(f"SpO2: {vitals['spo2']}%")
            if vitals_parts:
                vitals_text = ", ".join(vitals_parts)
        
        # Extract doctor information
        doctor_name = f"Dr. {doctor_context.get('first_name', '')} {doctor_context.get('last_name', '')}"
        specialization = doctor_context.get('specialization', 'General Medicine')
        
        # Build visit chain context section if available
        visit_chain_section = ""
        if visit_chain_context and len(visit_chain_context) > 0:
            visit_chain_section = """
**🔗 LINKED VISIT HISTORY (THIS IS A FOLLOW-UP VISIT):**
This patient has been seen before for related concerns. Use this history for context.

"""
            for i, prev_visit in enumerate(visit_chain_context, 1):
                prev_date = prev_visit.get('visit_date', 'Unknown date')
                prev_complaint = prev_visit.get('chief_complaint', 'Not recorded')
                prev_diagnosis = prev_visit.get('diagnosis', 'Not recorded')
                prev_treatment = prev_visit.get('treatment_plan', 'Not recorded')
                prev_medications = prev_visit.get('medications', 'None')
                # Use visit_type as context indicator (case-based architecture)
                visit_context_label = prev_visit.get('visit_type', 'Follow-up')
                
                # Include previous handwritten notes summary if available
                prev_notes = ""
                if prev_visit.get('handwritten_summary'):
                    prev_notes = f"\\n    - Previous Handwritten Notes Summary: {prev_visit.get('handwritten_summary', '')[:200]}"
                
                visit_chain_section += f"""
  **Previous Visit #{i} ({visit_context_label}):**
    - Date: {prev_date}
    - Chief Complaint: {prev_complaint}
    - Diagnosis: {prev_diagnosis}
    - Treatment Given: {prev_treatment}
    - Medications: {prev_medications}{prev_notes}
"""
            
            visit_chain_section += """
⚠️ **CONTINUITY INSTRUCTIONS:**
- Compare current prescription with previous prescriptions
- Note any changes in medications or dosages
- Evaluate if this is a continuation or change of treatment
- Flag if previous medications are being discontinued

"""
        
        prompt = f"""
You are an advanced AI medical assistant with specialized training in reading and interpreting handwritten medical documents. You are helping {doctor_name} ({specialization}) by analyzing a handwritten prescription/visit notes for their patient.

**IMPORTANT CONTEXT:**
This is a HANDWRITTEN prescription pad that the doctor has filled out during the patient consultation. The doctor chose to write on the prescription pad instead of typing details into the system. Your task is to:
1. EXTRACT all handwritten content from the prescription
2. INTERPRET the medical content correctly
3. PROVIDE clinical analysis of the documented information

**PATIENT INFORMATION (from system):**
- Name: {patient_name}
- Age: {patient_age}
- Gender: {patient_gender}
- Blood Group: {blood_group}
- Known Allergies: {allergies}
- Medical History: {medical_history}
{visit_chain_section}
**CURRENT VISIT CONTEXT (from system):**
- Visit Date: {visit_date}
- Visit Type: {visit_type}
- Chief Complaint (if entered): {chief_complaint}
- Symptoms (if entered): {symptoms}
- Vitals (if recorded): {vitals_text}

**DOCUMENT TO ANALYZE:**
- File Name: {file_name}
- Document Type: Handwritten Prescription/Visit Notes

**ANALYSIS INSTRUCTIONS:**

Please provide a comprehensive analysis in this format:

**1. HANDWRITING EXTRACTION:**
📝 Extract ALL readable text from the handwritten prescription:
- Header information (date, patient name if written)
- Chief complaint / reason for visit
- History of present illness
- Clinical examination findings
- Diagnosis (Rx/Dx)
- Treatment plan
- Medications prescribed (with dosage, frequency, duration)
- Special instructions
- Follow-up notes
- Any drawings, diagrams, or annotations

**2. MEDICATION ANALYSIS:**
💊 For each medication identified:
- Drug name (generic and brand if mentioned)
- Dosage
- Route of administration
- Frequency
- Duration
- Food/timing instructions
- Any warnings or precautions written

**3. CLINICAL INTERPRETATION:**
🏥 Based on the handwritten notes:
- What condition(s) is the doctor treating?
- Is the diagnosis clear from the handwriting?
- Are the medications appropriate for the apparent diagnosis?
- Any potential drug interactions to note?
- Appropriateness for patient's age ({patient_age}) and medical history

**4. ALLERGY & SAFETY CHECK:**
⚠️ Cross-reference with patient's known allergies ({allergies}):
- Any prescribed medications that might conflict with allergies?
- Any contraindications based on medical history ({medical_history})?
- Any safety concerns?

**5. PATIENT INSTRUCTIONS SUMMARY:**
📋 Clear summary for the patient:
- Diagnosis in simple terms
- Medication schedule in easy-to-understand format
- Lifestyle or dietary instructions
- Warning signs to watch for
- When to return for follow-up

**6. CLINICAL DOCUMENTATION:**
📁 Structured data extracted for medical records:
- Diagnosis (ICD codes if determinable)
- Procedures performed (if any)
- Medications prescribed (structured format)
- Follow-up plan

**7. HANDWRITING QUALITY NOTES:**
✍️ Assessment of document:
- Overall legibility score (1-10)
- Any sections that were difficult to read
- Any ambiguous medications or dosages that need verification
- Recommendations for clarification if needed

**8. VISIT SUMMARY:**
📊 Comprehensive summary of this visit based on the handwritten prescription:
- Primary diagnosis
- Secondary findings
- Treatment approach
- Prognosis indicators
- Critical follow-up requirements

**CRITICAL GUIDELINES:**
✓ If handwriting is unclear, indicate uncertainty with [?] or [unclear]
✓ For medications, if unsure of exact spelling, provide best interpretation with alternatives
✓ Flag any potentially dangerous prescriptions or dosages
✓ Consider patient's age and medical history in analysis
✓ Note if the handwriting suggests any urgency or severity
✓ Preserve doctor's original intent while clarifying for records

This analysis will help ensure accurate medical records and patient safety by properly interpreting Dr. {doctor_name}'s handwritten prescription for {patient_name}.
"""
        
        return prompt
    
    async def _perform_handwritten_analysis(
        self,
        prompt: str,
        document_data: Dict[str, Any],
        max_retries: int = 3,
        use_json_mode: bool = True
    ) -> Dict[str, Any]:
        """
        Perform AI analysis on handwritten prescription using Gemini 3 Pro multimodal.
        
        Now uses JSON structured output mode for reliable parsing.
        """
        
        for attempt in range(max_retries):
            try:
                loop = asyncio.get_event_loop()
                
                # For handwritten PDFs, we send the PDF directly to Gemini 3 Pro
                # which has excellent multimodal capabilities for reading handwriting
                pdf_part = types.Part.from_bytes(
                    data=document_data["content"],
                    mime_type="application/pdf"
                )
                
                content_parts = [prompt, pdf_part]
                
                # Use HIGH thinking level for handwritten analysis 
                # as it requires more reasoning to interpret handwriting
                # Now with JSON structured output for reliable parsing
                def generate_sync():
                    if use_json_mode:
                        return self.client.models.generate_content(
                            model=self.model_name,
                            contents=content_parts,
                            config=types.GenerateContentConfig(
                                thinking_config=types.ThinkingConfig(
                                    thinking_level=types.ThinkingLevel.HIGH
                                ),
                                response_mime_type="application/json",
                                response_schema=HANDWRITTEN_ANALYSIS_SCHEMA
                            )
                        )
                    else:
                        return self.client.models.generate_content(
                            model=self.model_name,
                            contents=content_parts,
                            config=types.GenerateContentConfig(
                                thinking_config=types.ThinkingConfig(
                                    thinking_level=types.ThinkingLevel.HIGH
                                )
                            )
                        )
                
                response = await loop.run_in_executor(
                    self.executor,
                    generate_sync
                )
                
                if response and response.text:
                    analysis_text = response.text
                    
                    if use_json_mode:
                        try:
                            # Parse JSON response directly
                            structured_analysis = json.loads(analysis_text)
                            
                            # Extract key data from structured response
                            medications = structured_analysis.get("medications", [])
                            diagnosis = structured_analysis.get("diagnosis", {})
                            diagnosis_text = diagnosis.get("primary_diagnosis", "") if isinstance(diagnosis, dict) else str(diagnosis)
                            legibility = structured_analysis.get("document_quality", {})
                            legibility_score = legibility.get("legibility_score", 7) if isinstance(legibility, dict) else 7
                            
                            return {
                                "raw_analysis": analysis_text,
                                "structured_analysis": structured_analysis,
                                "confidence_score": self._calculate_handwriting_confidence_from_structured(structured_analysis),
                                "analysis_length": len(analysis_text),
                                "extracted_medications": medications,
                                "extracted_diagnosis": diagnosis_text,
                                "legibility_score": legibility_score,
                                "structured_data": structured_analysis,  # New field for direct storage
                                "parsing_method": "json_mode"
                            }
                        except json.JSONDecodeError as je:
                            logger.warning(f"JSON parsing failed for handwritten analysis, falling back: {je}")
                            # Fall back to text parsing
                            parsed_analysis = self._parse_handwritten_analysis_response(analysis_text)
                            return {
                                "raw_analysis": analysis_text,
                                "structured_analysis": parsed_analysis,
                                "confidence_score": self._calculate_handwriting_confidence(analysis_text),
                                "analysis_length": len(analysis_text),
                                "extracted_medications": parsed_analysis.get("medications", []),
                                "extracted_diagnosis": parsed_analysis.get("diagnosis", ""),
                                "legibility_score": parsed_analysis.get("legibility_score", 7),
                                "parsing_method": "text_fallback"
                            }
                    else:
                        # Legacy text parsing mode
                        parsed_analysis = self._parse_handwritten_analysis_response(analysis_text)
                        return {
                            "raw_analysis": analysis_text,
                            "structured_analysis": parsed_analysis,
                            "confidence_score": self._calculate_handwriting_confidence(analysis_text),
                            "analysis_length": len(analysis_text),
                            "extracted_medications": parsed_analysis.get("medications", []),
                            "extracted_diagnosis": parsed_analysis.get("diagnosis", ""),
                            "legibility_score": parsed_analysis.get("legibility_score", 7),
                            "parsing_method": "text_mode"
                        }
                else:
                    return {
                        "error": "No response from AI model",
                        "raw_analysis": "",
                        "structured_analysis": {},
                        "confidence_score": 0.0
                    }
                    
            except Exception as e:
                error_message = str(e)
                
                # Check if it's a rate limit error (429)
                if "429" in error_message or "Resource exhausted" in error_message or "RESOURCE_EXHAUSTED" in error_message:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** (attempt + 1)
                        logger.warning(f"Rate limit hit. Retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Rate limit exceeded after {max_retries} attempts")
                        return {
                            "error": "Rate limit exceeded. Please try again later.",
                            "raw_analysis": "",
                            "structured_analysis": {},
                            "confidence_score": 0.0
                        }
                else:
                    logger.error(f"Error in handwritten analysis: {e}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    return {
                        "error": error_message,
                        "raw_analysis": "",
                        "structured_analysis": {},
                        "confidence_score": 0.0
                    }
        
        return {
            "error": "Analysis failed after retries",
            "raw_analysis": "",
            "structured_analysis": {},
            "confidence_score": 0.0
        }
    
    def _calculate_handwriting_confidence_from_structured(self, structured_data: Dict[str, Any]) -> float:
        """Calculate confidence score from structured handwritten analysis response"""
        try:
            base_score = 0.70
            
            # Check document quality
            doc_quality = structured_data.get("document_quality", {})
            legibility = doc_quality.get("legibility_score", 5) if isinstance(doc_quality, dict) else 5
            base_score += (legibility - 5) * 0.02  # Adjust based on legibility (5 is neutral)
            
            # Check for medications extracted
            meds = structured_data.get("medications", [])
            if meds and len(meds) > 0:
                base_score += 0.05
                # Check if medications have complete info
                complete_meds = sum(1 for m in meds if m.get("dosage") and m.get("frequency"))
                base_score += min(0.05, complete_meds * 0.01)
            
            # Check for diagnosis
            if structured_data.get("diagnosis"):
                base_score += 0.05
            
            # Check for safety concerns flagged
            safety = structured_data.get("safety_check", {})
            if safety.get("allergy_conflicts") or safety.get("drug_interactions"):
                # If safety issues detected, slightly reduce confidence (complexity indicator)
                base_score -= 0.03
            
            return min(0.95, max(0.4, base_score))
            
        except Exception as e:
            logger.warning(f"Error calculating handwriting confidence from structured data: {e}")
            return 0.65
    
    def _parse_handwritten_analysis_response(self, analysis_text: str) -> Dict[str, Any]:
        """Parse the handwritten prescription analysis response"""
        try:
            sections = {
                "extracted_text": "",
                "medications": [],
                "diagnosis": "",
                "clinical_interpretation": "",
                "safety_check": "",
                "patient_instructions": "",
                "clinical_documentation": "",
                "legibility_score": 7,
                "visit_summary": "",
                "handwriting_notes": ""
            }
            
            current_section = None
            lines = analysis_text.split('\n')
            
            for line in lines:
                line = line.strip()
                
                # Check for section headers
                if "HANDWRITING EXTRACTION" in line.upper():
                    current_section = "extracted_text"
                elif "MEDICATION ANALYSIS" in line.upper():
                    current_section = "medications"
                elif "CLINICAL INTERPRETATION" in line.upper():
                    current_section = "clinical_interpretation"
                elif "ALLERGY" in line.upper() and "SAFETY" in line.upper():
                    current_section = "safety_check"
                elif "PATIENT INSTRUCTIONS" in line.upper():
                    current_section = "patient_instructions"
                elif "CLINICAL DOCUMENTATION" in line.upper():
                    current_section = "clinical_documentation"
                elif "HANDWRITING QUALITY" in line.upper():
                    current_section = "handwriting_notes"
                elif "VISIT SUMMARY" in line.upper():
                    current_section = "visit_summary"
                elif line and current_section:
                    # Extract legibility score if found
                    if current_section == "handwriting_notes" and "legibility" in line.lower():
                        import re
                        score_match = re.search(r'(\d+)\s*/?\s*10', line)
                        if score_match:
                            sections["legibility_score"] = int(score_match.group(1))
                    
                    # Add content to current section
                    clean_line = line.lstrip('📝💊🏥⚠️📋📁✍️📊-•*')
                    if clean_line and not clean_line.startswith('**'):
                        if current_section == "medications":
                            # Try to extract medications as list items
                            if clean_line and not clean_line.startswith('For each'):
                                sections["medications"].append(clean_line)
                        elif current_section in sections and isinstance(sections[current_section], str):
                            if sections[current_section]:
                                sections[current_section] += " " + clean_line
                            else:
                                sections[current_section] = clean_line
            
            # Try to extract diagnosis from clinical interpretation or documentation
            if not sections["diagnosis"]:
                for section_text in [sections["clinical_interpretation"], sections["clinical_documentation"], sections["visit_summary"]]:
                    if "diagnosis" in section_text.lower() or "treating" in section_text.lower():
                        sections["diagnosis"] = section_text[:200]
                        break
            
            return sections
            
        except Exception as e:
            print(f"Error parsing handwritten analysis: {e}")
            return {
                "extracted_text": analysis_text[:500] if len(analysis_text) > 500 else analysis_text,
                "medications": [],
                "diagnosis": "",
                "clinical_interpretation": "",
                "safety_check": "",
                "patient_instructions": "",
                "clinical_documentation": "",
                "legibility_score": 5,
                "visit_summary": "",
                "handwriting_notes": ""
            }
    
    def _calculate_handwriting_confidence(self, analysis_text: str) -> float:
        """Calculate confidence score for handwritten prescription analysis"""
        try:
            base_score = 0.65  # Start slightly lower for handwritten docs
            
            # Increase score based on content indicators
            if len(analysis_text) > 1500:
                base_score += 0.1
            if len(analysis_text) > 3000:
                base_score += 0.1
            
            # Positive indicators (clear extraction)
            positive_indicators = [
                'medication', 'dosage', 'mg', 'tablet', 'times daily',
                'diagnosis', 'examination', 'prescription', 'follow-up'
            ]
            
            # Negative indicators (uncertainty)
            negative_indicators = [
                'unclear', 'illegible', 'uncertain', 'cannot read',
                'ambiguous', 'difficult to interpret', '[?]'
            ]
            
            positive_count = sum(1 for ind in positive_indicators if ind.lower() in analysis_text.lower())
            negative_count = sum(1 for ind in negative_indicators if ind.lower() in analysis_text.lower())
            
            base_score += min(0.15, positive_count * 0.02)
            base_score -= min(0.2, negative_count * 0.05)
            
            return max(0.3, min(0.95, base_score))
            
        except:
            return 0.6
    
    # ==========================================================================
    # PHASE 2: CLINICAL INTELLIGENCE METHODS
    # ==========================================================================
    
    async def generate_visit_summary(
        self,
        patient_context: Dict[str, Any],
        visit_context: Dict[str, Any],
        reports: List[Dict[str, Any]],
        analyses: List[Dict[str, Any]],
        doctor_context: Dict[str, Any],
        handwritten_notes: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Generate a professional SOAP note visit summary for documentation.
        
        Phase 2.3: Smart Visit Summary Generation
        
        Args:
            patient_context: Patient information
            visit_context: Current visit details
            reports: Medical reports from this visit
            analyses: AI analyses from this visit
            doctor_context: Doctor information
            handwritten_notes: Optional handwritten notes
            
        Returns:
            SOAP note structured data
        """
        try:
            logger.info(f"Generating visit summary for visit {visit_context.get('id')}")
            
            # Import SOAP schema
            from ai_schemas import SOAP_NOTE_SCHEMA
            
            # Build the prompt
            prompt = self._create_visit_summary_prompt(
                patient_context, visit_context, reports, analyses,
                doctor_context, handwritten_notes
            )
            
            # Generate using Gemini with JSON mode
            loop = asyncio.get_event_loop()
            
            def generate_soap():
                return self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.MEDIUM
                        ),
                        response_mime_type="application/json",
                        response_schema=SOAP_NOTE_SCHEMA
                    )
                )
            
            response = await loop.run_in_executor(self.executor, generate_soap)
            
            if response and response.text:
                try:
                    soap_data = json.loads(response.text)
                    
                    # Generate text version of SOAP note
                    soap_text = self._format_soap_note_text(soap_data)
                    
                    return {
                        "success": True,
                        "soap_note": soap_data,
                        "soap_note_text": soap_text,
                        "confidence_score": 0.85,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "model_used": self.model_name
                    }
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse SOAP JSON: {e}")
                    return {
                        "success": True,
                        "soap_note_text": response.text,
                        "confidence_score": 0.70,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "parsing_method": "text_fallback"
                    }
            else:
                return {"success": False, "error": "No response from AI model"}
                
        except Exception as e:
            logger.error(f"Error generating visit summary: {e}")
            return {"success": False, "error": str(e)}
    
    def _create_visit_summary_prompt(
        self,
        patient_context: Dict[str, Any],
        visit_context: Dict[str, Any],
        reports: List[Dict[str, Any]],
        analyses: List[Dict[str, Any]],
        doctor_context: Dict[str, Any],
        handwritten_notes: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Create prompt for SOAP note generation"""
        
        patient_name = f"{patient_context.get('first_name', '')} {patient_context.get('last_name', '')}"
        patient_age = self._calculate_age(patient_context.get('date_of_birth', ''))
        doctor_name = f"Dr. {doctor_context.get('first_name', '')} {doctor_context.get('last_name', '')}"
        
        # Format vitals
        vitals_text = "Not recorded"
        vitals = visit_context.get('vitals', {})
        if vitals:
            vitals_parts = []
            if vitals.get('blood_pressure_systolic') and vitals.get('blood_pressure_diastolic'):
                vitals_parts.append(f"BP: {vitals['blood_pressure_systolic']}/{vitals['blood_pressure_diastolic']} mmHg")
            if vitals.get('heart_rate'):
                vitals_parts.append(f"HR: {vitals['heart_rate']} bpm")
            if vitals.get('temperature'):
                vitals_parts.append(f"Temp: {vitals['temperature']}°C")
            if vitals.get('respiratory_rate'):
                vitals_parts.append(f"RR: {vitals['respiratory_rate']}/min")
            if vitals.get('oxygen_saturation'):
                vitals_parts.append(f"SpO2: {vitals['oxygen_saturation']}%")
            if vitals.get('weight'):
                vitals_parts.append(f"Wt: {vitals['weight']} kg")
            if vitals_parts:
                vitals_text = ", ".join(vitals_parts)
        
        # Format analyses summary
        analyses_summary = ""
        if analyses:
            analyses_summary = "\n**AI Analysis Findings:**\n"
            for analysis in analyses[:3]:
                doc_summary = analysis.get('document_summary', analysis.get('structured_data', {}).get('document_summary', ''))
                if doc_summary:
                    analyses_summary += f"- {str(doc_summary)[:300]}\n"
        
        prompt = f"""
Generate a professional medical visit summary in SOAP format for documentation.

**PATIENT INFORMATION:**
- Name: {patient_name}
- Age: {patient_age}
- Gender: {patient_context.get('gender', 'Not specified')}
- Blood Group: {patient_context.get('blood_group', 'Not specified')}
- Allergies: {patient_context.get('allergies', 'None known')}
- Medical History: {patient_context.get('medical_history', 'None documented')}

**VISIT DETAILS:**
- Date: {visit_context.get('visit_date', 'Not specified')}
- Visit Type: {visit_context.get('visit_type', 'General')}
- Doctor: {doctor_name} ({doctor_context.get('specialization', 'General Medicine')})

**CLINICAL DATA:**
- Chief Complaint: {visit_context.get('chief_complaint', 'Not specified')}
- Presenting Symptoms: {visit_context.get('symptoms', 'Not documented')}
- Vitals: {vitals_text}
- Clinical Examination: {visit_context.get('clinical_examination', 'Not documented')}
- Diagnosis: {visit_context.get('diagnosis', 'Pending')}
- Treatment Plan: {visit_context.get('treatment_plan', 'Not specified')}
- Medications: {visit_context.get('medications', 'None prescribed')}
- Tests Recommended: {visit_context.get('tests_recommended', 'None')}
- Follow-up: {visit_context.get('follow_up_date', 'Not scheduled')}

**REPORTS REVIEWED:** {len(reports)} document(s)
{analyses_summary}

**INSTRUCTIONS:**
Generate a concise, professional SOAP note that includes:

1. **Subjective (S):** Patient's reported symptoms, history of present illness, relevant medical history
2. **Objective (O):** Vital signs, physical examination findings, lab/imaging results
3. **Assessment (A):** Diagnosis with clinical reasoning, differential diagnoses if applicable
4. **Plan (P):** Treatment plan, medications, follow-up instructions, patient education

Also provide:
- ICD-10 codes for documented diagnoses (if determinable)
- CPT codes for any procedures (if applicable)
- Clinical reasoning for the assessment
- Prognosis if appropriate

The note should be suitable for medical records and insurance documentation.
"""
        return prompt
    
    def _format_soap_note_text(self, soap_data: Dict[str, Any]) -> str:
        """Format structured SOAP data into readable text"""
        lines = ["=" * 60, "SOAP NOTE", "=" * 60, ""]
        
        # Subjective
        subj = soap_data.get("subjective", {})
        lines.append("SUBJECTIVE:")
        lines.append("-" * 40)
        if subj.get("chief_complaint"):
            lines.append(f"Chief Complaint: {subj['chief_complaint']}")
        if subj.get("history_of_present_illness"):
            lines.append(f"HPI: {subj['history_of_present_illness']}")
        if subj.get("past_medical_history"):
            lines.append(f"PMH: {subj['past_medical_history']}")
        if subj.get("medications"):
            lines.append(f"Medications: {subj['medications']}")
        if subj.get("allergies"):
            lines.append(f"Allergies: {subj['allergies']}")
        lines.append("")
        
        # Objective
        obj = soap_data.get("objective", {})
        lines.append("OBJECTIVE:")
        lines.append("-" * 40)
        if obj.get("vital_signs"):
            lines.append(f"Vitals: {obj['vital_signs']}")
        if obj.get("physical_examination"):
            lines.append(f"Physical Exam: {obj['physical_examination']}")
        if obj.get("laboratory_results"):
            lines.append(f"Labs: {obj['laboratory_results']}")
        if obj.get("imaging_results"):
            lines.append(f"Imaging: {obj['imaging_results']}")
        lines.append("")
        
        # Assessment
        assess = soap_data.get("assessment", {})
        lines.append("ASSESSMENT:")
        lines.append("-" * 40)
        if assess.get("primary_diagnosis"):
            lines.append(f"Primary Dx: {assess['primary_diagnosis']}")
        if assess.get("differential_diagnoses"):
            lines.append(f"Differentials: {', '.join(assess['differential_diagnoses'])}")
        if assess.get("icd10_codes"):
            lines.append(f"ICD-10: {', '.join(assess['icd10_codes'])}")
        if assess.get("clinical_reasoning"):
            lines.append(f"Reasoning: {assess['clinical_reasoning']}")
        lines.append("")
        
        # Plan
        plan = soap_data.get("plan", {})
        lines.append("PLAN:")
        lines.append("-" * 40)
        if plan.get("treatment_plan"):
            lines.append(f"Treatment: {plan['treatment_plan']}")
        if plan.get("medications_prescribed"):
            lines.append(f"Rx: {', '.join(plan['medications_prescribed'])}")
        if plan.get("follow_up_instructions"):
            lines.append(f"Follow-up: {plan['follow_up_instructions']}")
        if plan.get("patient_education"):
            lines.append(f"Education: {plan['patient_education']}")
        if plan.get("cpt_codes"):
            lines.append(f"CPT: {', '.join(plan['cpt_codes'])}")
        
        lines.append("")
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    async def calculate_patient_risk_score(
        self,
        patient_context: Dict[str, Any],
        visits: List[Dict[str, Any]],
        analyses: List[Dict[str, Any]],
        doctor_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive patient risk scores using AI analysis.
        
        Phase 2.4: Patient Risk Scoring
        
        Args:
            patient_context: Patient demographics and history
            visits: List of patient visits
            analyses: Previous AI analyses
            doctor_context: Doctor information
            
        Returns:
            Risk score assessment
        """
        try:
            logger.info(f"Calculating risk score for patient {patient_context.get('id')}")
            
            from ai_schemas import RISK_SCORE_SCHEMA
            
            # Build comprehensive prompt
            prompt = self._create_risk_score_prompt(
                patient_context, visits, analyses, doctor_context
            )
            
            loop = asyncio.get_event_loop()
            
            def generate_risk():
                return self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.HIGH
                        ),
                        response_mime_type="application/json",
                        response_schema=RISK_SCORE_SCHEMA
                    )
                )
            
            response = await loop.run_in_executor(self.executor, generate_risk)
            
            if response and response.text:
                try:
                    risk_data = json.loads(response.text)
                    return {
                        "success": True,
                        "risk_scores": risk_data,
                        "calculated_at": datetime.now(timezone.utc).isoformat(),
                        "visits_analyzed": len(visits),
                        "analyses_used": len(analyses),
                        "model_used": self.model_name
                    }
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse risk score JSON: {e}")
                    return {
                        "success": False,
                        "error": "Failed to parse AI response",
                        "raw_response": response.text
                    }
            else:
                return {"success": False, "error": "No response from AI model"}
                
        except Exception as e:
            logger.error(f"Error calculating risk score: {e}")
            return {"success": False, "error": str(e)}
    
    def _create_risk_score_prompt(
        self,
        patient_context: Dict[str, Any],
        visits: List[Dict[str, Any]],
        analyses: List[Dict[str, Any]],
        doctor_context: Dict[str, Any]
    ) -> str:
        """Create prompt for patient risk score calculation"""
        
        patient_age = self._calculate_age(patient_context.get('date_of_birth', ''))
        
        # Summarize visits
        visits_summary = ""
        if visits:
            visits_summary = f"\n**Visit History ({len(visits)} visits):**\n"
            for v in visits[:10]:  # Last 10 visits
                visits_summary += f"- {v.get('visit_date', 'N/A')}: {v.get('chief_complaint', 'N/A')} → {v.get('diagnosis', 'N/A')}\n"
        
        # Summarize analyses findings
        analyses_summary = ""
        if analyses:
            analyses_summary = "\n**Key Findings from Reports:**\n"
            for a in analyses[:5]:
                structured = a.get('structured_data', {})
                findings = structured.get('findings', [])
                critical = structured.get('critical_findings', [])
                if critical:
                    for cf in critical[:2]:
                        analyses_summary += f"- ⚠️ {cf.get('finding', 'Critical finding')}\n"
                for f in findings[:3]:
                    if f.get('status') in ['high', 'low', 'critical_high', 'critical_low']:
                        analyses_summary += f"- {f.get('parameter', 'Unknown')}: {f.get('value', '')} ({f.get('status', '')})\n"
        
        prompt = f"""
Analyze this patient's complete medical data and calculate comprehensive risk scores.

**PATIENT DEMOGRAPHICS:**
- Age: {patient_age}
- Gender: {patient_context.get('gender', 'Not specified')}
- Blood Group: {patient_context.get('blood_group', 'Not specified')}
- Known Allergies: {patient_context.get('allergies', 'None')}
- Medical History: {patient_context.get('medical_history', 'None documented')}

{visits_summary}
{analyses_summary}

**RISK ASSESSMENT INSTRUCTIONS:**

Based on all available data, calculate the following risk scores (0-100, where 100 is highest risk):

1. **Overall Health Risk Score**: Combined assessment of all risk factors
2. **Cardiovascular Risk**: Based on BP, lipids, age, lifestyle factors
3. **Diabetes Risk**: Based on glucose levels, BMI, family history
4. **Kidney Risk**: Based on creatinine, eGFR, urinalysis findings
5. **Liver Risk**: Based on LFTs, lifestyle factors

Also identify:
- **Risk Factors**: Conditions or findings that increase health risk
- **Protective Factors**: Positive health indicators
- **Recommendations**: Actionable steps to reduce risk

Use established medical risk frameworks (Framingham, ASCVD, etc.) as reference.
Consider patient's age, gender, and medical history in all assessments.
"""
        return prompt
    
    async def analyze_with_historical_trends(
        self,
        file_content: bytes,
        file_name: str,
        file_type: str,
        patient_context: Dict[str, Any],
        visit_context: Dict[str, Any],
        doctor_context: Dict[str, Any],
        historical_values: Dict[str, List[Dict[str, Any]]],
        visit_chain_context: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Analyze document with historical trend data for better clinical context.
        
        Phase 2.2: Historical Trend Analysis
        
        Args:
            file_content: Document content
            file_name: Name of file
            file_type: MIME type
            patient_context: Patient information
            visit_context: Current visit
            doctor_context: Doctor information
            historical_values: Dict of parameter -> list of historical values
            visit_chain_context: Linked visit history
            
        Returns:
            Analysis with trend comparison
        """
        try:
            logger.info(f"Analyzing {file_name} with historical trends")
            
            # Prepare document
            document_data = await self._prepare_document(file_content, file_name, file_type)
            if not document_data:
                return {"success": False, "error": "Unable to process document format"}
            
            # Create enhanced prompt with historical data
            prompt = self._create_analysis_prompt_with_trends(
                patient_context, visit_context, doctor_context,
                file_name, historical_values, visit_chain_context
            )
            
            # Perform analysis
            analysis_result = await self._perform_gemini_analysis(prompt, document_data)
            
            if "error" in analysis_result:
                return {"success": False, "error": analysis_result["error"]}
            
            return {
                "success": True,
                "analysis": analysis_result,
                "historical_context_used": bool(historical_values),
                "parameters_with_history": list(historical_values.keys()) if historical_values else [],
                "processed_at": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error in trend analysis: {e}")
            return {"success": False, "error": str(e)}
    
    def _create_analysis_prompt_with_trends(
        self,
        patient_context: Dict[str, Any],
        visit_context: Dict[str, Any],
        doctor_context: Dict[str, Any],
        file_name: str,
        historical_values: Dict[str, List[Dict[str, Any]]],
        visit_chain_context: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Create analysis prompt enhanced with historical trend data"""
        
        # Start with base prompt
        base_prompt = self._create_analysis_prompt(
            patient_context, visit_context, doctor_context,
            file_name, visit_chain_context
        )
        
        # Build trend section
        trend_section = ""
        if historical_values:
            trend_section = """
═══════════════════════════════════════════════════════════════
**📊 HISTORICAL VALUES FOR TREND ANALYSIS:**
═══════════════════════════════════════════════════════════════
Compare current results with these previous values:

"""
            for parameter, history in historical_values.items():
                trend_section += f"**{parameter}:**\n"
                for entry in history[-5:]:  # Last 5 values
                    date = entry.get('test_date', entry.get('recorded_at', 'Unknown'))
                    value = entry.get('value', entry.get('parameter_value', 'N/A'))
                    status = entry.get('status', '')
                    status_str = f" [{status}]" if status else ""
                    trend_section += f"  - {date}: {value}{status_str}\n"
                trend_section += "\n"
            
            trend_section += """
⚠️ **TREND ANALYSIS INSTRUCTIONS:**
1. Calculate the trend direction for each parameter (improving/worsening/stable)
2. Calculate rate of change if concerning
3. Flag any values crossing from normal to abnormal
4. Note if trends indicate treatment effectiveness or failure
5. Predict trajectory if current trend continues
6. Compare current values directly with historical ranges
7. Identify any sudden changes that need attention

Include a dedicated "TREND ANALYSIS" section in your response.
═══════════════════════════════════════════════════════════════

"""
        
        # Insert trend section after patient info
        if "CURRENT VISIT CONTEXT" in base_prompt:
            base_prompt = base_prompt.replace(
                "**CURRENT VISIT CONTEXT",
                f"{trend_section}**CURRENT VISIT CONTEXT"
            )
        else:
            base_prompt = trend_section + base_prompt
        
        return base_prompt

    # ============================================================================
    # CASE/EPISODE OF CARE ANALYSIS METHODS
    # ============================================================================

    async def analyze_case(
        self,
        case_data: Dict[str, Any],
        visits: List[Dict[str, Any]],
        photos: List[Dict[str, Any]],
        reports: List[Dict[str, Any]],
        patient_context: Dict[str, Any],
        doctor_context: Dict[str, Any],
        analysis_type: str = "comprehensive"
    ) -> Dict[str, Any]:
        """
        Analyze a complete case/episode of care across multiple visits.
        
        Args:
            case_data: Case information (title, type, chief complaint, etc.)
            visits: List of visits associated with the case
            photos: List of case photos (before, progress, after)
            reports: List of reports/documents associated with case visits
            patient_context: Patient information
            doctor_context: Doctor information
            analysis_type: Type of analysis (comprehensive, progress_review, outcome_assessment)
        
        Returns:
            Dict containing case analysis results
        """
        try:
            print(f"Starting case analysis for case: {case_data.get('case_title', 'Unknown')}")
            
            # Import the schema
            from ai_schemas import CASE_ANALYSIS_SCHEMA
            
            # Build the case analysis prompt
            prompt = self._create_case_analysis_prompt(
                case_data=case_data,
                visits=visits,
                photos=photos,
                reports=reports,
                patient_context=patient_context,
                doctor_context=doctor_context,
                analysis_type=analysis_type
            )
            
            # Prepare photo content if available
            photo_contents = []
            for photo in photos:
                if photo.get("file_url"):
                    try:
                        photo_data = await self._fetch_image_from_url(photo["file_url"])
                        if photo_data:
                            photo_contents.append({
                                "type": photo.get("photo_type", "unknown"),
                                "data": photo_data,
                                "description": photo.get("description", "")
                            })
                    except Exception as e:
                        print(f"Warning: Could not fetch photo: {e}")
            
            # Build content parts
            content_parts = [types.Part.from_text(text=prompt)]
            
            # Add photos to content
            for photo in photo_contents:
                content_parts.append(types.Part.from_bytes(
                    data=photo["data"],
                    mime_type="image/jpeg"
                ))
            
            # Create generation config with JSON schema
            generation_config = types.GenerateContentConfig(
                temperature=0.3,
                top_p=0.95,
                max_output_tokens=8192,
                response_mime_type="application/json",
                response_schema=CASE_ANALYSIS_SCHEMA
            )
            
            # Generate analysis
            response = await asyncio.get_event_loop().run_in_executor(
                self.executor,
                lambda: self.client.models.generate_content(
                    model=f"publishers/google/models/{self.model_name}",
                    contents=[types.Content(role="user", parts=content_parts)],
                    config=generation_config
                )
            )
            
            if not response or not response.text:
                return {
                    "success": False,
                    "error": "No response from AI model",
                    "analysis": None
                }
            
            # Store raw JSON response
            raw_json_response = response.text
            
            # Parse JSON response
            try:
                analysis_result = json.loads(response.text)
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "error": "Failed to parse AI response",
                    "raw_analysis": raw_json_response,  # Store raw even if parsing fails
                    "analysis": None
                }
            
            # Return simplified structure - all fields are in structured_data
            return {
                "success": True,
                "raw_analysis": raw_json_response,  # Raw JSON string for raw_analysis column
                "structured_data": analysis_result,  # Parsed JSON for structured_data JSONB column
                "analysis_type": analysis_type,
                "model_used": self.model_name,
                "visits_analyzed": [v.get("id") for v in visits],
                "reports_analyzed": [r.get("id") for r in reports],
                "photos_analyzed": [p.get("id") for p in photos],
                "analysis_success": True
            }
            
        except Exception as e:
            print(f"Error in case analysis: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "analysis": None,
                "analysis_success": False,
                "analysis_error": str(e)
            }

    async def analyze_photos_comparison(
        self,
        before_photo_url: str,
        after_photo_url: str,
        case_context: Dict[str, Any],
        patient_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze before and after photos for visual progress assessment.
        
        Args:
            before_photo_url: URL of the before photo
            after_photo_url: URL of the after photo
            case_context: Case information for context
            patient_context: Patient information
        
        Returns:
            Dict containing photo comparison analysis
        """
        try:
            print("Starting photo comparison analysis")
            
            from ai_schemas import PHOTO_COMPARISON_SCHEMA
            
            # Fetch both photos
            before_data = await self._fetch_image_from_url(before_photo_url)
            after_data = await self._fetch_image_from_url(after_photo_url)
            
            if not before_data or not after_data:
                return {
                    "success": False,
                    "error": "Could not fetch one or both photos",
                    "analysis": None
                }
            
            # Build comparison prompt
            prompt = self._create_photo_comparison_prompt(case_context, patient_context)
            
            # Build content parts
            content_parts = [
                types.Part.from_text(text=prompt),
                types.Part.from_text(text="BEFORE PHOTO:"),
                types.Part.from_bytes(data=before_data, mime_type="image/jpeg"),
                types.Part.from_text(text="AFTER PHOTO:"),
                types.Part.from_bytes(data=after_data, mime_type="image/jpeg")
            ]
            
            # Create generation config
            generation_config = types.GenerateContentConfig(
                temperature=0.3,
                top_p=0.95,
                max_output_tokens=4096,
                response_mime_type="application/json",
                response_schema=PHOTO_COMPARISON_SCHEMA
            )
            
            # Generate analysis
            response = await asyncio.get_event_loop().run_in_executor(
                self.executor,
                lambda: self.client.models.generate_content(
                    model=f"publishers/google/models/{self.model_name}",
                    contents=[types.Content(role="user", parts=content_parts)],
                    config=generation_config
                )
            )
            
            if not response or not response.text:
                return {
                    "success": False,
                    "error": "No response from AI model",
                    "analysis": None
                }
            
            try:
                analysis_result = json.loads(response.text)
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "error": "Failed to parse AI response",
                    "analysis": None
                }
            
            return {
                "success": True,
                "model_used": self.model_name,
                "analysis": analysis_result,
                "visual_improvement_score": analysis_result.get("visual_improvement_score"),
                "overall_change": analysis_result.get("comparison_summary", {}).get("overall_change"),
                "confidence_score": analysis_result.get("confidence_score")
            }
            
        except Exception as e:
            print(f"Error in photo comparison analysis: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "analysis": None
            }

    def _create_case_analysis_prompt(
        self,
        case_data: Dict[str, Any],
        visits: List[Dict[str, Any]],
        photos: List[Dict[str, Any]],
        reports: List[Dict[str, Any]],
        patient_context: Dict[str, Any],
        doctor_context: Dict[str, Any],
        analysis_type: str
    ) -> str:
        """Create the prompt for case analysis"""
        
        # Sort visits by date
        sorted_visits = sorted(visits, key=lambda x: x.get("visit_date", ""))
        
        prompt = f"""
═══════════════════════════════════════════════════════════════════════════════
                    CASE/EPISODE OF CARE ANALYSIS
═══════════════════════════════════════════════════════════════════════════════

You are an experienced medical professional analyzing a complete case/episode of care.
Analyze the treatment progress and provide comprehensive insights.

═══════════════════════════════════════════════════════════════════════════════
**CASE INFORMATION:**
═══════════════════════════════════════════════════════════════════════════════
Case Title: {case_data.get('case_title', 'Unknown')}
Case Type: {case_data.get('case_type', 'Unknown')}
Chief Complaint: {case_data.get('chief_complaint', 'Not specified')}
Initial Diagnosis: {case_data.get('initial_diagnosis', 'Not specified')}
Current Status: {case_data.get('status', 'Unknown')}
Severity: {case_data.get('severity', 'Unknown')}
Started: {case_data.get('started_at', 'Unknown')}
Body Parts Affected: {', '.join(case_data.get('body_parts_affected', [])) or 'Not specified'}

═══════════════════════════════════════════════════════════════════════════════
**PATIENT INFORMATION:**
═══════════════════════════════════════════════════════════════════════════════
Name: {patient_context.get('full_name', 'Unknown')}
Age: {patient_context.get('age', 'Unknown')} years
Gender: {patient_context.get('gender', 'Unknown')}
Blood Group: {patient_context.get('blood_group', 'Unknown')}
Known Allergies: {patient_context.get('allergies', 'None known')}
Chronic Conditions: {patient_context.get('chronic_conditions', 'None known')}
Current Medications: {patient_context.get('current_medications', 'None')}

═══════════════════════════════════════════════════════════════════════════════
**VISIT HISTORY ({len(sorted_visits)} visits):**
═══════════════════════════════════════════════════════════════════════════════
"""
        
        for i, visit in enumerate(sorted_visits, 1):
            prompt += f"""
--- Visit #{i} ({visit.get('visit_date', 'Unknown date')}) ---
Type: {visit.get('visit_type', 'Unknown')}
Chief Complaint: {visit.get('chief_complaint', 'Not recorded')}
Symptoms: {visit.get('symptoms', 'Not recorded')}
Clinical Examination: {visit.get('clinical_examination', 'Not recorded')}
Diagnosis: {visit.get('diagnosis', 'Not recorded')}
Treatment Plan: {visit.get('treatment_plan', 'Not recorded')}
Medications: {visit.get('medications', 'Not recorded')}
Notes: {visit.get('notes', 'None')}
"""
        
        # Add photo information if available
        if photos:
            before_photos = [p for p in photos if p.get('photo_type') == 'before']
            progress_photos = [p for p in photos if p.get('photo_type') == 'progress']
            after_photos = [p for p in photos if p.get('photo_type') == 'after']
            
            prompt += f"""
═══════════════════════════════════════════════════════════════════════════════
**PHOTO DOCUMENTATION:**
═══════════════════════════════════════════════════════════════════════════════
Before Photos: {len(before_photos)}
Progress Photos: {len(progress_photos)}
After Photos: {len(after_photos)}

Please analyze any provided photos and compare the visual changes.
"""
        
        # Add analysis instructions based on type
        prompt += f"""
═══════════════════════════════════════════════════════════════════════════════
**ANALYSIS TYPE: {analysis_type.upper()}**
═══════════════════════════════════════════════════════════════════════════════

Please provide a comprehensive analysis including:

1. **Case Overview**: Summary of the entire case journey
2. **Treatment Effectiveness**: How effective has the treatment been?
3. **Progress Assessment**: Overall progress from first to latest visit
4. **Visual Progress** (if photos provided): Compare before/after photos
5. **Red Flags**: Any concerns or warning signs
6. **Recommendations**: Next steps and follow-up recommendations
7. **Patient-Friendly Summary**: Simple explanation for the patient

Be thorough but concise. Focus on actionable insights.
═══════════════════════════════════════════════════════════════════════════════
"""
        
        return prompt

    def _create_photo_comparison_prompt(
        self,
        case_context: Dict[str, Any],
        patient_context: Dict[str, Any]
    ) -> str:
        """Create prompt for photo comparison analysis"""
        
        return f"""
═══════════════════════════════════════════════════════════════════════════════
                    MEDICAL PHOTO COMPARISON ANALYSIS
═══════════════════════════════════════════════════════════════════════════════

You are analyzing before and after medical photos to assess treatment progress.

**CASE CONTEXT:**
Condition: {case_context.get('case_title', 'Unknown')}
Chief Complaint: {case_context.get('chief_complaint', 'Unknown')}
Diagnosis: {case_context.get('initial_diagnosis') or case_context.get('final_diagnosis', 'Unknown')}
Body Part: {', '.join(case_context.get('body_parts_affected', [])) or 'Unknown'}

**PATIENT:**
Age: {patient_context.get('age', 'Unknown')} years
Gender: {patient_context.get('gender', 'Unknown')}

**INSTRUCTIONS:**
1. Carefully analyze the BEFORE photo first
2. Then analyze the AFTER photo
3. Compare the two and identify all visible changes
4. Assess the degree of improvement or deterioration
5. Provide a visual improvement score (0-100)
   - 0 = Significantly worse
   - 50 = No change
   - 100 = Complete resolution
6. Give clinical recommendations based on visual progress
7. Provide a patient-friendly explanation

Be objective and thorough in your assessment.
═══════════════════════════════════════════════════════════════════════════════
"""

    async def _fetch_image_from_url(self, url: str) -> Optional[bytes]:
        """Fetch image content from URL"""
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                self.executor,
                lambda: requests.get(url, timeout=30)
            )
            if response.status_code == 200:
                return response.content
            return None
        except Exception as e:
            print(f"Error fetching image from URL: {e}")
            return None

    def __del__(self):
        """Cleanup thread pool executor"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
