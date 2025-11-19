from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from datetime import datetime, date
import io
import os
import asyncio
import tempfile
import fitz  # PyMuPDF for PDF manipulation
from typing import Dict, Any, List, Optional
import requests
from supabase import Client
from async_file_downloader import file_downloader

class VisitReportGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.setup_custom_styles()
        self.file_downloader = file_downloader  # Use global async downloader
    
    def setup_custom_styles(self):
        """Setup custom styles for the PDF"""
        self.styles.add(ParagraphStyle(
            name='ClinicHeader',
            parent=self.styles['Heading1'],
            fontSize=20,
            spaceAfter=6,
            spaceBefore=12,
            textColor=colors.darkblue,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))
        
        self.styles.add(ParagraphStyle(
            name='DoctorName',
            parent=self.styles['Heading2'],
            fontSize=16,
            spaceAfter=4,
            textColor=colors.darkblue,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))
        
        self.styles.add(ParagraphStyle(
            name='VisitTitle',
            parent=self.styles['Heading2'],
            fontSize=18,
            spaceAfter=12,
            spaceBefore=20,
            textColor=colors.darkred,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))
        
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading3'],
            fontSize=14,
            spaceAfter=8,
            spaceBefore=16,
            textColor=colors.darkblue,
            fontName='Helvetica-Bold',
            borderWidth=1,
            borderColor=colors.darkblue,
            borderPadding=5,
            backColor=colors.lightgrey
        ))
        
        self.styles.add(ParagraphStyle(
            name='FieldLabel',
            parent=self.styles['Normal'],
            fontSize=11,
            textColor=colors.black,
            fontName='Helvetica-Bold',
            spaceAfter=2
        ))
        
        self.styles.add(ParagraphStyle(
            name='FieldValue',
            parent=self.styles['Normal'],
            fontSize=11,
            spaceAfter=6,
            leftIndent=20
        ))
        
        self.styles.add(ParagraphStyle(
            name='TableHeader',
            parent=self.styles['Normal'],
            fontSize=12,
            textColor=colors.white,
            fontName='Helvetica-Bold',
            alignment=TA_CENTER
        ))
        
        self.styles.add(ParagraphStyle(
            name='Footer',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=colors.grey,
            alignment=TA_CENTER,
            spaceAfter=6
        ))

    def _safe(self, value: Any, default: str = "Not specified") -> str:
        """Safely convert value to string with default"""
        if value is None or value == "":
            return default
        return str(value)

    def _format_date(self, date_str: str) -> str:
        """Format date string for display"""
        try:
            if date_str:
                # Handle different date formats
                for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"]:
                    try:
                        dt = datetime.strptime(date_str[:len(fmt)], fmt)
                        return dt.strftime("%B %d, %Y")
                    except ValueError:
                        continue
            return "Not specified"
        except Exception:
            return self._safe(date_str)

    def _format_time(self, time_str: str) -> str:
        """Format time string for display"""
        try:
            if time_str:
                # Handle HH:MM format
                time_obj = datetime.strptime(time_str, "%H:%M").time()
                return time_obj.strftime("%I:%M %p")
            return "Not specified"
        except Exception:
            return self._safe(time_str)

    def _format_currency(self, amount: float) -> str:
        """Format currency amount"""
        try:
            if amount is not None:
                return f"₹{amount:,.2f}"
            return "₹0.00"
        except Exception:
            return "₹0.00"

    def _format_vitals(self, vitals: Dict[str, Any]) -> List[List[str]]:
        """Format vitals data for table display"""
        if not vitals:
            return [["No vital signs recorded", ""]]
        
        vital_data = []
        
        # Temperature
        if vitals.get("temperature"):
            vital_data.append(["Temperature", f"{vitals['temperature']}°C"])
        
        # Blood Pressure
        if vitals.get("blood_pressure_systolic") and vitals.get("blood_pressure_diastolic"):
            bp = f"{vitals['blood_pressure_systolic']}/{vitals['blood_pressure_diastolic']} mmHg"
            vital_data.append(["Blood Pressure", bp])
        
        # Heart Rate
        if vitals.get("heart_rate"):
            vital_data.append(["Heart Rate", f"{vitals['heart_rate']} BPM"])
        
        # Respiratory Rate
        if vitals.get("respiratory_rate"):
            vital_data.append(["Respiratory Rate", f"{vitals['respiratory_rate']} /min"])
        
        # Oxygen Saturation
        if vitals.get("oxygen_saturation"):
            vital_data.append(["Oxygen Saturation", f"{vitals['oxygen_saturation']}%"])
        
        # Weight
        if vitals.get("weight"):
            vital_data.append(["Weight", f"{vitals['weight']} kg"])
        
        # Height
        if vitals.get("height"):
            vital_data.append(["Height", f"{vitals['height']} cm"])
        
        # BMI
        if vitals.get("bmi"):
            vital_data.append(["BMI", f"{vitals['bmi']}"])
        
        return vital_data if vital_data else [["No vital signs recorded", ""]]

    async def download_template_file(self, template_url: str) -> bytes:
        """Download template PDF from URL using async non-blocking download"""
        try:
            # Use the async file downloader to prevent blocking
            file_content = await self.file_downloader.download_file(
                url=template_url,
                stream=True  # Use streaming for PDF templates
            )
            
            if file_content:
                return file_content
            else:
                raise Exception(f"Failed to download template from {template_url}")
                
        except Exception as e:
            print(f"❌ Error downloading template: {e}")
            raise Exception(f"Failed to download template: {str(e)}")

    def overlay_text_on_pdf(self, template_bytes: bytes, overlay_data: Dict[str, Any]) -> bytes:
        """Overlay visit information on template PDF using PyMuPDF"""
        try:
            # Load the template PDF
            template_doc = fitz.open(stream=template_bytes, filetype="pdf")
            
            # Create overlay content for the first page
            page = template_doc[0]
            
            # Define positions for different fields (you may need to adjust these)
            # These are example positions - in a real implementation, you'd want these to be configurable
            field_positions = {
                "patient_name": (100, 100),
                "visit_date": (100, 130),
                "doctor_name": (100, 160),
                "chief_complaint": (100, 200),
                "diagnosis": (100, 240),
                "medications": (100, 280),
                "treatment_plan": (100, 320),
                "follow_up": (100, 360)
            }
            
            # Add text overlays
            font_size = 12
            for field, (x, y) in field_positions.items():
                if field in overlay_data and overlay_data[field]:
                    # Insert text at specified position
                    page.insert_text(
                        (x, y),
                        overlay_data[field],
                        fontsize=font_size,
                        color=(0, 0, 0)  # Black color
                    )
            
            # Save the modified PDF
            output_bytes = template_doc.write()
            template_doc.close()
            
            return output_bytes
            
        except Exception as e:
            print(f"Error overlaying text on PDF template: {e}")
            # If overlay fails, return the original template
            return template_bytes

    def create_default_visit_report(self, visit: Dict[str, Any], patient: Dict[str, Any], 
                                  doctor: Dict[str, Any]) -> bytes:
        """Create a default visit report when no template is provided"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, 
                              topMargin=72, bottomMargin=72)
        
        story = []
        
        # Clinic Header
        clinic_name = f"Dr. {doctor['first_name']} {doctor['last_name']}'s Clinic"
        story.append(Paragraph(clinic_name, self.styles['ClinicHeader']))
        
        if doctor.get('specialization'):
            story.append(Paragraph(f"Specialization: {doctor['specialization']}", self.styles['DoctorName']))
        
        if doctor.get('phone'):
            story.append(Paragraph(f"Phone: {doctor['phone']}", self.styles['Normal']))
        
        story.append(Spacer(1, 20))
        
        # Visit Title
        story.append(Paragraph("MEDICAL VISIT REPORT", self.styles['VisitTitle']))
        story.append(Spacer(1, 20))
        
        # Patient Information Section
        story.append(Paragraph("PATIENT INFORMATION", self.styles['SectionHeader']))
        
        patient_data = [
            ['Patient Name:', f"{patient['first_name']} {patient['last_name']}"],
            ['Date of Birth:', self._format_date(patient.get('date_of_birth', ''))],
            ['Gender:', self._safe(patient.get('gender'))],
            ['Phone:', self._safe(patient.get('phone'))],
            ['Email:', self._safe(patient.get('email'))],
            ['Blood Group:', self._safe(patient.get('blood_group'))],
            ['Emergency Contact:', f"{self._safe(patient.get('emergency_contact_name'))} - {self._safe(patient.get('emergency_contact_phone'))}"]
        ]
        
        patient_table = Table(patient_data, colWidths=[2*inch, 4*inch])
        patient_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(patient_table)
        story.append(Spacer(1, 15))
        
        # Visit Details Section
        story.append(Paragraph("VISIT DETAILS", self.styles['SectionHeader']))
        
        visit_data = [
            ['Visit Date:', self._format_date(visit.get('visit_date', ''))],
            ['Visit Time:', self._format_time(visit.get('visit_time', ''))],
            ['Visit Type:', self._safe(visit.get('visit_type'))],
            ['Chief Complaint:', self._safe(visit.get('chief_complaint'))]
        ]
        
        visit_table = Table(visit_data, colWidths=[2*inch, 4*inch])
        visit_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(visit_table)
        story.append(Spacer(1, 15))
        
        # Vital Signs Section
        if visit.get('vitals'):
            story.append(Paragraph("VITAL SIGNS", self.styles['SectionHeader']))
            
            vitals_data = self._format_vitals(visit['vitals'])
            vitals_table = Table(vitals_data, colWidths=[2*inch, 4*inch])
            vitals_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 11),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ]))
            story.append(vitals_table)
            story.append(Spacer(1, 15))
        
        # Clinical Details Section
        story.append(Paragraph("CLINICAL EXAMINATION & FINDINGS", self.styles['SectionHeader']))
        
        clinical_details = []
        
        if visit.get('symptoms'):
            clinical_details.append(Paragraph(f"<b>Symptoms:</b> {visit['symptoms']}", self.styles['FieldValue']))
        
        if visit.get('clinical_examination'):
            clinical_details.append(Paragraph(f"<b>Clinical Examination:</b> {visit['clinical_examination']}", self.styles['FieldValue']))
        
        if visit.get('diagnosis'):
            clinical_details.append(Paragraph(f"<b>Diagnosis:</b> {visit['diagnosis']}", self.styles['FieldValue']))
        
        if not clinical_details:
            clinical_details.append(Paragraph("No clinical details recorded.", self.styles['FieldValue']))
        
        for detail in clinical_details:
            story.append(detail)
        
        story.append(Spacer(1, 15))
        
        # Treatment Section
        story.append(Paragraph("TREATMENT & RECOMMENDATIONS", self.styles['SectionHeader']))
        
        treatment_details = []
        
        if visit.get('treatment_plan'):
            treatment_details.append(Paragraph(f"<b>Treatment Plan:</b> {visit['treatment_plan']}", self.styles['FieldValue']))
        
        if visit.get('medications'):
            treatment_details.append(Paragraph(f"<b>Medications:</b> {visit['medications']}", self.styles['FieldValue']))
        
        if visit.get('tests_recommended'):
            treatment_details.append(Paragraph(f"<b>Tests Recommended:</b> {visit['tests_recommended']}", self.styles['FieldValue']))
        
        if visit.get('follow_up_date'):
            treatment_details.append(Paragraph(f"<b>Follow-up Date:</b> {self._format_date(visit['follow_up_date'])}", self.styles['FieldValue']))
        
        if not treatment_details:
            treatment_details.append(Paragraph("No treatment details recorded.", self.styles['FieldValue']))
        
        for detail in treatment_details:
            story.append(detail)
        
        story.append(Spacer(1, 15))
        
        # Billing Information (if available)
        if visit.get('total_amount') is not None:
            story.append(Paragraph("BILLING INFORMATION", self.styles['SectionHeader']))
            
            billing_data = []
            if visit.get('consultation_fee'):
                billing_data.append(['Consultation Fee:', self._format_currency(visit['consultation_fee'])])
            if visit.get('additional_charges'):
                billing_data.append(['Additional Charges:', self._format_currency(visit['additional_charges'])])
            if visit.get('discount'):
                billing_data.append(['Discount:', self._format_currency(visit['discount'])])
            if visit.get('total_amount') is not None:
                billing_data.append(['Total Amount:', self._format_currency(visit['total_amount'])])
            if visit.get('payment_status'):
                billing_data.append(['Payment Status:', visit['payment_status'].title()])
            
            if billing_data:
                billing_table = Table(billing_data, colWidths=[2*inch, 4*inch])
                billing_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 11),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ]))
                story.append(billing_table)
                story.append(Spacer(1, 15))
        
        # Notes Section
        if visit.get('notes'):
            story.append(Paragraph("ADDITIONAL NOTES", self.styles['SectionHeader']))
            story.append(Paragraph(visit['notes'], self.styles['FieldValue']))
            story.append(Spacer(1, 15))
        
        # Footer with doctor signature
        story.append(Spacer(1, 30))
        story.append(Paragraph("Doctor's Signature", self.styles['FieldLabel']))
        story.append(Spacer(1, 20))
        story.append(Paragraph(f"Dr. {doctor['first_name']} {doctor['last_name']}", self.styles['FieldValue']))
        
        if doctor.get('license_number'):
            story.append(Paragraph(f"License No: {doctor['license_number']}", self.styles['Footer']))
        
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", self.styles['Footer']))
        
        # Build PDF
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        return pdf_bytes

    async def generate_visit_report(self, visit: Dict[str, Any], patient: Dict[str, Any], 
                                  doctor: Dict[str, Any], template: Optional[Dict[str, Any]] = None) -> bytes:
        """Generate a visit report, either using a template or creating a default one"""
        try:
            if template and template.get('file_url'):
                # Download the template PDF
                template_bytes = await self.download_template_file(template['file_url'])
                
                # Prepare overlay data
                overlay_data = {
                    "patient_name": f"{patient['first_name']} {patient['last_name']}",
                    "visit_date": self._format_date(visit.get('visit_date', '')),
                    "doctor_name": f"Dr. {doctor['first_name']} {doctor['last_name']}",
                    "chief_complaint": self._safe(visit.get('chief_complaint')),
                    "diagnosis": self._safe(visit.get('diagnosis')),
                    "medications": self._safe(visit.get('medications')),
                    "treatment_plan": self._safe(visit.get('treatment_plan')),
                    "follow_up": self._format_date(visit.get('follow_up_date', '')) if visit.get('follow_up_date') else "As needed"
                }
                
                # Overlay visit information on template
                return self.overlay_text_on_pdf(template_bytes, overlay_data)
            else:
                # Create default report
                return self.create_default_visit_report(visit, patient, doctor)
                
        except Exception as e:
            print(f"Error generating visit report: {e}")
            # Fallback to default report if template processing fails
            return self.create_default_visit_report(visit, patient, doctor)
