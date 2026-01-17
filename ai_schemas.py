"""
AI Analysis JSON Schemas

Structured output schemas for Gemini AI responses.
Using JSON mode eliminates unreliable text parsing.
"""

from typing import Dict, Any

# ============================================================================
# DOCUMENT ANALYSIS SCHEMA
# Used for analyzing lab reports, X-rays, and other medical documents
# ============================================================================

DOCUMENT_ANALYSIS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_type": {
            "type": "string",
            "description": "Type of medical document (CBC, LFT, X-Ray, MRI, CT Scan, Urinalysis, etc.)"
        },
        "document_date": {
            "type": "string",
            "description": "Date of test/report if available (YYYY-MM-DD format)"
        },
        "document_quality": {
            "type": "string",
            "enum": ["excellent", "good", "fair", "poor"],
            "description": "Quality/readability of the document"
        },
        "document_summary": {
            "type": "string",
            "description": "Comprehensive summary of the document findings (2-3 paragraphs)"
        },
        "clinical_correlation": {
            "type": "object",
            "properties": {
                "relevance_to_complaint": {
                    "type": "string",
                    "description": "How findings relate to the patient's chief complaint"
                },
                "supports_diagnosis": {
                    "type": "boolean",
                    "description": "Whether findings support the working diagnosis"
                },
                "diagnosis_validation": {
                    "type": "string",
                    "description": "Detailed explanation of how results confirm/refute diagnosis"
                },
                "symptom_explanation": {
                    "type": "string",
                    "description": "Which findings explain the patient's symptoms"
                },
                "examination_correlation": {
                    "type": "string",
                    "description": "How findings correlate with clinical examination"
                }
            },
            "required": ["relevance_to_complaint", "supports_diagnosis"]
        },
        "findings": {
            "type": "array",
            "description": "List of all significant findings from the document",
            "items": {
                "type": "object",
                "properties": {
                    "parameter": {
                        "type": "string",
                        "description": "Name of the parameter/test (e.g., Hemoglobin, WBC, Creatinine)"
                    },
                    "value": {
                        "type": "string",
                        "description": "Measured value with units"
                    },
                    "reference_range": {
                        "type": "string",
                        "description": "Normal reference range"
                    },
                    "unit": {
                        "type": "string",
                        "description": "Unit of measurement"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["normal", "borderline_low", "borderline_high", "low", "high", "critical_low", "critical_high"],
                        "description": "Status relative to reference range"
                    },
                    "clinical_significance": {
                        "type": "string",
                        "description": "What this value means clinically for this patient"
                    },
                    "trend": {
                        "type": "string",
                        "enum": ["improving", "stable", "worsening", "unknown"],
                        "description": "Trend compared to previous values if known"
                    }
                },
                "required": ["parameter", "value", "status"]
            }
        },
        "critical_findings": {
            "type": "array",
            "description": "Findings requiring urgent attention",
            "items": {
                "type": "object",
                "properties": {
                    "finding": {
                        "type": "string",
                        "description": "Description of the critical finding"
                    },
                    "parameter": {
                        "type": "string",
                        "description": "Parameter name if applicable"
                    },
                    "value": {
                        "type": "string",
                        "description": "The critical value"
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["immediate", "within_24_hours", "within_48_hours", "within_week"],
                        "description": "How urgently action is needed"
                    },
                    "recommended_action": {
                        "type": "string",
                        "description": "Specific action recommended"
                    },
                    "potential_risk": {
                        "type": "string",
                        "description": "Risk if not addressed"
                    }
                },
                "required": ["finding", "urgency", "recommended_action"]
            }
        },
        "treatment_evaluation": {
            "type": "object",
            "description": "Evaluation of current treatment based on results",
            "properties": {
                "current_treatment_appropriate": {
                    "type": "boolean",
                    "description": "Whether current treatment plan is appropriate"
                },
                "treatment_response": {
                    "type": "string",
                    "enum": ["excellent", "good", "partial", "poor", "unknown"],
                    "description": "How patient is responding to treatment"
                },
                "modification_needed": {
                    "type": "boolean",
                    "description": "Whether treatment modification is recommended"
                },
                "suggestions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific treatment modification suggestions"
                },
                "contraindications": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Any contraindications revealed by results"
                }
            },
            "required": ["current_treatment_appropriate", "modification_needed"]
        },
        "actionable_insights": {
            "type": "array",
            "description": "Specific actions for the doctor to consider",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "The recommended action"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["immediate", "high", "medium", "low"],
                        "description": "Priority level of this action"
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why this action is recommended"
                    }
                },
                "required": ["action", "priority"]
            }
        },
        "patient_communication": {
            "type": "object",
            "description": "Guidance for communicating results to patient",
            "properties": {
                "summary_for_patient": {
                    "type": "string",
                    "description": "Simple, non-technical explanation of results"
                },
                "key_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key points to discuss with patient"
                },
                "reassurance_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Positive findings to reassure patient"
                },
                "concerns_to_discuss": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Concerns that need to be discussed"
                },
                "lifestyle_recommendations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lifestyle changes to recommend"
                }
            },
            "required": ["summary_for_patient", "key_points"]
        },
        "follow_up_recommendations": {
            "type": "array",
            "description": "Recommended follow-up tests and actions",
            "items": {
                "type": "object",
                "properties": {
                    "test_name": {
                        "type": "string",
                        "description": "Name of recommended test or action"
                    },
                    "timeframe": {
                        "type": "string",
                        "description": "When to perform (e.g., '1 week', '3 months', 'immediately')"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this follow-up is recommended"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["urgent", "routine", "optional"],
                        "description": "Priority of this follow-up"
                    }
                },
                "required": ["test_name", "timeframe", "reason"]
            }
        },
        "clinical_notes": {
            "type": "string",
            "description": "Additional clinical observations for medical records"
        },
        "confidence_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence in this analysis (0.0 to 1.0)"
        }
    },
    "required": ["document_type", "document_summary", "findings", "clinical_correlation", "confidence_score"]
}


# ============================================================================
# HANDWRITTEN PRESCRIPTION ANALYSIS SCHEMA
# Used for analyzing handwritten prescriptions and notes
# ============================================================================

HANDWRITTEN_ANALYSIS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "legibility_score": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "description": "Overall legibility score (1=illegible, 10=perfectly clear)"
        },
        "extracted_text": {
            "type": "object",
            "properties": {
                "header_info": {"type": "string"},
                "chief_complaint": {"type": "string"},
                "history": {"type": "string"},
                "examination_findings": {"type": "string"},
                "diagnosis": {"type": "string"},
                "treatment_plan": {"type": "string"},
                "special_instructions": {"type": "string"},
                "follow_up_notes": {"type": "string"}
            }
        },
        "medications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "drug_name": {"type": "string"},
                    "brand_name": {"type": "string"},
                    "generic_name": {"type": "string"},
                    "dosage": {"type": "string"},
                    "route": {"type": "string"},
                    "frequency": {"type": "string"},
                    "duration": {"type": "string"},
                    "timing_instructions": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low", "uncertain"]
                    }
                },
                "required": ["drug_name", "dosage", "frequency"]
            }
        },
        "diagnosis": {
            "type": "object",
            "properties": {
                "primary_diagnosis": {"type": "string"},
                "secondary_diagnoses": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "icd_codes": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        },
        "safety_check": {
            "type": "object",
            "properties": {
                "allergy_concerns": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "contraindications": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "drug_interactions": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "dosage_concerns": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        },
        "patient_instructions": {
            "type": "object",
            "properties": {
                "medication_schedule": {"type": "string"},
                "dietary_instructions": {"type": "string"},
                "activity_restrictions": {"type": "string"},
                "warning_signs": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "follow_up_date": {"type": "string"}
            }
        },
        "unclear_sections": {
            "type": "array",
            "description": "Sections that were difficult to read",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},
                    "issue": {"type": "string"},
                    "best_interpretation": {"type": "string"}
                }
            }
        },
        "visit_summary": {
            "type": "string",
            "description": "Comprehensive summary of the visit"
        },
        "confidence_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
        }
    },
    "required": ["legibility_score", "medications", "diagnosis", "confidence_score"]
}


# ============================================================================
# COMPREHENSIVE HISTORY ANALYSIS SCHEMA
# Used for analyzing complete patient medical history
# ============================================================================

COMPREHENSIVE_HISTORY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "medical_summary": {
            "type": "string",
            "description": "Complete narrative of patient's health journey"
        },
        "medical_trajectory": {
            "type": "object",
            "properties": {
                "overall_trend": {
                    "type": "string",
                    "enum": ["improving", "stable", "declining", "fluctuating"]
                },
                "trajectory_description": {"type": "string"},
                "key_turning_points": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        },
        "chronic_conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "condition": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["well_controlled", "partially_controlled", "uncontrolled", "resolved"]
                    },
                    "duration": {"type": "string"},
                    "current_treatment": {"type": "string"}
                }
            }
        },
        "recurring_patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "frequency": {"type": "string"},
                    "triggers": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            }
        },
        "treatment_effectiveness": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "treatment": {"type": "string"},
                    "condition": {"type": "string"},
                    "effectiveness": {
                        "type": "string",
                        "enum": ["highly_effective", "moderately_effective", "minimally_effective", "ineffective"]
                    },
                    "notes": {"type": "string"}
                }
            }
        },
        "risk_factors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "risk": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["high", "moderate", "low"]
                    },
                    "mitigation": {"type": "string"}
                }
            }
        },
        "missed_opportunities": {
            "type": "array",
            "description": "Things that might have been overlooked",
            "items": {
                "type": "object",
                "properties": {
                    "observation": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"]
                    }
                }
            }
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "recommendation": {"type": "string"},
                    "timeframe": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["immediate", "short_term", "long_term", "preventive"]
                    },
                    "rationale": {"type": "string"}
                }
            }
        },
        "significant_findings": {
            "type": "array",
            "items": {"type": "string"}
        },
        "follow_up_plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "timeframe": {"type": "string"},
                    "reason": {"type": "string"}
                }
            }
        },
        "confidence_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
        }
    },
    "required": ["medical_summary", "medical_trajectory", "recommendations", "confidence_score"]
}


# ============================================================================
# CONSOLIDATED ANALYSIS SCHEMA
# Used for analyzing multiple reports together
# ============================================================================

CONSOLIDATED_ANALYSIS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "overall_assessment": {
            "type": "string",
            "description": "Synthesized findings across all documents"
        },
        "clinical_picture": {
            "type": "string",
            "description": "Complete diagnostic picture from all results"
        },
        "document_correlations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "documents": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "correlation": {"type": "string"},
                    "significance": {"type": "string"}
                }
            }
        },
        "conflicting_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding1": {"type": "string"},
                    "finding2": {"type": "string"},
                    "resolution": {"type": "string"}
                }
            }
        },
        "integrated_recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "recommendation": {"type": "string"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                    "based_on": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            }
        },
        "patient_summary": {
            "type": "string",
            "description": "Unified explanation for patient"
        },
        "priority_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "urgency": {
                        "type": "string",
                        "enum": ["immediate", "urgent", "routine"]
                    },
                    "reason": {"type": "string"}
                }
            }
        },
        "confidence_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
        }
    },
    "required": ["overall_assessment", "clinical_picture", "integrated_recommendations", "confidence_score"]
}


# ============================================================================
# VISIT SUMMARY (SOAP NOTE) SCHEMA
# Used for generating visit summaries
# ============================================================================

SOAP_NOTE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "subjective": {
            "type": "object",
            "properties": {
                "chief_complaint": {"type": "string"},
                "history_of_present_illness": {"type": "string"},
                "review_of_systems": {"type": "string"},
                "past_medical_history": {"type": "string"},
                "medications": {"type": "string"},
                "allergies": {"type": "string"},
                "social_history": {"type": "string"},
                "family_history": {"type": "string"}
            },
            "required": ["chief_complaint", "history_of_present_illness"]
        },
        "objective": {
            "type": "object",
            "properties": {
                "vital_signs": {"type": "string"},
                "physical_examination": {"type": "string"},
                "laboratory_results": {"type": "string"},
                "imaging_results": {"type": "string"},
                "other_findings": {"type": "string"}
            },
            "required": ["vital_signs", "physical_examination"]
        },
        "assessment": {
            "type": "object",
            "properties": {
                "primary_diagnosis": {"type": "string"},
                "differential_diagnoses": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "icd10_codes": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "clinical_reasoning": {"type": "string"},
                "prognosis": {"type": "string"}
            },
            "required": ["primary_diagnosis"]
        },
        "plan": {
            "type": "object",
            "properties": {
                "treatment_plan": {"type": "string"},
                "medications_prescribed": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "procedures": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "cpt_codes": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "patient_education": {"type": "string"},
                "follow_up_instructions": {"type": "string"},
                "referrals": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["treatment_plan", "follow_up_instructions"]
        }
    },
    "required": ["subjective", "objective", "assessment", "plan"]
}


# ============================================================================
# RISK SCORE SCHEMA
# Used for calculating patient risk scores
# ============================================================================

RISK_SCORE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "overall_risk_score": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "description": "Overall health risk score (0=lowest, 100=highest)"
        },
        "cardiovascular_risk": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100
        },
        "diabetes_risk": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100
        },
        "kidney_risk": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100
        },
        "liver_risk": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100
        },
        "risk_factors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "factor": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["high", "moderate", "low"]
                    },
                    "impact_score": {"type": "integer", "minimum": 1, "maximum": 10}
                }
            }
        },
        "protective_factors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "factor": {"type": "string"},
                    "benefit_score": {"type": "integer", "minimum": 1, "maximum": 10}
                }
            }
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "recommendation": {"type": "string"},
                    "impact": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"]
                    }
                }
            }
        },
        "confidence_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
        }
    },
    "required": ["overall_risk_score", "risk_factors", "recommendations", "confidence_score"]
}


# ============================================================================
# DIFFERENTIAL DIAGNOSIS SCHEMA
# Used for generating differential diagnoses
# ============================================================================

DIFFERENTIAL_DIAGNOSIS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "primary_diagnosis": {
            "type": "object",
            "properties": {
                "diagnosis": {"type": "string"},
                "probability": {"type": "number", "minimum": 0, "maximum": 1},
                "supporting_evidence": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "against_evidence": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        },
        "differential_diagnoses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "diagnosis": {"type": "string"},
                    "probability": {"type": "number", "minimum": 0, "maximum": 1},
                    "supporting_evidence": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "tests_to_confirm": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            }
        },
        "red_flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symptom": {"type": "string"},
                    "concern": {"type": "string"},
                    "action_required": {"type": "string"}
                }
            }
        },
        "recommended_tests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "test": {"type": "string"},
                    "purpose": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["urgent", "routine", "if_needed"]
                    }
                }
            }
        },
        "clinical_reasoning": {
            "type": "string"
        },
        "confidence_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
        }
    },
    "required": ["primary_diagnosis", "differential_diagnoses", "clinical_reasoning", "confidence_score"]
}
