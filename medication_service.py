"""
Medication Interaction Service
==============================

Phase 2.1: Clinical Intelligence - Medication Interaction Checking

This service provides:
1. Drug-drug interaction detection
2. Drug-allergy warning system
3. Contraindication checking
4. Integration with AI analysis for medication safety

Created: January 17, 2026
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum
import re

logger = logging.getLogger(__name__)


class InteractionSeverity(Enum):
    """Severity levels for drug interactions"""
    CRITICAL = "critical"      # Life-threatening, contraindicated
    HIGH = "high"              # Major interaction, use with caution
    MODERATE = "moderate"      # Moderate risk, monitor closely
    LOW = "low"                # Minor interaction, generally safe
    UNKNOWN = "unknown"        # Unknown interaction level


class MedicationInteractionService:
    """
    Service for checking drug interactions, allergies, and contraindications.
    
    This service:
    1. Checks drug-drug interactions from a curated database
    2. Detects potential allergy conflicts
    3. Identifies contraindications based on patient conditions
    4. Provides recommendations for safer alternatives
    """
    
    def __init__(self):
        """Initialize the medication interaction service with interaction database"""
        
        # =====================================================================
        # DRUG INTERACTION DATABASE
        # Format: (drug1, drug2) -> interaction_info
        # Drug names are normalized to lowercase for matching
        # =====================================================================
        self.DRUG_INTERACTIONS: Dict[Tuple[str, str], Dict[str, Any]] = {
            # Anticoagulant interactions
            ("warfarin", "aspirin"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Increased bleeding risk due to additive anticoagulant effects",
                "mechanism": "Both drugs affect clotting; aspirin inhibits platelets while warfarin inhibits clotting factors",
                "recommendation": "Monitor INR closely. Consider alternative antiplatelet if needed. Watch for signs of bleeding.",
                "alternatives": ["Clopidogrel with caution", "Low-dose aspirin with close monitoring"]
            },
            ("warfarin", "ibuprofen"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Increased bleeding risk and potential INR elevation",
                "mechanism": "NSAIDs inhibit platelet function and can displace warfarin from protein binding",
                "recommendation": "Avoid combination. Use acetaminophen for pain if possible.",
                "alternatives": ["Acetaminophen (paracetamol)", "Topical NSAIDs with caution"]
            },
            ("warfarin", "naproxen"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Increased bleeding risk",
                "mechanism": "NSAID inhibits platelet aggregation",
                "recommendation": "Avoid combination. Monitor for GI bleeding.",
                "alternatives": ["Acetaminophen"]
            },
            ("warfarin", "vitamin k"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Decreased anticoagulant effect",
                "mechanism": "Vitamin K antagonizes warfarin's mechanism of action",
                "recommendation": "Maintain consistent vitamin K intake. Adjust warfarin dose if needed.",
                "alternatives": []
            },
            
            # Antibiotic interactions
            ("metronidazole", "alcohol"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Severe disulfiram-like reaction: flushing, nausea, vomiting, headache",
                "mechanism": "Metronidazole inhibits aldehyde dehydrogenase",
                "recommendation": "Avoid alcohol during treatment and 48 hours after completing course",
                "alternatives": []
            },
            ("ciprofloxacin", "antacids"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Reduced ciprofloxacin absorption and effectiveness",
                "mechanism": "Metal cations in antacids chelate with fluoroquinolones",
                "recommendation": "Take ciprofloxacin 2 hours before or 6 hours after antacids",
                "alternatives": ["H2 blockers", "PPIs"]
            },
            ("ciprofloxacin", "theophylline"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Increased theophylline levels, risk of toxicity",
                "mechanism": "Ciprofloxacin inhibits CYP1A2 metabolism of theophylline",
                "recommendation": "Monitor theophylline levels. Consider dose reduction.",
                "alternatives": ["Azithromycin", "Amoxicillin"]
            },
            ("tetracycline", "calcium"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Reduced tetracycline absorption",
                "mechanism": "Calcium chelates with tetracycline",
                "recommendation": "Separate doses by 2-3 hours",
                "alternatives": []
            },
            ("tetracycline", "iron"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Reduced absorption of both drugs",
                "mechanism": "Iron chelates with tetracycline",
                "recommendation": "Separate doses by 2-3 hours",
                "alternatives": []
            },
            
            # Diabetes medication interactions
            ("metformin", "contrast"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Risk of lactic acidosis, especially with iodinated contrast",
                "mechanism": "Contrast-induced nephropathy impairs metformin clearance",
                "recommendation": "Hold metformin 48 hours before and after contrast administration. Check renal function before resuming.",
                "alternatives": []
            },
            ("metformin", "alcohol"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Increased risk of hypoglycemia and lactic acidosis",
                "mechanism": "Alcohol potentiates hypoglycemic effect and impairs lactate metabolism",
                "recommendation": "Limit alcohol intake. Monitor blood glucose.",
                "alternatives": []
            },
            ("glipizide", "fluconazole"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Increased hypoglycemia risk",
                "mechanism": "Fluconazole inhibits CYP2C9 metabolism of sulfonylureas",
                "recommendation": "Monitor blood glucose closely. May need dose reduction.",
                "alternatives": ["Different antifungal"]
            },
            ("insulin", "beta blockers"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Masked hypoglycemia symptoms, prolonged hypoglycemia",
                "mechanism": "Beta blockers mask tachycardia and tremor signs of hypoglycemia",
                "recommendation": "Use cardioselective beta blockers. Educate patient on alternative hypoglycemia signs.",
                "alternatives": ["Cardioselective beta blockers (metoprolol, atenolol)"]
            },
            
            # Cardiovascular interactions
            ("digoxin", "amiodarone"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Increased digoxin levels (50-100% increase), risk of toxicity",
                "mechanism": "Amiodarone inhibits P-glycoprotein and reduces renal clearance",
                "recommendation": "Reduce digoxin dose by 50%. Monitor digoxin levels and for toxicity signs.",
                "alternatives": []
            },
            ("digoxin", "verapamil"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Increased digoxin levels and enhanced AV block",
                "mechanism": "Verapamil inhibits P-glycoprotein; both cause AV nodal depression",
                "recommendation": "Reduce digoxin dose. Monitor heart rate and rhythm.",
                "alternatives": ["Diltiazem with caution"]
            },
            ("atenolol", "verapamil"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Severe bradycardia, heart block, hypotension",
                "mechanism": "Additive negative chronotropic and dromotropic effects",
                "recommendation": "Avoid combination. If necessary, use with extreme caution and monitoring.",
                "alternatives": ["Dihydropyridine calcium blockers (amlodipine)"]
            },
            ("lisinopril", "potassium"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Hyperkalemia risk",
                "mechanism": "ACE inhibitors reduce aldosterone, retaining potassium",
                "recommendation": "Monitor potassium levels. Avoid potassium supplements unless hypokalemic.",
                "alternatives": []
            },
            ("lisinopril", "spironolactone"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Significant hyperkalemia risk",
                "mechanism": "Both drugs cause potassium retention",
                "recommendation": "Monitor potassium closely. Consider lower doses. Check renal function.",
                "alternatives": ["Thiazide diuretics"]
            },
            ("amlodipine", "simvastatin"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Increased simvastatin levels, higher myopathy risk",
                "mechanism": "Amlodipine inhibits CYP3A4 metabolism of simvastatin",
                "recommendation": "Limit simvastatin to 20mg daily with amlodipine.",
                "alternatives": ["Pravastatin", "Rosuvastatin"]
            },
            
            # Pain medication interactions
            ("tramadol", "ssri"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Serotonin syndrome risk, increased seizure risk",
                "mechanism": "Both drugs increase serotonin; tramadol lowers seizure threshold",
                "recommendation": "Avoid combination if possible. Monitor for serotonin syndrome symptoms.",
                "alternatives": ["Non-serotonergic analgesics"]
            },
            ("tramadol", "maoi"): {
                "severity": InteractionSeverity.CRITICAL,
                "effect": "Life-threatening serotonin syndrome",
                "mechanism": "MAOIs potentiate serotonergic effects of tramadol",
                "recommendation": "CONTRAINDICATED. Do not use within 14 days of MAOI.",
                "alternatives": ["Non-opioid analgesics"]
            },
            ("codeine", "paroxetine"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Reduced analgesic effect of codeine",
                "mechanism": "Paroxetine inhibits CYP2D6 conversion of codeine to morphine",
                "recommendation": "Consider alternative analgesic or antidepressant.",
                "alternatives": ["Morphine", "Oxycodone"]
            },
            
            # Psychiatric medication interactions
            ("lithium", "ibuprofen"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Increased lithium levels, toxicity risk",
                "mechanism": "NSAIDs reduce renal lithium clearance",
                "recommendation": "Avoid NSAIDs. Monitor lithium levels if necessary.",
                "alternatives": ["Acetaminophen"]
            },
            ("lithium", "ace inhibitors"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Increased lithium levels",
                "mechanism": "ACE inhibitors reduce lithium clearance",
                "recommendation": "Monitor lithium levels closely. May need dose reduction.",
                "alternatives": []
            },
            ("ssri", "maoi"): {
                "severity": InteractionSeverity.CRITICAL,
                "effect": "Life-threatening serotonin syndrome",
                "mechanism": "Massive serotonin accumulation",
                "recommendation": "CONTRAINDICATED. Wait 2-5 weeks between switching medications.",
                "alternatives": []
            },
            
            # Antifungal interactions
            ("ketoconazole", "simvastatin"): {
                "severity": InteractionSeverity.CRITICAL,
                "effect": "Severe myopathy and rhabdomyolysis risk",
                "mechanism": "Ketoconazole strongly inhibits CYP3A4 metabolism of statins",
                "recommendation": "CONTRAINDICATED. Hold statin during antifungal treatment.",
                "alternatives": ["Fluconazole with pravastatin", "Topical antifungals"]
            },
            ("fluconazole", "warfarin"): {
                "severity": InteractionSeverity.HIGH,
                "effect": "Increased INR and bleeding risk",
                "mechanism": "Fluconazole inhibits CYP2C9 metabolism of warfarin",
                "recommendation": "Monitor INR closely. May need warfarin dose reduction.",
                "alternatives": []
            },
            
            # Proton pump inhibitor interactions
            ("omeprazole", "clopidogrel"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Reduced antiplatelet effect of clopidogrel",
                "mechanism": "Omeprazole inhibits CYP2C19 activation of clopidogrel",
                "recommendation": "Use pantoprazole or H2 blocker instead.",
                "alternatives": ["Pantoprazole", "Famotidine"]
            },
            ("omeprazole", "methotrexate"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Increased methotrexate levels",
                "mechanism": "PPIs inhibit renal elimination of methotrexate",
                "recommendation": "Consider temporary discontinuation of PPI with high-dose methotrexate.",
                "alternatives": ["H2 blockers"]
            },
            
            # Thyroid medication interactions
            ("levothyroxine", "calcium"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Reduced levothyroxine absorption",
                "mechanism": "Calcium binds to levothyroxine in GI tract",
                "recommendation": "Separate doses by 4 hours.",
                "alternatives": []
            },
            ("levothyroxine", "iron"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Reduced levothyroxine absorption",
                "mechanism": "Iron binds to levothyroxine",
                "recommendation": "Separate doses by 4 hours.",
                "alternatives": []
            },
            ("levothyroxine", "antacids"): {
                "severity": InteractionSeverity.MODERATE,
                "effect": "Reduced levothyroxine absorption",
                "mechanism": "Antacids alter GI pH and bind levothyroxine",
                "recommendation": "Separate doses by 4 hours.",
                "alternatives": []
            },
        }
        
        # =====================================================================
        # DRUG CLASS MAPPINGS
        # Map generic drug names to their classes for broader interaction checking
        # =====================================================================
        self.DRUG_CLASSES: Dict[str, List[str]] = {
            "ssri": ["fluoxetine", "sertraline", "paroxetine", "citalopram", "escitalopram", "fluvoxamine"],
            "maoi": ["phenelzine", "tranylcypromine", "isocarboxazid", "selegiline", "moclobemide"],
            "nsaid": ["ibuprofen", "naproxen", "diclofenac", "indomethacin", "piroxicam", "meloxicam", "celecoxib"],
            "ace_inhibitor": ["lisinopril", "enalapril", "ramipril", "captopril", "benazepril", "perindopril"],
            "arb": ["losartan", "valsartan", "irbesartan", "olmesartan", "candesartan", "telmisartan"],
            "beta_blocker": ["atenolol", "metoprolol", "propranolol", "carvedilol", "bisoprolol", "nebivolol"],
            "calcium_blocker": ["amlodipine", "verapamil", "diltiazem", "nifedipine", "felodipine"],
            "statin": ["atorvastatin", "simvastatin", "rosuvastatin", "pravastatin", "lovastatin", "fluvastatin"],
            "sulfonylurea": ["glipizide", "glyburide", "glimepiride", "glibenclamide"],
            "fluoroquinolone": ["ciprofloxacin", "levofloxacin", "moxifloxacin", "ofloxacin"],
            "macrolide": ["azithromycin", "clarithromycin", "erythromycin"],
            "antacid": ["aluminum hydroxide", "magnesium hydroxide", "calcium carbonate", "tums", "maalox"],
            "ppi": ["omeprazole", "esomeprazole", "pantoprazole", "lansoprazole", "rabeprazole"],
            "anticoagulant": ["warfarin", "heparin", "enoxaparin", "rivaroxaban", "apixaban", "dabigatran"],
            "antiplatelet": ["aspirin", "clopidogrel", "prasugrel", "ticagrelor"],
            "opioid": ["morphine", "codeine", "oxycodone", "hydrocodone", "fentanyl", "tramadol", "methadone"],
            "benzodiazepine": ["diazepam", "lorazepam", "alprazolam", "clonazepam", "midazolam"],
            "diuretic_potassium_sparing": ["spironolactone", "eplerenone", "amiloride", "triamterene"],
            "diuretic_loop": ["furosemide", "bumetanide", "torsemide"],
            "diuretic_thiazide": ["hydrochlorothiazide", "chlorthalidone", "indapamide", "metolazone"],
        }
        
        # Reverse mapping: drug name -> class
        self.DRUG_TO_CLASS: Dict[str, str] = {}
        for drug_class, drugs in self.DRUG_CLASSES.items():
            for drug in drugs:
                self.DRUG_TO_CLASS[drug.lower()] = drug_class
        
        # =====================================================================
        # ALLERGY CROSS-REACTIVITY DATABASE
        # Drugs that may cause reactions in patients with specific allergies
        # =====================================================================
        self.ALLERGY_CROSS_REACTIVITY: Dict[str, List[str]] = {
            "penicillin": ["amoxicillin", "ampicillin", "piperacillin", "cephalosporin", "cefazolin", 
                          "cephalexin", "ceftriaxone", "cefuroxime", "cefdinir"],
            "sulfa": ["sulfamethoxazole", "trimethoprim-sulfamethoxazole", "bactrim", "septra",
                     "sulfasalazine", "dapsone", "sulfadiazine"],
            "aspirin": ["ibuprofen", "naproxen", "diclofenac", "ketorolac", "indomethacin", "piroxicam"],
            "nsaid": ["aspirin", "ibuprofen", "naproxen", "diclofenac", "celecoxib"],
            "codeine": ["morphine", "hydrocodone", "oxycodone", "tramadol"],
            "morphine": ["codeine", "hydrocodone", "oxycodone", "fentanyl"],
            "iodine": ["contrast dye", "povidone-iodine", "amiodarone", "iodinated contrast"],
            "latex": [],  # Not medication-related but important
            "egg": ["propofol", "influenza vaccine"],
            "shellfish": [],  # Note: shellfish allergy is NOT a contraindication for iodinated contrast
        }
        
        # =====================================================================
        # CONDITION-BASED CONTRAINDICATIONS
        # Conditions that contraindicate certain medications
        # =====================================================================
        self.CONDITION_CONTRAINDICATIONS: Dict[str, List[Dict[str, Any]]] = {
            "renal failure": [
                {"drug_class": "nsaid", "severity": "high", "reason": "NSAIDs can worsen renal function"},
                {"drug": "metformin", "severity": "high", "reason": "Risk of lactic acidosis in renal impairment"},
                {"drug_class": "ace_inhibitor", "severity": "moderate", "reason": "May worsen renal function; monitor closely"},
            ],
            "liver disease": [
                {"drug": "acetaminophen", "severity": "high", "reason": "Hepatotoxicity risk; limit dose to 2g/day"},
                {"drug_class": "statin", "severity": "moderate", "reason": "May worsen liver function; monitor LFTs"},
            ],
            "heart failure": [
                {"drug_class": "nsaid", "severity": "high", "reason": "NSAIDs cause fluid retention and worsen heart failure"},
                {"drug_class": "calcium_blocker", "severity": "moderate", "reason": "Some CCBs have negative inotropic effects"},
                {"drug": "metformin", "severity": "moderate", "reason": "Risk in unstable or acute heart failure"},
            ],
            "asthma": [
                {"drug_class": "beta_blocker", "severity": "high", "reason": "Can trigger bronchospasm"},
                {"drug": "aspirin", "severity": "moderate", "reason": "May trigger aspirin-sensitive asthma"},
            ],
            "peptic ulcer": [
                {"drug_class": "nsaid", "severity": "high", "reason": "Increases GI bleeding risk"},
                {"drug": "aspirin", "severity": "high", "reason": "Increases GI bleeding risk"},
            ],
            "diabetes": [
                {"drug_class": "beta_blocker", "severity": "moderate", "reason": "Can mask hypoglycemia symptoms"},
            ],
            "pregnancy": [
                {"drug_class": "ace_inhibitor", "severity": "critical", "reason": "Teratogenic; contraindicated in pregnancy"},
                {"drug_class": "arb", "severity": "critical", "reason": "Teratogenic; contraindicated in pregnancy"},
                {"drug": "methotrexate", "severity": "critical", "reason": "Abortifacient and teratogenic"},
                {"drug": "warfarin", "severity": "critical", "reason": "Teratogenic, especially in first trimester"},
                {"drug_class": "statin", "severity": "critical", "reason": "Contraindicated in pregnancy"},
            ],
            "breastfeeding": [
                {"drug": "methotrexate", "severity": "critical", "reason": "Excreted in breast milk; contraindicated"},
                {"drug": "lithium", "severity": "high", "reason": "Excreted in breast milk; avoid if possible"},
            ],
        }
        
        logger.info("MedicationInteractionService initialized with comprehensive drug database")
    
    def _normalize_drug_name(self, drug_name: str) -> str:
        """Normalize drug name for matching"""
        # Convert to lowercase and remove common suffixes
        normalized = drug_name.lower().strip()
        
        # Remove common suffixes and prefixes
        suffixes_to_remove = [" tablets", " capsules", " mg", " ml", " injection", " syrup", " cream"]
        for suffix in suffixes_to_remove:
            normalized = normalized.replace(suffix, "")
        
        # Remove dosage numbers
        normalized = re.sub(r'\d+\.?\d*\s*(mg|ml|mcg|g|units?)?', '', normalized).strip()
        
        return normalized
    
    def _extract_drug_names(self, medication_text: str) -> List[str]:
        """Extract individual drug names from a medication string"""
        if not medication_text:
            return []
        
        # Split by common separators
        drugs = re.split(r'[,;\n]+', medication_text)
        
        extracted = []
        for drug in drugs:
            normalized = self._normalize_drug_name(drug)
            if normalized and len(normalized) > 2:  # Filter out very short strings
                extracted.append(normalized)
        
        return extracted
    
    def _get_drug_class(self, drug_name: str) -> Optional[str]:
        """Get the drug class for a given drug name"""
        normalized = self._normalize_drug_name(drug_name)
        return self.DRUG_TO_CLASS.get(normalized)
    
    async def check_drug_interactions(
        self,
        current_medications: List[str],
        new_medications: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Check for drug-drug interactions between current and new medications.
        
        Args:
            current_medications: List of current medication names
            new_medications: List of new medications to check
            
        Returns:
            List of interaction warnings
        """
        interactions = []
        
        # Normalize all drug names
        current_drugs = set()
        for med in current_medications:
            current_drugs.update(self._extract_drug_names(med))
        
        new_drugs = set()
        for med in new_medications:
            new_drugs.update(self._extract_drug_names(med))
        
        all_drugs = current_drugs.union(new_drugs)
        
        # Check each pair of drugs
        checked_pairs = set()
        
        for drug1 in all_drugs:
            for drug2 in all_drugs:
                if drug1 == drug2:
                    continue
                
                # Create sorted pair to avoid duplicate checks
                pair = tuple(sorted([drug1, drug2]))
                if pair in checked_pairs:
                    continue
                checked_pairs.add(pair)
                
                # Check direct interaction
                interaction = self._check_pair_interaction(drug1, drug2)
                if interaction:
                    interaction["drugs"] = [drug1, drug2]
                    interaction["is_new_medication"] = drug1 in new_drugs or drug2 in new_drugs
                    interactions.append(interaction)
                    continue
                
                # Check class-based interaction
                class1 = self._get_drug_class(drug1)
                class2 = self._get_drug_class(drug2)
                
                if class1:
                    class_interaction = self._check_pair_interaction(class1, drug2)
                    if class_interaction:
                        class_interaction["drugs"] = [drug1, drug2]
                        class_interaction["via_class"] = class1
                        class_interaction["is_new_medication"] = drug1 in new_drugs or drug2 in new_drugs
                        interactions.append(class_interaction)
                        continue
                
                if class2:
                    class_interaction = self._check_pair_interaction(drug1, class2)
                    if class_interaction:
                        class_interaction["drugs"] = [drug1, drug2]
                        class_interaction["via_class"] = class2
                        class_interaction["is_new_medication"] = drug1 in new_drugs or drug2 in new_drugs
                        interactions.append(class_interaction)
        
        # Sort by severity
        severity_order = {
            InteractionSeverity.CRITICAL: 0,
            InteractionSeverity.HIGH: 1,
            InteractionSeverity.MODERATE: 2,
            InteractionSeverity.LOW: 3,
            InteractionSeverity.UNKNOWN: 4
        }
        
        interactions.sort(key=lambda x: severity_order.get(x.get("severity"), 5))
        
        return interactions
    
    def _check_pair_interaction(self, drug1: str, drug2: str) -> Optional[Dict[str, Any]]:
        """Check if two drugs have a known interaction"""
        # Check both orderings
        key1 = (drug1.lower(), drug2.lower())
        key2 = (drug2.lower(), drug1.lower())
        
        interaction = self.DRUG_INTERACTIONS.get(key1) or self.DRUG_INTERACTIONS.get(key2)
        
        if interaction:
            return {
                "type": "drug_interaction",
                "severity": interaction["severity"].value if isinstance(interaction["severity"], InteractionSeverity) else interaction["severity"],
                "effect": interaction.get("effect", ""),
                "mechanism": interaction.get("mechanism", ""),
                "recommendation": interaction.get("recommendation", ""),
                "alternatives": interaction.get("alternatives", [])
            }
        
        return None
    
    async def check_allergy_conflicts(
        self,
        patient_allergies: str,
        medications: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Check for potential allergy conflicts with medications.
        
        Args:
            patient_allergies: Comma-separated string of patient allergies
            medications: List of medications to check
            
        Returns:
            List of allergy warnings
        """
        warnings = []
        
        if not patient_allergies:
            return warnings
        
        # Parse allergies
        allergies = [a.strip().lower() for a in patient_allergies.split(",") if a.strip()]
        
        # Extract all drug names from medications
        all_drugs = set()
        for med in medications:
            all_drugs.update(self._extract_drug_names(med))
        
        for allergy in allergies:
            # Direct allergy match
            for drug in all_drugs:
                if allergy in drug or drug in allergy:
                    warnings.append({
                        "type": "allergy_direct",
                        "severity": "critical",
                        "allergy": allergy,
                        "drug": drug,
                        "message": f"DIRECT ALLERGY CONFLICT: Patient is allergic to '{allergy}' and '{drug}' contains or is this substance",
                        "recommendation": "DO NOT PRESCRIBE - Patient has documented allergy"
                    })
            
            # Cross-reactivity check
            cross_reactive_drugs = self.ALLERGY_CROSS_REACTIVITY.get(allergy, [])
            for drug in all_drugs:
                for reactive in cross_reactive_drugs:
                    if reactive.lower() in drug or drug in reactive.lower():
                        warnings.append({
                            "type": "allergy_cross_reactivity",
                            "severity": "high",
                            "allergy": allergy,
                            "drug": drug,
                            "related_to": reactive,
                            "message": f"CROSS-REACTIVITY WARNING: Patient is allergic to '{allergy}'. '{drug}' may cause cross-reactive allergy.",
                            "recommendation": f"Use with extreme caution. Consider alternative medication. Monitor for allergic reactions."
                        })
        
        return warnings
    
    async def check_condition_contraindications(
        self,
        patient_conditions: List[str],
        medications: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Check for contraindications based on patient conditions.
        
        Args:
            patient_conditions: List of patient medical conditions
            medications: List of medications to check
            
        Returns:
            List of contraindication warnings
        """
        warnings = []
        
        if not patient_conditions:
            return warnings
        
        # Normalize conditions
        conditions = [c.strip().lower() for c in patient_conditions if c.strip()]
        
        # Extract all drug names
        all_drugs = set()
        for med in medications:
            all_drugs.update(self._extract_drug_names(med))
        
        for condition in conditions:
            # Find matching condition contraindications
            contraindications = self.CONDITION_CONTRAINDICATIONS.get(condition, [])
            
            for contra in contraindications:
                for drug in all_drugs:
                    # Check specific drug
                    if "drug" in contra and contra["drug"].lower() in drug:
                        warnings.append({
                            "type": "condition_contraindication",
                            "severity": contra["severity"],
                            "condition": condition,
                            "drug": drug,
                            "reason": contra["reason"],
                            "recommendation": f"Review necessity of {drug} given patient's {condition}. {contra['reason']}"
                        })
                    
                    # Check drug class
                    elif "drug_class" in contra:
                        drug_class = self._get_drug_class(drug)
                        if drug_class == contra["drug_class"]:
                            warnings.append({
                                "type": "condition_contraindication",
                                "severity": contra["severity"],
                                "condition": condition,
                                "drug": drug,
                                "drug_class": drug_class,
                                "reason": contra["reason"],
                                "recommendation": f"Review necessity of {drug} ({drug_class}) given patient's {condition}. {contra['reason']}"
                            })
        
        return warnings
    
    async def comprehensive_medication_check(
        self,
        current_medications: List[str],
        new_medications: List[str],
        patient_allergies: str,
        patient_conditions: Optional[List[str]] = None,
        patient_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform comprehensive medication safety check.
        
        Args:
            current_medications: Current medications patient is taking
            new_medications: New medications being prescribed
            patient_allergies: Patient's known allergies
            patient_conditions: Patient's medical conditions
            patient_context: Full patient context for additional checks
            
        Returns:
            Comprehensive safety check results
        """
        results = {
            "drug_interactions": [],
            "allergy_warnings": [],
            "contraindications": [],
            "summary": {
                "critical_count": 0,
                "high_count": 0,
                "moderate_count": 0,
                "low_count": 0,
                "safe_to_prescribe": True
            },
            "recommendations": []
        }
        
        all_medications = current_medications + new_medications
        
        # Check drug interactions
        interactions = await self.check_drug_interactions(current_medications, new_medications)
        results["drug_interactions"] = interactions
        
        # Check allergy conflicts
        allergy_warnings = await self.check_allergy_conflicts(patient_allergies, all_medications)
        results["allergy_warnings"] = allergy_warnings
        
        # Check condition contraindications
        if patient_conditions:
            contraindications = await self.check_condition_contraindications(patient_conditions, all_medications)
            results["contraindications"] = contraindications
        
        # Additional checks from patient context
        if patient_context:
            # Extract conditions from medical history
            medical_history = patient_context.get("medical_history", "")
            if medical_history:
                history_conditions = self._extract_conditions_from_history(medical_history)
                if history_conditions:
                    additional_contra = await self.check_condition_contraindications(history_conditions, all_medications)
                    results["contraindications"].extend(additional_contra)
        
        # Count severities
        all_warnings = results["drug_interactions"] + results["allergy_warnings"] + results["contraindications"]
        
        for warning in all_warnings:
            severity = warning.get("severity", "low")
            if severity == "critical":
                results["summary"]["critical_count"] += 1
                results["summary"]["safe_to_prescribe"] = False
            elif severity == "high":
                results["summary"]["high_count"] += 1
            elif severity == "moderate":
                results["summary"]["moderate_count"] += 1
            else:
                results["summary"]["low_count"] += 1
        
        # Generate overall recommendations
        if results["summary"]["critical_count"] > 0:
            results["recommendations"].append({
                "priority": "critical",
                "message": "CRITICAL SAFETY CONCERNS DETECTED. Review and modify prescription before dispensing.",
                "action": "Do not prescribe without addressing critical warnings"
            })
        
        if results["summary"]["high_count"] > 0:
            results["recommendations"].append({
                "priority": "high",
                "message": "High-severity interactions detected. Close monitoring required if proceeding.",
                "action": "Consider alternatives or implement monitoring plan"
            })
        
        if results["allergy_warnings"]:
            results["recommendations"].append({
                "priority": "critical",
                "message": "Potential allergy conflicts identified. Verify allergy history with patient.",
                "action": "Confirm allergies and consider alternative medications"
            })
        
        return results
    
    def _extract_conditions_from_history(self, medical_history: str) -> List[str]:
        """Extract medical conditions from free-text medical history"""
        conditions = []
        
        history_lower = medical_history.lower()
        
        condition_keywords = {
            "renal failure": ["renal failure", "kidney failure", "ckd", "chronic kidney", "renal impairment", "kidney disease"],
            "liver disease": ["liver disease", "hepatic", "cirrhosis", "liver failure", "hepatitis"],
            "heart failure": ["heart failure", "chf", "congestive heart", "cardiac failure", "cardiomyopathy"],
            "asthma": ["asthma", "asthmatic", "bronchospasm"],
            "peptic ulcer": ["peptic ulcer", "gastric ulcer", "duodenal ulcer", "gi bleed", "ulcer disease"],
            "diabetes": ["diabetes", "diabetic", "dm type", "t2dm", "t1dm", "sugar"],
            "pregnancy": ["pregnant", "pregnancy", "gravid"],
            "breastfeeding": ["breastfeeding", "lactating", "nursing mother"],
        }
        
        for condition, keywords in condition_keywords.items():
            for keyword in keywords:
                if keyword in history_lower:
                    conditions.append(condition)
                    break
        
        return list(set(conditions))
    
    async def enhance_analysis_with_interactions(
        self,
        analysis_result: Dict[str, Any],
        patient_context: Dict[str, Any],
        visit_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Enhance AI analysis with medication interaction warnings.
        
        This integrates medication safety checking into the AI analysis workflow.
        
        Args:
            analysis_result: The structured AI analysis result
            patient_context: Patient information
            visit_context: Current visit context
            
        Returns:
            Enhanced analysis with medication warnings
        """
        # Extract current medications from patient context
        current_medications = []
        
        if patient_context.get("current_medications"):
            meds = patient_context.get("current_medications")
            if isinstance(meds, list):
                current_medications = meds
            else:
                current_medications = [meds]
        
        # Extract medications from visit context if available
        new_medications = []
        if visit_context:
            visit_meds = visit_context.get("medications", "")
            if visit_meds:
                new_medications = [visit_meds] if isinstance(visit_meds, str) else visit_meds
        
        # Extract medications from AI analysis (if handwritten prescription analysis)
        extracted_meds = []
        if "medications" in analysis_result:
            for med in analysis_result.get("medications", []):
                if isinstance(med, dict) and med.get("drug_name"):
                    extracted_meds.append(med["drug_name"])
                elif isinstance(med, str):
                    extracted_meds.append(med)
        
        new_medications.extend(extracted_meds)
        
        # Extract patient allergies
        allergies = patient_context.get("allergies", "")
        
        # Extract conditions from medical history
        medical_history = patient_context.get("medical_history", "")
        conditions = self._extract_conditions_from_history(medical_history)
        
        # Perform comprehensive check
        if current_medications or new_medications:
            safety_check = await self.comprehensive_medication_check(
                current_medications=current_medications,
                new_medications=new_medications,
                patient_allergies=allergies,
                patient_conditions=conditions,
                patient_context=patient_context
            )
            
            # Add to analysis result
            analysis_result["medication_safety_check"] = safety_check
            
            # Add warnings to critical findings if any
            critical_warnings = [w for w in safety_check.get("drug_interactions", []) 
                               if w.get("severity") in ["critical", "high"]]
            critical_warnings.extend([w for w in safety_check.get("allergy_warnings", [])])
            
            if critical_warnings and "critical_findings" not in analysis_result:
                analysis_result["critical_findings"] = []
            
            for warning in critical_warnings:
                analysis_result["critical_findings"].append({
                    "finding": warning.get("message") or warning.get("effect", "Medication safety concern"),
                    "urgency": "immediate" if warning.get("severity") == "critical" else "within_24_hours",
                    "recommended_action": warning.get("recommendation", "Review medication prescription"),
                    "parameter": "medication_interaction" if warning.get("type") == "drug_interaction" else "allergy_warning"
                })
        
        return analysis_result


# Singleton instance
_medication_service_instance: Optional[MedicationInteractionService] = None


def get_medication_service() -> MedicationInteractionService:
    """Get or create the medication interaction service singleton"""
    global _medication_service_instance
    if _medication_service_instance is None:
        _medication_service_instance = MedicationInteractionService()
    return _medication_service_instance
