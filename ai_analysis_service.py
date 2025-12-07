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
                link_reason = prev_visit.get('link_reason', 'Follow-up')
                
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
  **Previous Visit #{i} ({link_reason}):**
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
    
    async def _perform_gemini_analysis(
        self, 
        prompt: str, 
        document_data: Dict[str, Any],
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Perform the actual AI analysis using Gemini 3 Pro with retry logic for rate limits"""
        
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
                def generate_sync():
                    return self.client.models.generate_content(
                        model=self.model_name,
                        contents=content_parts,
                        config=types.GenerateContentConfig(
                            thinking_config=types.ThinkingConfig(
                                thinking_level=types.ThinkingLevel.LOW  # Fast, low-latency for document analysis
                            )
                        )
                    )
                
                response = await loop.run_in_executor(
                    self.executor,
                    generate_sync
                )
                
                if response and response.text:
                    analysis_text = response.text
                    
                    # Parse the structured response
                    parsed_analysis = self._parse_analysis_response(analysis_text)
                    
                    return {
                        "raw_analysis": analysis_text,
                        "structured_analysis": parsed_analysis,
                        "confidence_score": self._calculate_confidence(analysis_text),
                        "analysis_length": len(analysis_text),
                        "key_findings": self._extract_key_findings(parsed_analysis)
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
                        print(f"⚠️ Rate limit hit. Retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        print(f"❌ Rate limit exceeded after {max_retries} attempts")
                        return {
                            "error": "Rate limit exceeded. Please try again later.",
                            "raw_analysis": "",
                            "structured_analysis": {},
                            "confidence_score": 0.0,
                            "key_findings": []
                        }
                else:
                    # Other errors - don't retry
                    print(f"Error in Gemini 3 Pro analysis: {e}")
                    print(f"Traceback: {traceback.format_exc()}")
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
    
    def _parse_analysis_response(self, analysis_text: str) -> Dict[str, Any]:
        """Parse the structured analysis response from Gemini"""
        try:
            sections = {
                "document_summary": "",
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
            
            # Simple parsing based on section headers
            current_section = None
            lines = analysis_text.split('\n')
            
            for line in lines:
                line = line.strip()
                
                # Check for section headers (enhanced to match new format)
                if "DOCUMENT IDENTIFICATION" in line.upper() or "DOCUMENT SUMMARY" in line.upper():
                    current_section = "document_summary"
                elif "CLINICAL CORRELATION WITH VISIT" in line.upper() or "CORRELATION WITH VISIT" in line.upper():
                    current_section = "clinical_correlation"
                elif "DETAILED FINDINGS" in line.upper():
                    current_section = "detailed_findings"
                elif "CRITICAL" in line.upper() and "URGENT" in line.upper():
                    current_section = "critical_findings"
                elif "TREATMENT PLAN EVALUATION" in line.upper():
                    current_section = "treatment_evaluation"
                elif "CLINICAL SIGNIFICANCE" in line.upper():
                    current_section = "clinical_significance"
                elif "CORRELATION WITH PATIENT" in line.upper():
                    current_section = "correlation_with_patient"
                elif "ACTIONABLE" in line.upper() or "NEXT STEPS" in line.upper():
                    current_section = "actionable_insights"
                elif "PATIENT COMMUNICATION" in line.upper():
                    current_section = "patient_communication"
                elif "CLINICAL" in line.upper() and ("NOTES" in line.upper() or "DOCUMENTATION" in line.upper()):
                    current_section = "clinical_notes"
                elif line and current_section and not line.startswith('**') and not line.startswith('⚠️') and not line.startswith('🚨'):
                    # Add content to current section (skip emoji markers)
                    clean_line = line.lstrip('✓-•*')
                    if clean_line:
                        if sections[current_section]:
                            sections[current_section] += " " + clean_line
                        else:
                            sections[current_section] = clean_line
            
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
            
            # Generate consolidated insights using Gemini 3 Pro
            loop = asyncio.get_event_loop()
            
            def generate_consolidated():
                return self.client.models.generate_content(
                    model=self.model_name,
                    contents=consolidated_prompt,
                    config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.HIGH  # High reasoning for consolidated analysis
                        )
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
        analysis_period_months: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Perform comprehensive analysis of patient's complete medical history
        
        Args:
            patient_context: Patient information and demographics
            visits: List of all patient visits
            reports: List of all medical reports/documents
            existing_analyses: Previous AI analyses for this patient
            doctor_context: Doctor information
            analysis_period_months: Optional time period limit
        
        Returns:
            Dict containing comprehensive analysis results
        """
        try:
            print(f"Starting comprehensive history analysis for patient {patient_context.get('id')}")
            
            # Prepare comprehensive prompt
            prompt = self._create_comprehensive_history_prompt(
                patient_context,
                visits,
                reports,
                existing_analyses,
                doctor_context,
                analysis_period_months
            )
            
            # Perform analysis using Gemini 3 Pro with HIGH thinking for complex reasoning
            loop = asyncio.get_event_loop()
            
            def generate_comprehensive():
                return self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.HIGH  # High reasoning for comprehensive history analysis
                        )
                    )
                )
            
            response = await loop.run_in_executor(
                self.executor,
                generate_comprehensive
            )
            
            if response and response.text:
                analysis_text = response.text
            else:
                return {
                    "success": False,
                    "error": "No response from AI model"
                }
            
            if not analysis_text:
                return {
                    "success": False,
                    "error": "Failed to generate analysis text"
                }
            
            # Parse and structure the analysis
            structured_analysis = self._parse_comprehensive_analysis(analysis_text)
            
            return {
                "success": True,
                "comprehensive_analysis": analysis_text,
                "confidence_score": 0.85,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                **structured_analysis
            }
            
        except Exception as e:
            print(f"Error in comprehensive history analysis: {e}")
            print(f"Traceback: {traceback.format_exc()}")
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
        analysis_period_months: Optional[int] = None
    ) -> str:
        """Create a comprehensive prompt for patient history analysis"""
        
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
        
        # Prepare visits summary
        visits_summary = ""
        if visits:
            visits_summary = f"\n**MEDICAL VISITS ({len(visits)} total):**\n"
            for i, visit in enumerate(visits[:10], 1):  # Limit to 10 most recent
                visit_date = visit.get('visit_date', 'Unknown date')
                visit_type = visit.get('visit_type', 'General')
                chief_complaint = visit.get('chief_complaint', 'Not specified')
                diagnosis = visit.get('diagnosis', 'Not specified')
                treatment = visit.get('treatment_plan', 'Not specified')
                medications = visit.get('medications', 'None prescribed')
                
                visits_summary += f"""
{i}. **{visit_date} - {visit_type}**
   - Chief Complaint: {chief_complaint}
   - Diagnosis: {diagnosis}
   - Treatment: {treatment}
   - Medications: {medications}"""
            
            if len(visits) > 10:
                visits_summary += f"\n... and {len(visits) - 10} more visits"
        
        # Prepare reports summary
        reports_summary = ""
        if reports:
            reports_summary = f"\n**MEDICAL REPORTS/TESTS ({len(reports)} total):**\n"
            for i, report in enumerate(reports[:10], 1):  # Limit to 10 most recent
                file_name = report.get('file_name', 'Unknown file')
                test_type = report.get('test_type', 'General Report')
                uploaded_date = report.get('uploaded_at', 'Unknown date')
                
                reports_summary += f"\n{i}. **{file_name}** ({test_type}) - {uploaded_date}"
            
            if len(reports) > 10:
                reports_summary += f"\n... and {len(reports) - 10} more reports"
        
        # Prepare existing analyses summary
        analyses_summary = ""
        if existing_analyses:
            analyses_summary = f"\n**PREVIOUS AI ANALYSES ({len(existing_analyses)} total):**\n"
            for i, analysis in enumerate(existing_analyses[:5], 1):  # Limit to 5 most recent
                analyzed_date = analysis.get('analyzed_at', 'Unknown date')
                clinical_significance = analysis.get('clinical_significance', 'Not available')
                key_findings = analysis.get('key_findings', [])
                
                analyses_summary += f"""
{i}. **Analysis from {analyzed_date}**
   - Clinical Significance: {clinical_significance[:200]}...
   - Key Findings: {', '.join(key_findings[:3]) if key_findings else 'None specified'}"""
        
        prompt = f"""
You are an advanced AI medical assistant helping {doctor_name} ({doctor_specialization}) analyze the complete medical history of {patient_name} ({patient_age}){period_text}.

**PATIENT DEMOGRAPHICS:**
- Name: {patient_name}
- Age: {patient_age}
- Gender: {patient_context.get('gender', 'Not specified')}
- Blood Group: {patient_context.get('blood_group', 'Not specified')}
- Known Allergies: {patient_context.get('allergies', 'None reported')}
- Medical History: {patient_context.get('medical_history', 'None provided')}
- Emergency Contact: {patient_context.get('emergency_contact_name', 'Not provided')}

{visits_summary}

{reports_summary}

{analyses_summary}

**COMPREHENSIVE ANALYSIS REQUEST:**

Please provide a thorough, professional analysis covering:

1. **COMPREHENSIVE MEDICAL SUMMARY:**
   - Overall health trajectory and patterns
   - Significant medical events and milestones
   - Evolution of health conditions over time

2. **MEDICAL TRAJECTORY ANALYSIS:**
   - How the patient's health has changed over time
   - Progression of any chronic conditions
   - Response to previous treatments

3. **CHRONIC CONDITIONS & PATTERNS:**
   - Identify any chronic or recurring conditions
   - Patterns in symptoms or health issues
   - Seasonal or cyclical patterns

4. **TREATMENT EFFECTIVENESS:**
   - Analysis of how well treatments have worked
   - Medication compliance and effectiveness
   - Treatment modifications over time

5. **RISK FACTORS IDENTIFICATION:**
   - Current and emerging health risks
   - Lifestyle factors affecting health
   - Genetic or hereditary concerns

6. **SIGNIFICANT CLINICAL FINDINGS:**
   - Most important test results and findings
   - Abnormal values requiring attention
   - Trends in laboratory values

7. **COMPREHENSIVE RECOMMENDATIONS:**
   - Preventive care recommendations
   - Lifestyle modifications
   - Follow-up care planning
   - Screening recommendations

8. **LIFESTYLE & MEDICATION HISTORY:**
   - Impact of lifestyle factors on health
   - Medication history and interactions
   - Side effects or adverse reactions

9. **FOLLOW-UP SUGGESTIONS:**
   - Recommended monitoring schedule
   - Specialist referrals if needed
   - Future diagnostic tests

This analysis will help Dr. {doctor_name} provide comprehensive, informed care for {patient_name}, especially if they're returning after a long time. Focus on clinically relevant insights that will enhance patient care and decision-making.

Please structure your response clearly with appropriate medical terminology while ensuring it's comprehensive and actionable.
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
                link_reason = prev_visit.get('link_reason', 'Follow-up')
                
                # Include previous handwritten notes summary if available
                prev_notes = ""
                if prev_visit.get('handwritten_summary'):
                    prev_notes = f"\\n    - Previous Handwritten Notes Summary: {prev_visit.get('handwritten_summary', '')[:200]}"
                
                visit_chain_section += f"""
  **Previous Visit #{i} ({link_reason}):**
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
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Perform AI analysis on handwritten prescription using Gemini 3 Pro multimodal"""
        
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
                def generate_sync():
                    return self.client.models.generate_content(
                        model=self.model_name,
                        contents=content_parts,
                        config=types.GenerateContentConfig(
                            thinking_config=types.ThinkingConfig(
                                thinking_level=types.ThinkingLevel.HIGH  # High reasoning for handwriting interpretation
                            )
                        )
                    )
                
                response = await loop.run_in_executor(
                    self.executor,
                    generate_sync
                )
                
                if response and response.text:
                    analysis_text = response.text
                    
                    # Parse the structured response for handwritten prescriptions
                    parsed_analysis = self._parse_handwritten_analysis_response(analysis_text)
                    
                    return {
                        "raw_analysis": analysis_text,
                        "structured_analysis": parsed_analysis,
                        "confidence_score": self._calculate_handwriting_confidence(analysis_text),
                        "analysis_length": len(analysis_text),
                        "extracted_medications": parsed_analysis.get("medications", []),
                        "extracted_diagnosis": parsed_analysis.get("diagnosis", ""),
                        "legibility_score": parsed_analysis.get("legibility_score", 7)
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
                        print(f"⚠️ Rate limit hit. Retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        print(f"❌ Rate limit exceeded after {max_retries} attempts")
                        return {
                            "error": "Rate limit exceeded. Please try again later.",
                            "raw_analysis": "",
                            "structured_analysis": {},
                            "confidence_score": 0.0
                        }
                else:
                    print(f"❌ Error in handwritten analysis: {e}")
                    print(f"Traceback: {traceback.format_exc()}")
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
    
    def __del__(self):
        """Cleanup thread pool executor"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
