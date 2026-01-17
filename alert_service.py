"""
Alert Service for Clinical Findings
====================================

This module provides a service for detecting, creating, and managing
clinical alerts from AI analysis results.

Part of Phase 1: Foundation Fixes (1.2 Add Critical Findings Alert System)
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class AlertType(Enum):
    """Types of clinical alerts"""
    CRITICAL_VALUE = "critical_value"
    DRUG_INTERACTION = "drug_interaction"
    DIAGNOSIS_CONCERN = "diagnosis_concern"
    FOLLOW_UP_URGENT = "follow_up_urgent"
    TREATMENT_ALERT = "treatment_alert"
    SAFETY_CONCERN = "safety_concern"


class AlertSeverity(Enum):
    """Severity levels for alerts"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ClinicalAlertService:
    """
    Service for managing clinical alerts from AI analysis.
    
    This service:
    1. Detects critical findings from AI analysis results
    2. Creates appropriate alerts in the database
    3. Manages alert acknowledgment workflow
    4. Provides alert queries for doctors
    """
    
    def __init__(self, supabase_client):
        """
        Initialize the alert service.
        
        Args:
            supabase_client: Supabase client instance for database operations
        """
        self.supabase = supabase_client
        
        # Critical value patterns to detect
        self.critical_patterns = {
            # Lab value patterns
            "hemoglobin": {"low": 7.0, "high": 18.0, "unit": "g/dL"},
            "hb": {"low": 7.0, "high": 18.0, "unit": "g/dL"},
            "wbc": {"low": 2000, "high": 30000, "unit": "/μL"},
            "platelet": {"low": 50000, "high": 500000, "unit": "/μL"},
            "creatinine": {"low": 0.4, "high": 4.0, "unit": "mg/dL"},
            "potassium": {"low": 2.5, "high": 6.5, "unit": "mEq/L"},
            "sodium": {"low": 120, "high": 160, "unit": "mEq/L"},
            "glucose": {"low": 40, "high": 500, "unit": "mg/dL"},
            "blood sugar": {"low": 40, "high": 500, "unit": "mg/dL"},
            "bp_systolic": {"low": 80, "high": 180, "unit": "mmHg"},
            "bp_diastolic": {"low": 50, "high": 120, "unit": "mmHg"},
            "inr": {"low": 0.5, "high": 4.5, "unit": ""},
            "troponin": {"low": 0, "high": 0.04, "unit": "ng/mL"},
        }
        
        # Keywords indicating critical findings
        self.critical_keywords = [
            "critical", "urgent", "emergency", "immediate attention",
            "life-threatening", "severe", "danger", "acute",
            "malignant", "carcinoma", "cancer", "tumor mass",
            "fracture", "hemorrhage", "bleeding", "infarction",
            "sepsis", "shock", "respiratory failure", "cardiac arrest",
            "stroke", "myocardial infarction", "pulmonary embolism"
        ]
    
    async def process_analysis_for_alerts(
        self,
        analysis_id: str,
        analysis_data: Dict[str, Any],
        patient_id: str,
        doctor_firebase_uid: str,
        visit_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Process AI analysis results and create alerts for critical findings.
        
        Args:
            analysis_id: The ID of the AI analysis
            analysis_data: The structured analysis data from Gemini
            patient_id: The patient ID
            doctor_firebase_uid: The doctor's Firebase UID
            visit_id: Optional visit ID
            
        Returns:
            List of created alert records
        """
        alerts_created = []
        
        try:
            # Extract critical findings from structured data
            critical_findings = analysis_data.get("critical_findings", [])
            
            # Also check findings for critical values
            findings = analysis_data.get("findings", [])
            
            # Process explicit critical findings
            for finding in critical_findings:
                alert = await self._create_alert_from_critical_finding(
                    finding=finding,
                    analysis_id=analysis_id,
                    patient_id=patient_id,
                    doctor_firebase_uid=doctor_firebase_uid,
                    visit_id=visit_id
                )
                if alert:
                    alerts_created.append(alert)
            
            # Check regular findings for critical values
            for finding in findings:
                if self._is_critical_finding(finding):
                    alert = await self._create_alert_from_finding(
                        finding=finding,
                        analysis_id=analysis_id,
                        patient_id=patient_id,
                        doctor_firebase_uid=doctor_firebase_uid,
                        visit_id=visit_id
                    )
                    if alert:
                        alerts_created.append(alert)
            
            # Check treatment evaluation for concerns
            treatment_eval = analysis_data.get("treatment_evaluation", {})
            if treatment_eval:
                treatment_alerts = await self._check_treatment_alerts(
                    treatment_eval=treatment_eval,
                    analysis_id=analysis_id,
                    patient_id=patient_id,
                    doctor_firebase_uid=doctor_firebase_uid,
                    visit_id=visit_id
                )
                alerts_created.extend(treatment_alerts)
            
            logger.info(
                f"Processed analysis {analysis_id}: created {len(alerts_created)} alerts"
            )
            
        except Exception as e:
            logger.error(f"Error processing analysis for alerts: {e}")
        
        return alerts_created
    
    def _is_critical_finding(self, finding: Dict[str, Any]) -> bool:
        """Check if a finding should be considered critical."""
        # Check for explicit critical flag
        if finding.get("is_critical", False):
            return True
        
        # Check the text content for critical keywords
        finding_text = str(finding).lower()
        for keyword in self.critical_keywords:
            if keyword in finding_text:
                return True
        
        # Check for out-of-range values
        value = finding.get("value")
        parameter = finding.get("parameter", "").lower()
        
        if value is not None and parameter:
            for param_name, ranges in self.critical_patterns.items():
                if param_name in parameter:
                    try:
                        numeric_value = float(str(value).replace(",", ""))
                        if numeric_value < ranges["low"] or numeric_value > ranges["high"]:
                            return True
                    except (ValueError, TypeError):
                        pass
        
        return False
    
    def _determine_severity(self, finding: Dict[str, Any]) -> str:
        """Determine the severity level of a finding."""
        finding_text = str(finding).lower()
        
        # High severity keywords
        high_severity = [
            "life-threatening", "emergency", "immediate", "critical",
            "severe", "acute", "cardiac arrest", "stroke", "hemorrhage"
        ]
        
        # Medium severity keywords
        medium_severity = [
            "urgent", "concerning", "abnormal", "elevated", "decreased",
            "warrants attention", "monitor closely"
        ]
        
        for keyword in high_severity:
            if keyword in finding_text:
                return AlertSeverity.HIGH.value
        
        for keyword in medium_severity:
            if keyword in finding_text:
                return AlertSeverity.MEDIUM.value
        
        return AlertSeverity.LOW.value
    
    def _determine_alert_type(self, finding: Dict[str, Any]) -> str:
        """Determine the type of alert based on the finding content."""
        finding_text = str(finding).lower()
        
        # Drug interaction patterns
        if any(word in finding_text for word in ["interaction", "contraindicated", "avoid"]):
            return AlertType.DRUG_INTERACTION.value
        
        # Diagnosis concern patterns
        if any(word in finding_text for word in ["malignant", "cancer", "tumor", "carcinoma", "suspicious"]):
            return AlertType.DIAGNOSIS_CONCERN.value
        
        # Follow-up urgency
        if any(word in finding_text for word in ["follow-up", "follow up", "review", "recheck"]):
            return AlertType.FOLLOW_UP_URGENT.value
        
        # Safety concerns
        if any(word in finding_text for word in ["safety", "fall risk", "allergy", "adverse"]):
            return AlertType.SAFETY_CONCERN.value
        
        # Treatment alerts
        if any(word in finding_text for word in ["treatment", "therapy", "medication", "dose"]):
            return AlertType.TREATMENT_ALERT.value
        
        # Default to critical value
        return AlertType.CRITICAL_VALUE.value
    
    async def _create_alert_from_critical_finding(
        self,
        finding: Dict[str, Any],
        analysis_id: str,
        patient_id: str,
        doctor_firebase_uid: str,
        visit_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Create an alert from an explicitly critical finding."""
        try:
            # Build alert title and message
            title = finding.get("finding", "Critical Finding Detected")[:200]
            message = finding.get("clinical_significance", finding.get("description", ""))
            recommendation = finding.get("recommended_action", "")
            
            if recommendation:
                message = f"{message}\n\nRecommended Action: {recommendation}"
            
            alert_data = {
                "patient_id": patient_id,
                "doctor_firebase_uid": doctor_firebase_uid,
                "visit_id": visit_id,
                "analysis_id": analysis_id,
                "alert_type": self._determine_alert_type(finding),
                "severity": self._determine_severity(finding),
                "title": title,
                "message": message[:2000] if message else "Critical finding detected",
                "finding_data": finding,
                "acknowledged": False,
                "created_at": datetime.utcnow().isoformat()
            }
            
            result = self.supabase.table("ai_clinical_alerts").insert(alert_data).execute()
            
            if result.data:
                logger.info(f"Created critical alert for patient {patient_id}: {title[:50]}")
                return result.data[0]
            
        except Exception as e:
            logger.error(f"Error creating alert from critical finding: {e}")
        
        return None
    
    async def _create_alert_from_finding(
        self,
        finding: Dict[str, Any],
        analysis_id: str,
        patient_id: str,
        doctor_firebase_uid: str,
        visit_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Create an alert from a finding that was detected as critical."""
        try:
            parameter = finding.get("parameter", "Unknown Parameter")
            value = finding.get("value", "N/A")
            unit = finding.get("unit", "")
            status = finding.get("status", "abnormal")
            
            title = f"Critical Value: {parameter}"
            message = f"Value: {value} {unit}\nStatus: {status}"
            
            if finding.get("interpretation"):
                message += f"\nInterpretation: {finding['interpretation']}"
            
            alert_data = {
                "patient_id": patient_id,
                "doctor_firebase_uid": doctor_firebase_uid,
                "visit_id": visit_id,
                "analysis_id": analysis_id,
                "alert_type": AlertType.CRITICAL_VALUE.value,
                "severity": self._determine_severity(finding),
                "title": title[:200],
                "message": message[:2000],
                "finding_data": finding,
                "acknowledged": False,
                "created_at": datetime.utcnow().isoformat()
            }
            
            result = self.supabase.table("ai_clinical_alerts").insert(alert_data).execute()
            
            if result.data:
                logger.info(f"Created value alert for patient {patient_id}: {title}")
                return result.data[0]
            
        except Exception as e:
            logger.error(f"Error creating alert from finding: {e}")
        
        return None
    
    async def _check_treatment_alerts(
        self,
        treatment_eval: Dict[str, Any],
        analysis_id: str,
        patient_id: str,
        doctor_firebase_uid: str,
        visit_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Check treatment evaluation for alerts."""
        alerts = []
        
        try:
            # Check for treatment concerns
            concerns = treatment_eval.get("concerns", [])
            for concern in concerns:
                if isinstance(concern, dict):
                    concern_text = concern.get("concern", str(concern))
                    severity = concern.get("severity", "medium")
                else:
                    concern_text = str(concern)
                    severity = "medium"
                
                # Only create alerts for significant concerns
                if any(word in concern_text.lower() for word in [
                    "contraindicated", "adverse", "allergic", "interaction",
                    "discontinue", "avoid", "dangerous", "risk"
                ]):
                    alert_data = {
                        "patient_id": patient_id,
                        "doctor_firebase_uid": doctor_firebase_uid,
                        "visit_id": visit_id,
                        "analysis_id": analysis_id,
                        "alert_type": AlertType.TREATMENT_ALERT.value,
                        "severity": severity if severity in ["high", "medium", "low"] else "medium",
                        "title": "Treatment Concern",
                        "message": concern_text[:2000],
                        "finding_data": concern if isinstance(concern, dict) else {"concern": concern_text},
                        "acknowledged": False,
                        "created_at": datetime.utcnow().isoformat()
                    }
                    
                    result = self.supabase.table("ai_clinical_alerts").insert(alert_data).execute()
                    if result.data:
                        alerts.append(result.data[0])
            
            # Check medication interactions
            interactions = treatment_eval.get("medication_interactions", [])
            for interaction in interactions:
                if isinstance(interaction, dict):
                    drugs = interaction.get("drugs", [])
                    effect = interaction.get("effect", "Unknown interaction")
                    severity = interaction.get("severity", "medium")
                    
                    title = f"Drug Interaction: {', '.join(drugs[:3])}" if drugs else "Drug Interaction"
                else:
                    title = "Drug Interaction"
                    effect = str(interaction)
                    severity = "medium"
                
                alert_data = {
                    "patient_id": patient_id,
                    "doctor_firebase_uid": doctor_firebase_uid,
                    "visit_id": visit_id,
                    "analysis_id": analysis_id,
                    "alert_type": AlertType.DRUG_INTERACTION.value,
                    "severity": severity if severity in ["high", "medium", "low"] else "medium",
                    "title": title[:200],
                    "message": effect[:2000],
                    "finding_data": interaction if isinstance(interaction, dict) else {"interaction": effect},
                    "acknowledged": False,
                    "created_at": datetime.utcnow().isoformat()
                }
                
                result = self.supabase.table("ai_clinical_alerts").insert(alert_data).execute()
                if result.data:
                    alerts.append(result.data[0])
                    
        except Exception as e:
            logger.error(f"Error checking treatment alerts: {e}")
        
        return alerts
    
    async def get_unacknowledged_alerts(
        self,
        doctor_firebase_uid: str,
        patient_id: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get unacknowledged alerts for a doctor.
        
        Args:
            doctor_firebase_uid: The doctor's Firebase UID
            patient_id: Optional filter by patient
            severity: Optional filter by severity (high, medium, low)
            limit: Maximum number of alerts to return
            
        Returns:
            List of unacknowledged alert records
        """
        try:
            query = self.supabase.table("ai_clinical_alerts") \
                .select("*") \
                .eq("doctor_firebase_uid", doctor_firebase_uid) \
                .eq("acknowledged", False) \
                .order("created_at", desc=True) \
                .limit(limit)
            
            if patient_id:
                query = query.eq("patient_id", patient_id)
            
            if severity:
                query = query.eq("severity", severity)
            
            result = query.execute()
            return result.data or []
            
        except Exception as e:
            logger.error(f"Error getting unacknowledged alerts: {e}")
            return []
    
    async def get_alert_counts(
        self,
        doctor_firebase_uid: str
    ) -> Dict[str, int]:
        """
        Get counts of alerts by severity for a doctor.
        
        Args:
            doctor_firebase_uid: The doctor's Firebase UID
            
        Returns:
            Dictionary with counts by severity
        """
        try:
            # Use the database function if available, otherwise count manually
            result = self.supabase.rpc(
                "get_alert_counts",
                {"p_doctor_uid": doctor_firebase_uid}
            ).execute()
            
            if result.data and len(result.data) > 0:
                counts = result.data[0]
                return {
                    "high": counts.get("high_count", 0),
                    "medium": counts.get("medium_count", 0),
                    "low": counts.get("low_count", 0),
                    "total": counts.get("total_count", 0)
                }
            
        except Exception as e:
            logger.warning(f"Error using get_alert_counts RPC, falling back to manual count: {e}")
        
        # Fallback: manual counting
        try:
            alerts = await self.get_unacknowledged_alerts(
                doctor_firebase_uid=doctor_firebase_uid,
                limit=1000
            )
            
            counts = {"high": 0, "medium": 0, "low": 0, "total": 0}
            for alert in alerts:
                severity = alert.get("severity", "low")
                counts[severity] = counts.get(severity, 0) + 1
                counts["total"] += 1
            
            return counts
            
        except Exception as e:
            logger.error(f"Error getting alert counts: {e}")
            return {"high": 0, "medium": 0, "low": 0, "total": 0}
    
    async def acknowledge_alert(
        self,
        alert_id: str,
        doctor_firebase_uid: str,
        notes: Optional[str] = None
    ) -> bool:
        """
        Acknowledge an alert.
        
        Args:
            alert_id: The alert ID to acknowledge
            doctor_firebase_uid: The doctor acknowledging the alert
            notes: Optional notes about the acknowledgment
            
        Returns:
            True if successful, False otherwise
        """
        try:
            update_data = {
                "acknowledged": True,
                "acknowledged_at": datetime.utcnow().isoformat(),
                "acknowledged_by": doctor_firebase_uid
            }
            
            if notes:
                update_data["acknowledgment_notes"] = notes
            
            result = self.supabase.table("ai_clinical_alerts") \
                .update(update_data) \
                .eq("id", alert_id) \
                .eq("doctor_firebase_uid", doctor_firebase_uid) \
                .execute()
            
            return len(result.data) > 0 if result.data else False
            
        except Exception as e:
            logger.error(f"Error acknowledging alert {alert_id}: {e}")
            return False
    
    async def acknowledge_all_for_patient(
        self,
        patient_id: str,
        doctor_firebase_uid: str
    ) -> int:
        """
        Acknowledge all alerts for a patient.
        
        Args:
            patient_id: The patient ID
            doctor_firebase_uid: The doctor acknowledging the alerts
            
        Returns:
            Number of alerts acknowledged
        """
        try:
            update_data = {
                "acknowledged": True,
                "acknowledged_at": datetime.utcnow().isoformat(),
                "acknowledged_by": doctor_firebase_uid
            }
            
            result = self.supabase.table("ai_clinical_alerts") \
                .update(update_data) \
                .eq("patient_id", patient_id) \
                .eq("doctor_firebase_uid", doctor_firebase_uid) \
                .eq("acknowledged", False) \
                .execute()
            
            return len(result.data) if result.data else 0
            
        except Exception as e:
            logger.error(f"Error acknowledging alerts for patient {patient_id}: {e}")
            return 0
    
    async def get_patient_alert_history(
        self,
        patient_id: str,
        doctor_firebase_uid: str,
        days: int = 90,
        include_acknowledged: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get alert history for a patient.
        
        Args:
            patient_id: The patient ID
            doctor_firebase_uid: The doctor's Firebase UID
            days: Number of days of history to retrieve
            include_acknowledged: Whether to include acknowledged alerts
            
        Returns:
            List of alert records
        """
        try:
            since_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
            
            query = self.supabase.table("ai_clinical_alerts") \
                .select("*") \
                .eq("patient_id", patient_id) \
                .eq("doctor_firebase_uid", doctor_firebase_uid) \
                .gte("created_at", since_date) \
                .order("created_at", desc=True)
            
            if not include_acknowledged:
                query = query.eq("acknowledged", False)
            
            result = query.execute()
            return result.data or []
            
        except Exception as e:
            logger.error(f"Error getting patient alert history: {e}")
            return []
    
    async def get_alerts_for_visit(
        self,
        visit_id: str,
        doctor_firebase_uid: str
    ) -> List[Dict[str, Any]]:
        """
        Get all alerts associated with a specific visit.
        
        Args:
            visit_id: The visit ID
            doctor_firebase_uid: The doctor's Firebase UID
            
        Returns:
            List of alert records for the visit
        """
        try:
            result = self.supabase.table("ai_clinical_alerts") \
                .select("*") \
                .eq("visit_id", visit_id) \
                .eq("doctor_firebase_uid", doctor_firebase_uid) \
                .order("severity", desc=True) \
                .execute()
            
            return result.data or []
            
        except Exception as e:
            logger.error(f"Error getting alerts for visit {visit_id}: {e}")
            return []


# Singleton instance holder
_alert_service_instance: Optional[ClinicalAlertService] = None


def get_alert_service(supabase_client) -> ClinicalAlertService:
    """
    Get or create the singleton alert service instance.
    
    Args:
        supabase_client: Supabase client instance
        
    Returns:
        ClinicalAlertService instance
    """
    global _alert_service_instance
    
    if _alert_service_instance is None:
        _alert_service_instance = ClinicalAlertService(supabase_client)
    
    return _alert_service_instance
