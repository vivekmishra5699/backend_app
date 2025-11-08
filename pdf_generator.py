from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from datetime import datetime, date
import io
import os
from typing import Dict, Any, List

class PatientProfilePDFGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.setup_custom_styles()
    
    def setup_custom_styles(self):
        """Setup custom styles for the PDF"""
        self.styles.add(ParagraphStyle(
            name='PatientName',
            parent=self.styles['Heading1'],
            fontSize=18,
            spaceAfter=12,
            textColor=colors.darkblue,
            alignment=TA_CENTER
        ))
        
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=14,
            spaceAfter=8,
            spaceBefore=12,
            textColor=colors.darkblue,
            borderWidth=1,
            borderColor=colors.darkblue,
            borderPadding=5
        ))
        
        self.styles.add(ParagraphStyle(
            name='FieldLabel',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.darkgray,
            fontName='Helvetica-Bold'
        ))
        
        self.styles.add(ParagraphStyle(
            name='FieldValue',
            parent=self.styles['Normal'],
            fontSize=10,
            spaceAfter=4
        ))

    def _safe(self, value: Any, default: str = "N/A") -> str:
        return str(value) if (value is not None and value != "") else default

    def _format_iso_dt(self, iso_str: str, out_fmt: str = "%Y-%m-%d %H:%M") -> str:
        try:
            dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
            return dt.strftime(out_fmt)
        except Exception:
            return self._safe(iso_str)

    def _calc_age(self, dob_str: str) -> str:
        try:
            # Expecting YYYY-MM-DD
            dob = datetime.strptime(dob_str[:10], "%Y-%m-%d").date()
            today = date.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return f"{age} years"
        except Exception:
            return "N/A"

    def generate_patient_profile_pdf(self, patient: Dict[str, Any], visits: List[Dict[str, Any]], 
                                   reports: List[Dict[str, Any]], doctor: Dict[str, Any]) -> bytes:
        """Generate a complete patient profile PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, 
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Header
        story.append(Paragraph("PATIENT MEDICAL PROFILE", self.styles['PatientName']))
        story.append(Spacer(1, 12))
        
        # Doctor Information
        story.append(Paragraph("PHYSICIAN INFORMATION", self.styles['SectionHeader']))
        doctor_data = [
            ['Doctor Name:', f"Dr. {self._safe(doctor.get('first_name'))} {self._safe(doctor.get('last_name'))}"],
            ['Specialization:', self._safe(doctor.get('specialization'))],
            ['License Number:', self._safe(doctor.get('license_number'))],
            ['Phone:', self._safe(doctor.get('phone'))],
            ['Email:', self._safe(doctor.get('email'))]
        ]
        doctor_table = Table(doctor_data, colWidths=[2*inch, 4*inch])
        doctor_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEBELOW', (0, -1), (-1, -1), 1, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(doctor_table)
        story.append(Spacer(1, 20))
        
        # Patient Demographics
        story.append(Paragraph("PATIENT DEMOGRAPHICS", self.styles['SectionHeader']))
        age = self._calc_age(self._safe(patient.get('date_of_birth')))
        patient_data = [
            ['Patient ID:', self._safe(patient.get('id'))],
            ['Patient Name:', f"{self._safe(patient.get('first_name'))} {self._safe(patient.get('last_name'))}"],
            ['Date of Birth:', self._safe(patient.get('date_of_birth'))],
            ['Age:', age],
            ['Gender:', self._safe(patient.get('gender'))],
            ['Phone:', self._safe(patient.get('phone'))],
            ['Email:', self._safe(patient.get('email'))],
            ['Address:', self._safe(patient.get('address'))],
            ['Blood Group:', self._safe(patient.get('blood_group'))],
            ['Emergency Contact:', f"{self._safe(patient.get('emergency_contact_name'))} - {self._safe(patient.get('emergency_contact_phone'))}"],
            ['Profile Created:', self._format_iso_dt(self._safe(patient.get('created_at')))],
            ['Last Updated:', self._format_iso_dt(self._safe(patient.get('updated_at')))]
        ]
        
        patient_table = Table(patient_data, colWidths=[2*inch, 4*inch])
        patient_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEBELOW', (0, -1), (-1, -1), 1, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(patient_table)
        story.append(Spacer(1, 20))
        
        # Medical History
        if patient.get('allergies') or patient.get('medical_history'):
            story.append(Paragraph("MEDICAL HISTORY", self.styles['SectionHeader']))
            if patient.get('allergies'):
                story.append(Paragraph("Allergies:", self.styles['FieldLabel']))
                story.append(Paragraph(self._safe(patient.get('allergies')), self.styles['FieldValue']))
                story.append(Spacer(1, 8))
            
            if patient.get('medical_history'):
                story.append(Paragraph("Medical History:", self.styles['FieldLabel']))
                story.append(Paragraph(self._safe(patient.get('medical_history')), self.styles['FieldValue']))
            
            story.append(Spacer(1, 20))
        
        # Visits History - include all details from each visit
        if visits:
            story.append(Paragraph("VISIT HISTORY", self.styles['SectionHeader']))
            
            for idx, visit in enumerate(visits, start=1):
                story.append(Paragraph(f"Visit Date: {self._safe(visit.get('visit_date'))}", self.styles['FieldLabel']))
                
                visit_data = []
                visit_data.append(['Visit ID:', self._safe(visit.get('id'))])
                if visit.get('visit_time'):
                    visit_data.append(['Time:', self._safe(visit.get('visit_time'))])
                visit_data.extend([
                    ['Type:', self._safe(visit.get('visit_type'))],
                    ['Chief Complaint:', self._safe(visit.get('chief_complaint'))],
                ])
                
                if visit.get('symptoms'):
                    visit_data.append(['Symptoms:', self._safe(visit.get('symptoms'))])
                if visit.get('clinical_examination'):
                    visit_data.append(['Clinical Examination:', self._safe(visit.get('clinical_examination'))])
                if visit.get('diagnosis'):
                    visit_data.append(['Diagnosis:', self._safe(visit.get('diagnosis'))])
                if visit.get('treatment_plan'):
                    visit_data.append(['Treatment Plan:', self._safe(visit.get('treatment_plan'))])
                if visit.get('medications'):
                    visit_data.append(['Medications:', self._safe(visit.get('medications'))])
                if visit.get('tests_recommended'):
                    visit_data.append(['Tests Recommended:', self._safe(visit.get('tests_recommended'))])
                if visit.get('follow_up_date'):
                    visit_data.append(['Follow-up Date:', self._safe(visit.get('follow_up_date'))])
                
                # Vitals - include full set
                if visit.get('vitals'):
                    vitals = visit['vitals'] or {}
                    vitals_str = []
                    if vitals.get('temperature') is not None:
                        vitals_str.append(f"Temperature: {vitals['temperature']}°C")
                    if vitals.get('blood_pressure_systolic') is not None and vitals.get('blood_pressure_diastolic') is not None:
                        vitals_str.append(f"BP: {vitals['blood_pressure_systolic']}/{vitals['blood_pressure_diastolic']} mmHg")
                    if vitals.get('heart_rate') is not None:
                        vitals_str.append(f"Heart Rate: {vitals['heart_rate']} BPM")
                    if vitals.get('respiratory_rate') is not None:
                        vitals_str.append(f"Respiratory Rate: {vitals['respiratory_rate']} breaths/min")
                    if vitals.get('oxygen_saturation') is not None:
                        vitals_str.append(f"SpO₂: {vitals['oxygen_saturation']}%")
                    if vitals.get('weight') is not None:
                        vitals_str.append(f"Weight: {vitals['weight']} kg")
                    if vitals.get('height') is not None:
                        vitals_str.append(f"Height: {vitals['height']} cm")
                    if vitals.get('bmi') is not None:
                        vitals_str.append(f"BMI: {vitals['bmi']}")
                    
                    if vitals_str:
                        visit_data.append(['Vitals:', ', '.join(vitals_str)])
                
                if visit.get('notes'):
                    visit_data.append(['Notes:', self._safe(visit.get('notes'))])

                # Visit timestamps
                if visit.get('created_at'):
                    visit_data.append(['Recorded On:', self._format_iso_dt(self._safe(visit.get('created_at')))])
                if visit.get('updated_at'):
                    visit_data.append(['Last Updated:', self._format_iso_dt(self._safe(visit.get('updated_at')))])
                
                visit_table = Table(visit_data, colWidths=[1.8*inch, 4.2*inch])
                visit_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ]))
                story.append(visit_table)
                story.append(Spacer(1, 12))
                
                # Optional page break between visits if many details
                # if idx % 3 == 0:
                #     story.append(PageBreak())
        
        # Reports Summary (remove file size)
        if reports:
            story.append(Paragraph("REPORTS SUMMARY", self.styles['SectionHeader']))
            
            # Group reports by test type
            reports_by_test = {}
            for report in reports:
                test_type = report.get('test_type', 'General Report')
                if test_type not in reports_by_test:
                    reports_by_test[test_type] = []
                reports_by_test[test_type].append(report)
            
            for test_type, test_reports in reports_by_test.items():
                story.append(Paragraph(f"{self._safe(test_type)}:", self.styles['FieldLabel']))
                
                report_data = []
                for report in test_reports:
                    uploaded_at_fmt = self._format_iso_dt(self._safe(report.get('uploaded_at')))
                    report_data.append([
                        self._safe(report.get('file_name')),
                        uploaded_at_fmt,
                        self._safe(report.get('notes', 'N/A'))
                    ])
                
                if report_data:
                    # 3 columns: File Name, Upload Date, Notes
                    report_table = Table(
                        [['File Name', 'Upload Date', 'Notes']] + report_data,
                        colWidths=[2.5*inch, 2.0*inch, 1.5*inch]
                    )
                    report_table.setStyle(TableStyle([
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, -1), 8),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
                    ]))
                    story.append(report_table)
                    story.append(Spacer(1, 8))
        
        # Footer
        story.append(Spacer(1, 30))
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", 
                             self.styles['Normal']))
        story.append(Paragraph("This is a confidential medical document.", 
                             self.styles['Normal']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()