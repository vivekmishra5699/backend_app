from supabase import Client
from typing import Optional, List, Dict, Any
import traceback
import asyncio
from datetime import datetime, timezone
from thread_pool_manager import get_executor
from optimized_cache import optimized_cache

class DatabaseManager:
    def __init__(self, supabase_client: Client, enable_cache: bool = True):
        self.supabase = supabase_client
        # Use unified thread pool instead of creating a new one
        self.executor = get_executor()
        self.cache = optimized_cache if enable_cache else None
        if self.cache:
            print("✅ Optimized query cache enabled (5000 entries, 200MB)")
    
    # Doctor related operations
    async def get_doctor_by_firebase_uid(self, firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Get doctor by Firebase UID (CACHED)"""
        try:
            # Check cache first
            if self.cache:
                cache_key = f"doctor_uid:{firebase_uid}"
                cached_result = await self.cache.get(cache_key)
                if cached_result is not None:
                    return cached_result
            
            print(f"Fetching doctor by Firebase UID: {firebase_uid}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("doctors").select("*").eq("firebase_uid", firebase_uid).execute()
            )
            print(f"Supabase response for UID lookup: {response}")
            
            result = response.data[0] if response.data else None
            
            # Cache result
            if self.cache and result:
                cache_key = f"doctor_uid:{firebase_uid}"
                await self.cache.set(cache_key, result, ttl=600)  # Cache for 10 minutes
            
            return result
        except Exception as e:
            print(f"Error fetching doctor by Firebase UID: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None
    
    async def get_doctor_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get doctor by email"""
        try:
            print(f"Fetching doctor by email: {email}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("doctors").select("*").eq("email", email).execute()
            )
            print(f"Supabase response for email lookup: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching doctor by email: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def create_doctor(self, doctor_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new doctor record"""
        try:
            print(f"Inserting doctor data to Supabase: {doctor_data}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("doctors").insert(doctor_data).execute()
            )
            print(f"Supabase insert response: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating doctor: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def update_doctor(self, firebase_uid: str, update_data: Dict[str, Any]) -> bool:
        """Update doctor profile and sync lab contacts"""
        try:
            # Update the main doctor profile
            response = await self.supabase.table("doctors").update(update_data).eq("firebase_uid", firebase_uid).execute()
            
            if not response.data:
                print(f"Warning: No doctor found with firebase_uid {firebase_uid} to update.")
                return False

            # Invalidate cache for the updated doctor
            if self.cache:
                await self.cache.delete(f"doctor_uid_{firebase_uid}")
                print(f"Cache invalidated for doctor_uid_{firebase_uid}")

            # If lab phone numbers are in the update, sync the lab_contacts table
            if 'pathology_lab_phone' in update_data:
                await self.create_or_update_lab_contact_from_profile(
                    doctor_firebase_uid=firebase_uid,
                    lab_type='pathology',
                    phone=update_data.get('pathology_lab_phone'),
                    name=update_data.get('pathology_lab_name')
                )
            
            if 'radiology_lab_phone' in update_data:
                await self.create_or_update_lab_contact_from_profile(
                    doctor_firebase_uid=firebase_uid,
                    lab_type='radiology',
                    phone=update_data.get('radiology_lab_phone'),
                    name=update_data.get('radiology_lab_name')
                )

            return True
        except Exception as e:
            print(f"Error updating doctor profile: {e}")
            return False

    async def create_or_update_lab_contact_from_profile(self, doctor_firebase_uid: str, lab_type: str, phone: Optional[str], name: Optional[str]):
        """
        Creates or updates a lab contact entry based on doctor's profile data.
        This is intended to keep the lab_contacts table in sync.
        """
        if not phone:
            # If the phone number is removed from the profile, we might want to deactivate or delete the lab contact.
            # For now, we'll just log it. A more robust implementation could handle this.
            print(f"Lab phone for {lab_type} was cleared for doctor {doctor_firebase_uid}. No action taken in lab_contacts.")
            return

        try:
            # Check if a lab contact already exists for this doctor and lab type
            existing_contact_response = await self.supabase.table("lab_contacts").select("id, contact_phone, lab_name").eq("doctor_firebase_uid", doctor_firebase_uid).eq("lab_type", lab_type).execute()
            
            update_data = {
                "contact_phone": phone,
                "lab_name": name or f"Default {lab_type.capitalize()} Lab",
                "is_active": True,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }

            if existing_contact_response.data:
                # Update the existing lab contact
                contact_id = existing_contact_response.data[0]['id']
                await self.supabase.table("lab_contacts").update(update_data).eq("id", contact_id).execute()
                print(f"Updated existing {lab_type} lab contact for doctor {doctor_firebase_uid}.")
            else:
                # Create a new lab contact
                insert_data = {
                    **update_data,
                    "doctor_firebase_uid": doctor_firebase_uid,
                    "lab_type": lab_type,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                await self.supabase.table("lab_contacts").insert(insert_data).execute()
                print(f"Created new {lab_type} lab contact for doctor {doctor_firebase_uid}.")

        except Exception as e:
            print(f"Error syncing {lab_type} lab contact for doctor {doctor_firebase_uid}: {e}")
            # We don't re-raise the exception to avoid failing the entire profile update

    async def delete_patient(self, patient_id: int, doctor_firebase_uid: str) -> bool:
        try:
            # First, verify the doctor owns the patient
            patient_response = await self.supabase.table("patients").select("id").eq("id", patient_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            if not patient_response.data:
                print(f"Unauthorized or patient not found: patient_id={patient_id}, doctor_uid={doctor_firebase_uid}")
                return False
            
            # If authorized, proceed with deletion
            response = await self.supabase.table("patients").delete().eq("id", patient_id).execute()
            
            if response.data:
                print(f"Patient with id {patient_id} deleted successfully.")
                return True
            else:
                print(f"Failed to delete patient with id {patient_id}.")
                return False
            
        except Exception as e:
            print(f"Error deleting patient: {e}")
            return False
    
    # Patient related operations
    async def get_patient_by_id(self, patient_id: int, doctor_firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Get patient by ID for a specific doctor"""
        try:
            print(f"Fetching patient by ID: {patient_id} for doctor: {doctor_firebase_uid}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("patients").select("*").eq("id", patient_id).eq("created_by_doctor", doctor_firebase_uid).execute()
            )
            print(f"Supabase response for patient lookup: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching patient by ID: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_patient_by_id_unrestricted(self, patient_id: int) -> Optional[Dict[str, Any]]:
        """Get patient by ID without doctor scoping (for pharmacy views)."""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("patients")
                .select("*")
                .eq("id", patient_id)
                .limit(1)
                .execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching patient by ID (unrestricted): {e}")
            return None

    async def get_all_patients_for_doctor(self, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all patients for a specific doctor"""
        try:
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("patients").select("*").eq("created_by_doctor", doctor_firebase_uid).order("created_at", desc=True).execute()
            )
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching patients: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return []

    async def create_patient(self, patient_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new patient record"""
        try:
            print(f"Inserting patient data to Supabase: {patient_data}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("patients").insert(patient_data).execute()
            )
            print(f"Supabase insert response: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating patient: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def update_patient(self, patient_id: int, doctor_firebase_uid: str, update_data: Dict[str, Any]) -> bool:
        """Update patient profile"""
        try:
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("patients").update(update_data).eq("id", patient_id).eq("created_by_doctor", doctor_firebase_uid).execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error updating patient: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return False

    # Visit related operations
    async def get_visits_by_patient_id(self, patient_id: int, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all visits for a patient by a specific doctor"""
        try:
            print(f"Fetching visits for patient: {patient_id} by doctor: {doctor_firebase_uid}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visits").select("*").eq("patient_id", patient_id).eq("doctor_firebase_uid", doctor_firebase_uid).order("visit_date", desc=True).execute()
            )
            print(f"Supabase response for visits lookup: {response}")
            
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching visits: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return []

    async def get_visit_by_id(self, visit_id: int, doctor_firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Get visit by ID for a specific doctor"""
        try:
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visits").select("*").eq("id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching visit: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def create_visit(self, visit_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new visit record"""
        try:
            print(f"Inserting visit data to Supabase: {visit_data}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visits").insert(visit_data).execute()
            )
            print(f"Supabase insert response: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating visit: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def update_visit(self, visit_id: int, doctor_firebase_uid: str, update_data: Dict[str, Any]) -> bool:
        """Update visit record"""
        try:
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visits").update(update_data).eq("id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error updating visit: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return False

    async def delete_visit(self, visit_id: int, doctor_firebase_uid: str) -> bool:
        """Delete visit record and all associated reports, AI analyses, and patient history analyses"""
        try:
            print(f"Deleting visit {visit_id} for doctor {doctor_firebase_uid}")
            
            loop = asyncio.get_event_loop()
            
            # Get the patient_id before deleting the visit (needed for cleanup)
            visit_data = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visits").select("patient_id").eq("id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            patient_id = visit_data.data[0]["patient_id"] if visit_data.data else None
            
            # Delete AI document analyses for this visit (if table exists)
            try:
                ai_analyses_response = await loop.run_in_executor(
                    self.executor, 
                    lambda: self.supabase.table("ai_document_analysis").delete().eq("visit_id", visit_id).execute()
                )
                print(f"Deleted {len(ai_analyses_response.data if ai_analyses_response.data else [])} AI document analyses")
            except Exception as ai_error:
                print(f"Note: Could not delete AI document analyses (table may not exist): {ai_error}")
            
            # Delete AI consolidated analyses for this visit (if table exists)
            try:
                consolidated_response = await loop.run_in_executor(
                    self.executor, 
                    lambda: self.supabase.table("ai_consolidated_analysis").delete().eq("visit_id", visit_id).execute()
                )
                print(f"Deleted {len(consolidated_response.data if consolidated_response.data else [])} AI consolidated analyses")
            except Exception as consolidated_error:
                print(f"Note: Could not delete AI consolidated analyses (table may not exist): {consolidated_error}")
            
            # Delete AI analysis queue entries for this visit (if table exists)
            try:
                queue_response = await loop.run_in_executor(
                    self.executor, 
                    lambda: self.supabase.table("ai_analysis_queue").delete().eq("visit_id", visit_id).execute()
                )
                print(f"Deleted {len(queue_response.data if queue_response.data else [])} AI analysis queue entries")
            except Exception as queue_error:
                print(f"Note: Could not delete AI analysis queue entries (table may not exist): {queue_error}")
            
            # Delete reports first (if table exists)
            try:
                reports_response = await loop.run_in_executor(
                    self.executor, 
                    lambda: self.supabase.table("reports").delete().eq("visit_id", visit_id).execute()
                )
                print(f"Deleted {len(reports_response.data if reports_response.data else [])} reports")
            except Exception as reports_error:
                print(f"Note: Could not delete reports (table may not exist): {reports_error}")
            
            # Delete upload links (if table exists)
            try:
                links_response = await loop.run_in_executor(
                    self.executor, 
                    lambda: self.supabase.table("upload_links").delete().eq("visit_id", visit_id).execute()
                )
                print(f"Deleted {len(links_response.data if links_response.data else [])} upload links")
            except Exception as links_error:
                print(f"Note: Could not delete upload links (table may not exist): {links_error}")
            
            # Finally delete the visit
            visit_response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visits").delete().eq("id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            
            if visit_response.data:
                print(f"Successfully deleted visit {visit_id}")
                
                # After successful visit deletion, clean up patient history analyses
                # since they are now based on outdated data
                if patient_id:
                    print(f"Cleaning up patient history analyses for patient {patient_id} due to visit deletion")
                    await self.delete_patient_history_analyses_by_patient(patient_id, doctor_firebase_uid)
                
                return True
            else:
                print(f"No visit found with id {visit_id} for doctor {doctor_firebase_uid}")
                return False
                
        except Exception as e:
            print(f"Error deleting visit: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return False

    # Utility methods
    async def test_connection(self) -> Dict[str, Any]:
        """Test database connection"""
        try:
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("doctors").select("id").limit(1).execute()
            )
            return {
                "status": "success",
                "message": "Database connection OK",
                "data": response.data
            }
        except Exception as e:
            return {
                "status": "error", 
                "message": f"Database connection failed: {str(e)}",
                "traceback": traceback.format_exc()
            }

    async def get_patient_with_visits(self, patient_id: int, doctor_firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Get patient with all their visits"""
        try:
            # Get patient data
            patient = await self.get_patient_by_id(patient_id, doctor_firebase_uid)
            if not patient:
                return None
            
            # Get visits
            visits = await self.get_visits_by_patient_id(patient_id, doctor_firebase_uid)
            
            return {
                "patient": patient,
                "visits": visits
            }
        except Exception as e:
            print(f"Error fetching patient with visits: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    # AI Analysis related operations
    async def create_ai_analysis(self, analysis_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new AI document analysis record"""
        try:
            print(f"Creating AI analysis: {analysis_data}")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("ai_document_analysis").insert(analysis_data).execute()
            )
            print(f"AI analysis creation response: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating AI analysis: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_ai_analysis_by_report_id(self, report_id: int, doctor_firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Get AI analysis for a specific report"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("ai_document_analysis").select("*").eq("report_id", report_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching AI analysis by report ID: {e}")
            return None

    async def get_ai_analyses_by_visit_id(self, visit_id: int, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all AI analyses for a visit"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("ai_document_analysis").select("*").eq("visit_id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).order("analyzed_at", desc=True).execute()
            )
            
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching AI analyses by visit ID: {e}")
            return []

    async def get_ai_analyses_by_patient_id(self, patient_id: int, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all AI analyses for a patient"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("ai_document_analysis").select("*").eq("patient_id", patient_id).eq("doctor_firebase_uid", doctor_firebase_uid).order("analyzed_at", desc=True).execute()
            )
            
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching AI analyses by patient ID: {e}")
            return []

    async def create_consolidated_analysis(self, analysis_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a consolidated AI analysis record"""
        try:
            print(f"Creating consolidated AI analysis: {analysis_data}")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("ai_consolidated_analysis").insert(analysis_data).execute()
            )
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating consolidated AI analysis: {e}")
            return None

    async def get_consolidated_analyses_by_visit_id(self, visit_id: int, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get consolidated AI analyses for a visit"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("ai_consolidated_analysis").select("*").eq("visit_id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).order("analyzed_at", desc=True).execute()
            )
            
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching consolidated AI analyses: {e}")
            return []

    async def queue_ai_analysis(self, queue_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Add an AI analysis task to the queue"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("ai_analysis_queue").insert(queue_data).execute()
            )
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error queueing AI analysis: {e}")
            return None

    async def get_pending_ai_analyses(self, doctor_firebase_uid: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get pending AI analysis tasks for a doctor"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("ai_analysis_queue").select("*").eq("doctor_firebase_uid", doctor_firebase_uid).eq("status", "pending").order("priority", desc=True).order("queued_at").limit(limit).execute()
            )
            
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching pending AI analyses: {e}")
            return []

    async def update_ai_analysis_queue_status(self, queue_id: int, status: str, error_message: str = None) -> bool:
        """Update the status of an AI analysis queue item"""
        try:
            update_data = {
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            if status == "processing":
                update_data["started_at"] = datetime.now(timezone.utc).isoformat()
            elif status in ["completed", "failed"]:
                update_data["completed_at"] = datetime.now(timezone.utc).isoformat()
            
            if error_message:
                update_data["error_message"] = error_message
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("ai_analysis_queue").update(update_data).eq("id", queue_id).execute()
            )
            
            return bool(response.data)
        except Exception as e:
            print(f"Error updating AI analysis queue status: {e}")
            return False

    async def get_ai_analysis_summary(self, doctor_firebase_uid: str, patient_id: int = None, visit_id: int = None) -> Dict[str, Any]:
        """Get AI analysis summary using the database function"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.rpc('get_ai_analysis_summary', {
                    'p_doctor_firebase_uid': doctor_firebase_uid,
                    'p_patient_id': patient_id,
                    'p_visit_id': visit_id
                }).execute()
            )
            
            if response.data and len(response.data) > 0:
                summary = response.data[0]
                return {
                    "analysis_count": summary.get("analysis_count", 0),
                    "latest_analysis_date": summary.get("latest_analysis_date"),
                    "avg_confidence_score": float(summary.get("avg_confidence_score", 0)) if summary.get("avg_confidence_score") else 0.0,
                    "pending_analyses": summary.get("pending_analyses", 0),
                    "failed_analyses": summary.get("failed_analyses", 0)
                }
            else:
                return {
                    "analysis_count": 0,
                    "latest_analysis_date": None,
                    "avg_confidence_score": 0.0,
                    "pending_analyses": 0,
                    "failed_analyses": 0
                }
        except Exception as e:
            print(f"Error getting AI analysis summary: {e}")
            return {
                "analysis_count": 0,
                "latest_analysis_date": None,
                "avg_confidence_score": 0.0,
                "pending_analyses": 0,
                "failed_analyses": 0
            }

    async def delete_ai_analyses_for_visit(self, visit_id: int, doctor_firebase_uid: str) -> int:
        """Delete all AI analyses for a visit and return count of deleted items"""
        try:
            total_deleted = 0
            loop = asyncio.get_event_loop();
            
            # Delete AI document analyses for this visit
            try:
                ai_analyses_response = await loop.run_in_executor(
                    self.executor, 
                    lambda: self.supabase.table("ai_document_analysis").delete().eq("visit_id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
                )
                deleted_count = len(ai_analyses_response.data if ai_analyses_response.data else [])
                total_deleted += deleted_count
                print(f"Deleted {deleted_count} AI document analyses for visit {visit_id}")
            except Exception as ai_error:
                print(f"Note: Could not delete AI document analyses: {ai_error}")
            
            # Delete AI consolidated analyses for this visit
            try:
                consolidated_response = await loop.run_in_executor(
                    self.executor, 
                    lambda: self.supabase.table("ai_consolidated_analysis").delete().eq("visit_id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
                )
                deleted_count = len(consolidated_response.data if consolidated_response.data else [])
                total_deleted += deleted_count
                print(f"Deleted {deleted_count} AI consolidated analyses for visit {visit_id}")
            except Exception as consolidated_error:
                print(f"Note: Could not delete AI consolidated analyses: {consolidated_error}")
            
            # Delete AI analysis queue entries for this visit
            try:
                queue_response = await loop.run_in_executor(
                    self.executor, 
                    lambda: self.supabase.table("ai_analysis_queue").delete().eq("visit_id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
                )
                deleted_count = len(queue_response.data if queue_response.data else [])
                total_deleted += deleted_count
                print(f"Deleted {deleted_count} AI analysis queue entries for visit {visit_id}")
            except Exception as queue_error:
                print(f"Note: Could not delete AI analysis queue entries: {queue_error}")
            
            return total_deleted
        except Exception as e:
            print(f"Error deleting AI analyses for visit: {e}")
            return 0

    def __del__(self):
        """Cleanup thread pool executor"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)

    # Report related operations
    async def create_report_upload_link(self, link_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a report upload link"""
        try:
            print(f"Creating report upload link: {link_data}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("report_upload_links").insert(link_data).execute()
            )
            print(f"Supabase insert response: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating report upload link: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_report_upload_link(self, upload_token: str) -> Optional[Dict[str, Any]]:
        """Get report upload link by token"""
        try:
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("report_upload_links").select("*").eq("upload_token", upload_token).execute()
            )
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching report upload link: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def create_report(self, report_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new report using the security definer function"""
        try:
            # Use the security definer function for report creation
            response = await asyncio.get_event_loop().run_in_executor(
                self.executor,
                lambda: self.supabase.rpc('upload_report_with_token', {
                    'p_visit_id': report_data['visit_id'],
                    'p_patient_id': report_data['patient_id'],
                    'p_doctor_firebase_uid': report_data['doctor_firebase_uid'],
                    'p_file_name': report_data['file_name'],
                    'p_file_size': report_data['file_size'],
                    'p_file_type': report_data['file_type'],
                    'p_file_url': report_data['file_url'],
                    'p_storage_path': report_data.get('storage_path'),
                    'p_test_type': report_data.get('test_type'),
                    'p_notes': report_data.get('notes'),
                    'p_upload_token': report_data['upload_token'],
                    'p_uploaded_at': report_data['uploaded_at'],
                    'p_created_at': report_data['created_at']
                }).execute()
            )
            
            if response.data:
                print(f"Report created via function: {response.data}")
                return response.data
            else:
                print(f"No data returned from upload_report_with_token function")
                return None
                
        except Exception as e:
            print(f"Error creating report via function: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def create_report_direct(self, report_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a report directly without token validation (for lab uploads)"""
        try:
            print(f"Creating report directly: {report_data}")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("reports").insert(report_data).execute()
            )
            print(f"Direct report creation response: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating report directly: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_report_by_id(self, report_id: int, doctor_firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Get a specific report by ID and doctor"""
        try:
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("reports").select("*").eq("id", report_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching report by ID: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_reports_by_visit_id(self, visit_id: int, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all reports for a visit"""
        try:
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("reports").select("*").eq("visit_id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).order("uploaded_at", desc=True).execute()
            )
            
            reports = response.data if response.data else []
            return [self._safe_report_data(report) for report in reports]
        except Exception as e:
            print(f"Error fetching reports: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return []

    async def get_reports_by_patient_id(self, patient_id: int, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all reports for a patient"""
        try:
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("reports").select("*").eq("patient_id", patient_id).eq("doctor_firebase_uid", doctor_firebase_uid).order("uploaded_at", desc=True).execute()
            )
            
            reports = response.data if response.data else []
            return [self._safe_report_data(report) for report in reports]
        except Exception as e:
            print(f"Error fetching patient reports: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return []

    async def delete_expired_upload_links(self) -> bool:
        """Delete expired upload links"""
        try:
            from datetime import datetime, timezone
            current_time = datetime.now(timezone.utc).isoformat()
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("report_upload_links").delete().lt("expires_at", current_time).execute()
            )
            
            return True
        except Exception as e:
            print(f"Error deleting expired upload links: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return False

    async def update_visit_billing(self, visit_id: int, doctor_firebase_uid: str, billing_data: Dict[str, Any]) -> bool:
        """Update billing information for a visit"""
        try:
            # Calculate total amount if not provided
            if "total_amount" not in billing_data:
                consultation_fee = billing_data.get("consultation_fee", 0) or 0
                additional_charges = billing_data.get("additional_charges", 0) or 0
                discount = billing_data.get("discount", 0) or 0
                billing_data["total_amount"] = max(0, consultation_fee + additional_charges - discount)
            
            # Add updated timestamp
            billing_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visits").update(billing_data).eq("id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error updating visit billing: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return False

    async def get_earnings_report(self, doctor_firebase_uid: str, start_date: str = None, end_date: str = None, payment_status: str = None, visit_type: str = None) -> Dict[str, Any]:
        """Get earnings report for a doctor with filters"""
        try:
            loop = asyncio.get_event_loop()
            
            # Build query
            query = self.supabase.table("visits").select("*").eq("doctor_firebase_uid", doctor_firebase_uid)
            
            # Apply filters
            if start_date:
                query = query.gte("visit_date", start_date)
            if end_date:
                query = query.lte("visit_date", end_date)
            if payment_status:
                query = query.eq("payment_status", payment_status)
            if visit_type:
                query = query.eq("visit_type", visit_type)
            
            response = await loop.run_in_executor(
                self.executor, 
                lambda: query.execute()
            )
            
            visits = response.data if response.data else []
            
            # Calculate statistics
            total_consultations = len(visits)
            paid_consultations = len([v for v in visits if v.get("payment_status") == "paid"])
            unpaid_consultations = len([v for v in visits if v.get("payment_status") in ["unpaid", None]])
            
            total_amount = sum(float(v.get("total_amount", 0) or 0) for v in visits)
            paid_amount = sum(float(v.get("total_amount", 0) or 0) for v in visits if v.get("payment_status") == "paid")
            unpaid_amount = sum(float(v.get("total_amount", 0) or 0) for v in visits if v.get("payment_status") in ["unpaid", None])
            
            average_per_consultation = total_amount / total_consultations if total_consultations > 0 else 0
            
            # Breakdown by payment method
            payment_method_breakdown = {}
            for visit in visits:
                if visit.get("payment_status") == "paid" and visit.get("payment_method"):
                    method = visit.get("payment_method")
                    amount = float(visit.get("total_amount", 0) or 0)
                    payment_method_breakdown[method] = payment_method_breakdown.get(method, 0) + amount
            
            # Breakdown by visit type
            visit_type_breakdown = {}
            for visit in visits:
                vtype = visit.get("visit_type", "Unknown")
                amount = float(visit.get("total_amount", 0) or 0)
                if vtype not in visit_type_breakdown:
                    visit_type_breakdown[vtype] = {"count": 0, "amount": 0}
                visit_type_breakdown[vtype]["count"] += 1
                visit_type_breakdown[vtype]["amount"] += amount
            
            return {
                "total_consultations": total_consultations,
                "paid_consultations": paid_consultations,
                "unpaid_consultations": unpaid_consultations,
                "total_amount": round(total_amount, 2),
                "paid_amount": round(paid_amount, 2),
                "unpaid_amount": round(unpaid_amount, 2),
                "average_per_consultation": round(average_per_consultation, 2),
                "breakdown_by_payment_method": payment_method_breakdown,
                "breakdown_by_visit_type": visit_type_breakdown,
                "visits": visits
            }
            
        except Exception as e:
            print(f"Error generating earnings report: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return {
                "total_consultations": 0,
                "paid_consultations": 0,
                "unpaid_consultations": 0,
                "total_amount": 0,
                "paid_amount": 0,
                "unpaid_amount": 0,
                "average_per_consultation": 0,
                "breakdown_by_payment_method": {},
                "breakdown_by_visit_type": {},
                "visits": []
            }

    async def get_daily_earnings(self, doctor_firebase_uid: str, date: str) -> Dict[str, Any]:
        """Get earnings for a specific date"""
        return await self.get_earnings_report(doctor_firebase_uid, date, date)

    async def get_monthly_earnings(self, doctor_firebase_uid: str, year: int, month: int) -> Dict[str, Any]:
        """Get earnings for a specific month"""
        start_date = f"{year}-{month:02d}-01"
        
        # Calculate last day of month
        if month == 12:
            next_month = f"{year + 1}-01-01"
        else:
            next_month = f"{year}-{month + 1:02d}-01"
        
        from datetime import datetime, timedelta
        last_day = datetime.strptime(next_month, "%Y-%m-%d") - timedelta(days=1)
        end_date = last_day.strftime("%Y-%m-%d")
        
        return await self.get_earnings_report(doctor_firebase_uid, start_date, end_date)

    async def get_yearly_earnings(self, doctor_firebase_uid: str, year: int) -> Dict[str, Any]:
        """Get earnings for a specific year"""
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        return await self.get_earnings_report(doctor_firebase_uid, start_date, end_date)

    async def get_pending_payments(self, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all visits with unpaid status"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visits").select("*, patients(first_name, last_name, phone)").eq("doctor_firebase_uid", doctor_firebase_uid).in_("payment_status", ["unpaid", "partially_paid"]).order("visit_date", desc=True).execute()
            )
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching pending payments: {e}")
            return []

    # PDF Template Management Methods
    async def create_pdf_template(self, template_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new PDF template"""
        try:
            print(f"Creating PDF template: {template_data}")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("pdf_templates").insert(template_data).execute()
            )
            print(f"PDF template creation response: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating PDF template: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_pdf_templates_by_doctor(self, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all PDF templates for a doctor"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("pdf_templates").select("*").eq("doctor_firebase_uid", doctor_firebase_uid).order("created_at", desc=True).execute()
            )
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching PDF templates: {e}")
            return []

    async def get_pdf_template_by_id(self, template_id: int, doctor_firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Get a specific PDF template by ID"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("pdf_templates").select("*").eq("id", template_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching PDF template by ID: {e}")
            return None

    async def update_pdf_template(self, template_id: int, doctor_firebase_uid: str, update_data: Dict[str, Any]) -> bool:
        """Update PDF template information"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("pdf_templates").update(update_data).eq("id", template_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error updating PDF template: {e}")
            return False

    async def delete_pdf_template(self, template_id: int, doctor_firebase_uid: str) -> bool:
        """Delete a PDF template"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("pdf_templates").delete().eq("id", template_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error deleting PDF template: {e}")
            return False

    # Visit Report Management Methods
    async def create_visit_report(self, report_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new visit report"""
        try:
            print(f"Creating visit report: {report_data}")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visit_reports").insert(report_data).execute()
            )
            print(f"Visit report creation response: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating visit report: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    def _safe_report_data(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure report data has safe values for null fields"""
        if not report:
            return report
        
        # Ensure string fields are never null
        safe_report = report.copy()
        
        # Required fields that should never be null (based on database schema)
        required_string_fields = ['file_name', 'file_url', 'file_type', 'uploaded_at']
        for field in required_string_fields:
            if field in safe_report and (safe_report[field] is None or safe_report[field] == ""):
                safe_report[field] = ""  # Provide empty string as fallback
        
        # Required numeric fields
        if 'file_size' in safe_report and safe_report['file_size'] is None:
            safe_report['file_size'] = 0
        
        # Optional string fields that can be empty
        optional_string_fields = ['storage_path', 'test_type', 'notes', 'created_at', 'generated_at', 'whatsapp_message_id']
        for field in optional_string_fields:
            if field in safe_report and safe_report[field] is None:
                safe_report[field] = ""
        
        # Ensure boolean fields have proper defaults
        if 'sent_via_whatsapp' in safe_report and safe_report['sent_via_whatsapp'] is None:
            safe_report['sent_via_whatsapp'] = False
            
        return safe_report

    async def get_visit_reports_by_visit_id(self, visit_id: int, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all visit reports for a specific visit"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visit_reports").select("*").eq("visit_id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).order("generated_at", desc=True).execute()
            )
            reports = response.data if response.data else []
            return [self._safe_report_data(report) for report in reports]
        except Exception as e:
            print(f"Error fetching visit reports by visit ID: {e}")
            return []

    async def get_visit_reports_by_patient_id(self, patient_id: int, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all visit reports for a specific patient"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visit_reports").select("*").eq("patient_id", patient_id).eq("doctor_firebase_uid", doctor_firebase_uid).order("generated_at", desc=True).execute()
            )
            reports = response.data if response.data else []
            return [self._safe_report_data(report) for report in reports]
        except Exception as e:
            print(f"Error fetching visit reports by patient ID: {e}")
            return []

    async def get_visit_report_by_id(self, report_id: int, doctor_firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Get a specific visit report by ID"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visit_reports").select("*").eq("id", report_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching visit report by ID: {e}")
            return None

    async def update_visit_report(self, report_id: int, update_data: Dict[str, Any]) -> bool:
        """Update visit report information"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visit_reports").update(update_data).eq("id", report_id).execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error updating visit report: {e}")
            return False

    async def delete_visit_report(self, report_id: int, doctor_firebase_uid: str) -> bool:
        """Delete a visit report"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("visit_reports").delete().eq("id", report_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error deleting visit report: {e}")
            return False

    # Patient History Analysis Operations
    async def create_patient_history_analysis(self, analysis_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new patient history analysis record"""
        try:
            print(f"🔍 Database: Inserting patient history analysis...")
            print(f"   Patient ID: {analysis_data.get('patient_id')}")
            print(f"   Doctor UID: {analysis_data.get('doctor_firebase_uid')}")
            print(f"   Raw analysis length: {len(analysis_data.get('raw_analysis', ''))}")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("patient_history_analysis").insert(analysis_data).execute()
            )
            
            print(f"📦 Supabase response: data={bool(response.data)}, count={getattr(response, 'count', None)}")
            
            if response.data:
                print(f"✅ Successfully inserted analysis with ID: {response.data[0].get('id')}")
                return response.data[0]
            else:
                print(f"❌ No data returned from insert operation")
                return None
        except Exception as e:
            print(f"❌ Error creating patient history analysis: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_latest_patient_history_analysis(self, patient_id: int, doctor_firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Get the latest comprehensive history analysis for a patient"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("patient_history_analysis").select("*").eq("patient_id", patient_id).eq("doctor_firebase_uid", doctor_firebase_uid).order("analyzed_at", desc=True).limit(1).execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching latest patient history analysis: {e}")
            return None

    async def get_patient_history_analyses(self, patient_id: int, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all comprehensive history analyses for a patient"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("patient_history_analysis").select("*").eq("patient_id", patient_id).eq("doctor_firebase_uid", doctor_firebase_uid).order("analyzed_at", desc=True).execute()
            )
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching patient history analyses: {e}")
            return []

    async def get_patient_history_analysis_by_id(self, analysis_id: int, doctor_firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Get a specific patient history analysis by ID"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("patient_history_analysis").select("*").eq("id", analysis_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching patient history analysis by ID: {e}")
            return None

    async def delete_patient_history_analysis(self, analysis_id: int, doctor_firebase_uid: str) -> bool:
        """Delete a patient history analysis record"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("patient_history_analysis").delete().eq("id", analysis_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            if response.data:
                print(f"Successfully deleted patient history analysis {analysis_id}")
                return True
            else:
                print(f"No patient history analysis found with id {analysis_id} for doctor {doctor_firebase_uid}")
                return False
        except Exception as e:
            print(f"Error deleting patient history analysis: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return False

    async def delete_patient_history_analyses_by_patient(self, patient_id: int, doctor_firebase_uid: str) -> bool:
        """Delete all patient history analyses for a specific patient"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("patient_history_analysis").delete().eq("patient_id", patient_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            deleted_count = len(response.data) if response.data else 0
            print(f"Successfully deleted {deleted_count} patient history analyses for patient {patient_id}")
            return True
        except Exception as e:
            print(f"Error deleting patient history analyses: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return False

    async def cleanup_outdated_patient_history_analyses(self, patient_id: int, doctor_firebase_uid: str) -> bool:
        """
        Clean up patient history analyses that may be outdated due to data changes.
        This should be called when visits or reports are added/deleted for a patient.
        """
        try:
            # Get current visit and report counts
            visits = await self.get_visits_by_patient_id(patient_id, doctor_firebase_uid)
            reports = await self.get_reports_by_patient_id(patient_id, doctor_firebase_uid)
            
            current_visit_count = len(visits) if visits else 0
            current_report_count = len(reports) if reports else 0
            
            # Get all existing analyses for this patient
            analyses = await self.get_patient_history_analyses(patient_id, doctor_firebase_uid)
            
            outdated_analyses = []
            for analysis in analyses:
                stored_visit_count = analysis.get("total_visits", 0)
                stored_report_count = analysis.get("total_reports", 0)
                
                # Check if the analysis is outdated
                if (stored_visit_count != current_visit_count or 
                    stored_report_count != current_report_count):
                    outdated_analyses.append(analysis["id"])
                    print(f"Analysis {analysis['id']} is outdated: visits {stored_visit_count}->{current_visit_count}, reports {stored_report_count}->{current_report_count}")
            
            # Delete outdated analyses
            for analysis_id in outdated_analyses:
                await self.delete_patient_history_analysis(analysis_id, doctor_firebase_uid)
            
            if outdated_analyses:
                print(f"Cleaned up {len(outdated_analyses)} outdated patient history analyses for patient {patient_id}")
            
            return True
        except Exception as e:
            print(f"Error cleaning up outdated patient history analyses: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return False

    async def cleanup_all_outdated_patient_history_analyses(self, doctor_firebase_uid: str) -> bool:
        """
        Clean up all outdated patient history analyses for a doctor.
        This can be run periodically to ensure data consistency.
        """
        try:
            print(f"Starting cleanup of all outdated patient history analyses for doctor {doctor_firebase_uid}")
            
            # Get all patients for this doctor
            patients = await self.get_all_patients_for_doctor(doctor_firebase_uid)
            
            total_cleaned = 0
            for patient in patients:
                patient_id = patient["id"]
                patient_name = f"{patient['first_name']} {patient['last_name']}"
                
                print(f"Checking patient {patient_id} ({patient_name})...")
                
                # Get current visit and report counts
                visits = await self.get_visits_by_patient_id(patient_id, doctor_firebase_uid)
                reports = await self.get_reports_by_patient_id(patient_id, doctor_firebase_uid)
                
                current_visit_count = len(visits) if visits else 0
                current_report_count = len(reports) if reports else 0
                
                # Get all existing analyses for this patient
                analyses = await self.get_patient_history_analyses(patient_id, doctor_firebase_uid)
                
                patient_outdated = 0
                for analysis in analyses:
                    stored_visit_count = analysis.get("total_visits", 0)
                    stored_report_count = analysis.get("total_reports", 0)
                    
                    # Check if the analysis is outdated
                    if (stored_visit_count != current_visit_count or 
                        stored_report_count != current_report_count):
                        print(f"  Deleting outdated analysis {analysis['id']}: visits {stored_visit_count}->{current_visit_count}, reports {stored_report_count}->{current_report_count}")
                        await self.delete_patient_history_analysis(analysis["id"], doctor_firebase_uid)
                        patient_outdated += 1
                        total_cleaned += 1
                
                if patient_outdated > 0:
                    print(f"  Cleaned up {patient_outdated} outdated analyses for patient {patient_name}")
                else:
                    print(f"  No outdated analyses found for patient {patient_name}")
            
            print(f"Cleanup completed. Total outdated analyses cleaned: {total_cleaned}")
            return True
            
        except Exception as e:
            print(f"Error cleaning up all outdated patient history analyses: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return False

    # Handwritten Visit Notes Operations
    async def create_handwritten_visit_note(self, note_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new handwritten visit note record"""
        try:
            print(f"Creating handwritten visit note: {note_data}")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("handwritten_visit_notes").insert(note_data).execute()
            )
            print(f"Handwritten visit note creation response: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating handwritten visit note: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_handwritten_visit_note_by_id(self, note_id: int, doctor_firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Get a handwritten visit note by ID"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("handwritten_visit_notes").select("*").eq("id", note_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error getting handwritten visit note by ID: {e}")
            return None

    async def get_handwritten_visit_notes_by_visit_id(self, visit_id: int, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all handwritten visit notes for a specific visit"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("handwritten_visit_notes").select("*").eq("visit_id", visit_id).eq("doctor_firebase_uid", doctor_firebase_uid).eq("is_active", True).order("created_at", desc=True).execute()
            )
            return response.data if response.data else []
        except Exception as e:
            print(f"Error getting handwritten visit notes by visit ID: {e}")
            return []

    async def get_handwritten_visit_notes_by_patient_id(self, patient_id: int, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all handwritten visit notes for a specific patient"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("handwritten_visit_notes").select("*").eq("patient_id", patient_id).eq("doctor_firebase_uid", doctor_firebase_uid).eq("is_active", True).order("created_at", desc=True).execute()
            )
            return response.data if response.data else []
        except Exception as e:
            print(f"Error getting handwritten visit notes by patient ID: {e}")
            return []

    async def update_handwritten_visit_note(self, note_id: int, doctor_firebase_uid: str, update_data: Dict[str, Any]) -> bool:
        """Update handwritten visit note information"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("handwritten_visit_notes").update(update_data).eq("id", note_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error updating handwritten visit note: {e}")
            return False

    async def delete_handwritten_visit_note(self, note_id: int, doctor_firebase_uid: str) -> bool:
        """Delete a handwritten visit note"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("handwritten_visit_notes").delete().eq("id", note_id).eq("doctor_firebase_uid", doctor_firebase_uid).execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error deleting handwritten visit note: {e}")
            return False

    async def get_handwritten_visit_notes_by_doctor(self, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all handwritten visit notes for a doctor"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("handwritten_visit_notes").select("*").eq("doctor_firebase_uid", doctor_firebase_uid).eq("is_active", True).order("created_at", desc=True).execute()
            )
            return response.data if response.data else []
        except Exception as e:
            print(f"Error getting handwritten visit notes by doctor: {e}")
            return []

    # Calendar Management Methods
    async def get_follow_up_appointments_by_month(self, doctor_firebase_uid: str, year: int, month: int) -> List[Dict[str, Any]]:
        """Get all follow-up appointments for a specific month"""
        try:
            # Calculate month boundaries
            from datetime import date, datetime
            start_date = date(year, month, 1)
            if month == 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, month + 1, 1)
            
            start_date_str = start_date.strftime('%Y-%m-%d')
            end_date_str = end_date.strftime('%Y-%m-%d')
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("visits")
                .select("""
                    id,
                    visit_id:id,
                    patient_id,
                    visit_date,
                    visit_type,
                    chief_complaint,
                    follow_up_date,
                    follow_up_time,
                    notes,
                    patients!inner(
                        first_name,
                        last_name,
                        phone
                    )
                """)
                .eq("doctor_firebase_uid", doctor_firebase_uid)
                .gte("follow_up_date", start_date_str)
                .lt("follow_up_date", end_date_str)
                .not_.is_("follow_up_date", "null")
                .order("follow_up_date", desc=False)
                .execute()
            )
            
            # Process the results to flatten the patient data
            appointments = []
            if response.data:
                for appointment in response.data:
                    patient = appointment.get("patients", {})
                    appointment_data = {
                        "visit_id": appointment["id"],
                        "patient_id": appointment["patient_id"],
                        "patient_first_name": patient.get("first_name", ""),
                        "patient_last_name": patient.get("last_name", ""),
                        "patient_phone": patient.get("phone"),
                        "visit_date": appointment["visit_date"],
                        "visit_type": appointment["visit_type"],
                        "chief_complaint": appointment["chief_complaint"],
                        "follow_up_date": appointment["follow_up_date"],
                        "follow_up_time": appointment.get("follow_up_time"),
                        "notes": appointment.get("notes")
                    }
                    appointments.append(appointment_data)
            
            return appointments
            
        except Exception as e:
            print(f"Error getting follow-up appointments by month: {e}")
            return []

    async def get_follow_up_appointments_by_date(self, doctor_firebase_uid: str, date: str) -> List[Dict[str, Any]]:
        """Get all follow-up appointments for a specific date"""
        try:
            print(f"Querying follow-up appointments for doctor {doctor_firebase_uid} on date {date}")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("visits")
                .select("""
                    id,
                    patient_id,
                    visit_date,
                    visit_type,
                    chief_complaint,
                    follow_up_date,
                    follow_up_time,
                    notes,
                    patients!inner(
                        first_name,
                        last_name,
                        phone
                    )
                """)
                .eq("doctor_firebase_uid", doctor_firebase_uid)
                .eq("follow_up_date", date)
                .not_.is_("follow_up_date", "null")
                .order("follow_up_time", desc=False)
                .execute()
            )
            
            print(f"Database response: {response.data}")
            
            # Process the results
            appointments = []
            if response.data:
                for appointment in response.data:
                    patient = appointment.get("patients")
                    if not patient:
                        print(f"Warning: No patient data found for visit {appointment['id']}")
                        continue
                        
                    appointment_data = {
                        "visit_id": appointment["id"],
                        "patient_id": appointment["patient_id"],
                        "patient_first_name": patient.get("first_name", ""),
                        "patient_last_name": patient.get("last_name", ""),
                        "patient_phone": patient.get("phone"),
                        "visit_date": appointment["visit_date"],
                        "visit_type": appointment["visit_type"],
                        "chief_complaint": appointment.get("chief_complaint", ""),
                        "follow_up_date": appointment["follow_up_date"],
                        "follow_up_time": appointment.get("follow_up_time"),
                        "notes": appointment.get("notes", "")
                    }
                    appointments.append(appointment_data)
            
            print(f"Processed {len(appointments)} appointments")
            return appointments
            
        except Exception as e:
            print(f"Error in get_follow_up_appointments_by_date: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return []
        except Exception as e:
            print(f"Error getting follow-up appointments by date: {e}")
            return []

    async def get_upcoming_follow_up_appointments(self, doctor_firebase_uid: str, days: int) -> List[Dict[str, Any]]:
        """Get upcoming follow-up appointments for the next N days"""
        try:
            from datetime import date, timedelta
            today = date.today()
            end_date = today + timedelta(days=days)
            
            today_str = today.strftime('%Y-%m-%d')
            end_date_str = end_date.strftime('%Y-%m-%d')
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("visits")
                .select("""
                    id,
                    visit_id:id,
                    patient_id,
                    visit_date,
                    visit_type,
                    chief_complaint,
                    follow_up_date,
                    follow_up_time,
                    notes,
                    patients!inner(
                        first_name,
                        last_name,
                        phone
                    )
                """)
                .eq("doctor_firebase_uid", doctor_firebase_uid)
                .gte("follow_up_date", today_str)
                .lte("follow_up_date", end_date_str)
                .not_.is_("follow_up_date", "null")
                .order("follow_up_date", desc=False)
                .order("follow_up_time", desc=False)
                .execute()
            )
            
            # Process the results
            appointments = []
            if response.data:
                for appointment in response.data:
                    patient = appointment.get("patients", {})
                    appointment_data = {
                        "visit_id": appointment["id"],
                        "patient_id": appointment["patient_id"],
                        "patient_first_name": patient.get("first_name", ""),
                        "patient_last_name": patient.get("last_name", ""),
                        "patient_phone": patient.get("phone"),
                        "visit_date": appointment["visit_date"],
                        "visit_type": appointment["visit_type"],
                        "chief_complaint": appointment["chief_complaint"],
                        "follow_up_date": appointment["follow_up_date"],
                        "follow_up_time": appointment.get("follow_up_time"),
                        "notes": appointment.get("notes")
                    }
                    appointments.append(appointment_data)
            
            return appointments
            
        except Exception as e:
            print(f"Error getting upcoming follow-up appointments: {e}")
            return []

    async def get_overdue_follow_up_appointments(self, doctor_firebase_uid: str) -> List[Dict[str, Any]]:
        """Get all overdue follow-up appointments"""
        try:
            from datetime import date
            today = date.today().strftime('%Y-%m-%d')
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("visits")
                .select("""
                    id,
                    visit_id:id,
                    patient_id,
                    visit_date,
                    visit_type,
                    chief_complaint,
                    follow_up_date,
                    follow_up_time,
                    notes,
                    patients!inner(
                        first_name,
                        last_name,
                        phone
                    )
                """)
                .eq("doctor_firebase_uid", doctor_firebase_uid)
                .lt("follow_up_date", today)
                .not_.is_("follow_up_date", "null")
                .order("follow_up_date", desc=False)
                .execute()
            )
            
            # Process the results
            appointments = []
            if response.data:
                for appointment in response.data:
                    patient = appointment.get("patients", {})
                    appointment_data = {
                        "visit_id": appointment["id"],
                        "patient_id": appointment["patient_id"],
                        "patient_first_name": patient.get("first_name", ""),
                        "patient_last_name": patient.get("last_name", ""),
                        "patient_phone": patient.get("phone"),
                        "visit_date": appointment["visit_date"],
                        "visit_type": appointment["visit_type"],
                        "chief_complaint": appointment["chief_complaint"],
                        "follow_up_date": appointment["follow_up_date"],
                        "follow_up_time": appointment.get("follow_up_time"),
                        "notes": appointment.get("notes")
                    }
                    appointments.append(appointment_data)
            
            return appointments
            
        except Exception as e:
            print(f"Error getting overdue follow-up appointments: {e}")
            return []

    async def get_follow_up_appointments_summary(self, doctor_firebase_uid: str) -> Dict[str, int]:
        """Get summary counts of follow-up appointments"""
        try:
            from datetime import date, timedelta, datetime
            import calendar
            
            today = date.today()
            week_end = today + timedelta(days=7)
            
            # Get current month boundaries
            month_start = today.replace(day=1)
            next_month = today.replace(day=28) + timedelta(days=4)
            month_end = next_month - timedelta(days=next_month.day)
            
            # Get next month boundaries
            next_month_start = (month_end + timedelta(days=1))
            if next_month_start.month == 12:
                next_month_end = date(next_month_start.year + 1, 1, 1) - timedelta(days=1)
            else:
                next_month_end = date(next_month_start.year, next_month_start.month + 1, 1) - timedelta(days=1)
            
            summary = {
                "today": 0,
                "this_week": 0,
                "this_month": 0,
                "next_month": 0,
                "overdue": 0
            }
            
            # Count today's appointments
            today_appointments = await self.get_follow_up_appointments_by_date(doctor_firebase_uid, today.strftime('%Y-%m-%d'))
            summary["today"] = len(today_appointments)
            
            # Count this week's appointments
            week_appointments = await self.get_upcoming_follow_up_appointments(doctor_firebase_uid, 7)
            summary["this_week"] = len(week_appointments)
            
            # Count this month's appointments
            month_appointments = await self.get_follow_up_appointments_by_month(doctor_firebase_uid, today.year, today.month)
            summary["this_month"] = len(month_appointments)
            
            # Count next month's appointments
            if next_month_start.month == 12:
                next_month_appointments = await self.get_follow_up_appointments_by_month(doctor_firebase_uid, next_month_start.year + 1, 1)
            else:
                next_month_appointments = await self.get_follow_up_appointments_by_month(doctor_firebase_uid, next_month_start.year, next_month_start.month)
            summary["next_month"] = len(next_month_appointments)
            
            # Count overdue appointments
            overdue_appointments = await self.get_overdue_follow_up_appointments(doctor_firebase_uid)
            summary["overdue"] = len(overdue_appointments)
            
            return summary

        except Exception as e:
            print(f"Error getting follow-up appointments summary: {e}")
            return {
                "today": 0,
                "this_week": 0,
                "this_month": 0,
                "next_month": 0,
                "overdue": 0
            }

    # Notification Management Methods
    async def create_notification(self, notification_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new notification for a doctor"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("notifications").insert(notification_data).execute()
            )
            
            if response.data:
                print(f"Notification created: {response.data[0]['id']}")
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating notification: {e}")
            return None

    async def get_doctor_notifications(self, doctor_firebase_uid: str, unread_only: bool = False, limit: int = 50) -> List[Dict[str, Any]]:
        """Get notifications for a doctor"""
        try:
            loop = asyncio.get_event_loop()
            
            query = self.supabase.table("notifications").select("*").eq("doctor_firebase_uid", doctor_firebase_uid)
            
            if unread_only:
                query = query.eq("is_read", False)
            
            response = await loop.run_in_executor(
                self.executor,
                lambda: query.order("created_at", desc=True).limit(limit).execute()
            )
            
            return response.data if response.data else []
        except Exception as e:
            print(f"Error getting notifications: {e}")
            return []

    async def mark_notification_as_read(self, notification_id: int, doctor_firebase_uid: str) -> bool:
        """Mark a notification as read"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("notifications")
                .update({"is_read": True, "read_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", notification_id)
                .eq("doctor_firebase_uid", doctor_firebase_uid)
                .execute()
            )
            
            return bool(response.data)
        except Exception as e:
            print(f"Error marking notification as read: {e}")
            return False

    async def mark_all_notifications_as_read(self, doctor_firebase_uid: str) -> bool:
        """Mark all notifications for a doctor as read"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("notifications")
                .update({"is_read": True, "read_at": datetime.now(timezone.utc).isoformat()})
                .eq("doctor_firebase_uid", doctor_firebase_uid)
                .eq("is_read", False)
                .execute()
            )
            
            return bool(response.data)
        except Exception as e:
            print(f"Error marking all notifications as read: {e}")
            return False

    async def get_unread_notification_count(self, doctor_firebase_uid: str) -> int:
        """Get count of unread notifications for a doctor"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("notifications")
                .select("id", count="exact")
                .eq("doctor_firebase_uid", doctor_firebase_uid)
                .eq("is_read", False)
                .execute()
            )
            
            return response.count if response.count is not None else 0
        except Exception as e:
            print(f"Error getting unread notification count: {e}")
            return 0

    async def delete_notification(self, notification_id: int, doctor_firebase_uid: str) -> bool:
        """Delete a notification"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("notifications")
                .delete()
                .eq("id", notification_id)
                .eq("doctor_firebase_uid", doctor_firebase_uid)
                .execute()
            )
            
            return bool(response.data)
        except Exception as e:
            print(f"Error deleting notification: {e}")
            return False

    # Lab Management Methods
    async def create_lab_contact(self, lab_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new lab contact"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("lab_contacts").insert(lab_data).execute()
            )
            
            if response.data:
                print(f"Lab contact created: {response.data[0]['id']}")
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating lab contact: {e}")
            return None

    async def get_doctor_lab_contacts(self, doctor_firebase_uid: str, lab_type: Optional[str] = None, active_only: bool = True) -> List[Dict[str, Any]]:
        """Get lab contacts for a doctor"""
        try:
            loop = asyncio.get_event_loop()
            
            query = self.supabase.table("lab_contacts").select("*").eq("doctor_firebase_uid", doctor_firebase_uid)
            
            if lab_type:
                query = query.eq("lab_type", lab_type)
            
            if active_only:
                query = query.eq("is_active", True)
            
            response = await loop.run_in_executor(
                self.executor,
                lambda: query.order("created_at", desc=True).execute()
            )
            
            return response.data if response.data else []
        except Exception as e:
            print(f"Error getting lab contacts: {e}")
            return []

    async def update_lab_contact(self, contact_id: int, doctor_firebase_uid: str, update_data: Dict[str, Any]) -> bool:
        """Update a lab contact"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("lab_contacts")
                .update(update_data)
                .eq("id", contact_id)
                .eq("doctor_firebase_uid", doctor_firebase_uid)
                .execute()
            )
            
            return bool(response.data)
        except Exception as e:
            print(f"Error updating lab contact: {e}")
            return False

    async def delete_lab_contact(self, contact_id: int, doctor_firebase_uid: str) -> bool:
        """Delete a lab contact"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("lab_contacts")
                .delete()
                .eq("id", contact_id)
                .eq("doctor_firebase_uid", doctor_firebase_uid)
                .execute()
            )
            
            return bool(response.data)
        except Exception as e:
            print(f"Error deleting lab contact: {e}")
            return False

    async def get_lab_contact_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Get lab contact by phone number (checks both profile contacts and lab_contacts table)"""
        try:
            loop = asyncio.get_event_loop()
            print(f"Looking for lab contact with phone: '{phone}'")
            
            # First check if this phone number exists in doctor profiles
            # Since .or_() is not available in all Supabase client versions, use separate queries
            
            # Check pathology lab phone
            pathology_response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("doctors")
                .select("firebase_uid, first_name, last_name, pathology_lab_name, pathology_lab_phone, radiology_lab_name, radiology_lab_phone")
                .eq("pathology_lab_phone", phone)
                .execute()
            )
            
            # Check radiology lab phone
            radiology_response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("doctors")
                .select("firebase_uid, first_name, last_name, pathology_lab_name, pathology_lab_phone, radiology_lab_name, radiology_lab_phone")
                .eq("radiology_lab_phone", phone)
                .execute()
            )
            
            # Combine results
            doctor_data = []
            if pathology_response.data:
                doctor_data.extend(pathology_response.data)
            if radiology_response.data:
                # Check if this doctor is already in the list (same firebase_uid)
                existing_uids = [d['firebase_uid'] for d in doctor_data]
                for doctor in radiology_response.data:
                    if doctor['firebase_uid'] not in existing_uids:
                        doctor_data.append(doctor)
            
            print(f"Doctor lookup response: {doctor_data}")
            
            if doctor_data:
                doctor = doctor_data[0]
                print(f"Found doctor: {doctor['first_name']}, pathology_phone: '{doctor.get('pathology_lab_phone')}', radiology_phone: '{doctor.get('radiology_lab_phone')}'")
                
                # Determine which lab type this phone number corresponds to
                lab_info = {
                    "id": f"profile_{doctor['firebase_uid']}",
                    "doctor_firebase_uid": doctor['firebase_uid'],
                    "doctor_name": f"{doctor['first_name']} {doctor['last_name']}",
                    "contact_phone": phone,
                    "is_active": True,
                    "source": "doctor_profile"
                }
                
                # Check if it's pathology contact
                if doctor.get('pathology_lab_phone') == phone:
                    print(f"Matched pathology phone: '{doctor.get('pathology_lab_phone')}' == '{phone}'")
                    lab_info.update({
                        "lab_type": "pathology",
                        "lab_name": doctor.get('pathology_lab_name', 'Pathology Lab'),
                    })
                # Check if it's radiology contact  
                elif doctor.get('radiology_lab_phone') == phone:
                    print(f"Matched radiology phone: '{doctor.get('radiology_lab_phone')}' == '{phone}'")
                    lab_info.update({
                        "lab_type": "radiology", 
                        "lab_name": doctor.get('radiology_lab_name', 'Radiology Lab'),
                    })
                # If same number for both, we need to handle this differently
                # For now, let's default to pathology and let the frontend handle it
                else:
                    print(f"No exact match found. Defaulting to both types.")
                    lab_info.update({
                        "lab_type": "both",  # Special case where same number handles both
                        "lab_name": doctor.get('pathology_lab_name', doctor.get('radiology_lab_name', 'Medical Lab')),
                        "pathology_name": doctor.get('pathology_lab_name'),
                        "radiology_name": doctor.get('radiology_lab_name')
                    })
                
                print(f"Returning lab_info: {lab_info}")
                return lab_info
            
            # If not found in doctor profiles, check lab_contacts table (legacy support)
            print(f"Doctor profile lookup returned no results, checking lab_contacts table...")
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("lab_contacts")
                .select("*")
                .eq("contact_phone", phone)
                .eq("is_active", True)
                .execute()
            )
            
            print(f"Lab contacts lookup response: {response.data if response else 'None'}")
            
            if response.data:
                lab_contact = response.data[0]
                lab_contact["source"] = "lab_contacts_table"
                print(f"Returning lab_contact from table: {lab_contact}")
                return lab_contact
            
            print(f"No lab contact found for phone: '{phone}'")
            return None
        except Exception as e:
            print(f"Error getting lab contact by phone: {e}")
            return None

    async def ensure_lab_contact_exists(self, doctor_uid: str, phone: str, lab_name: str, lab_type: str) -> Optional[int]:
        """
        Ensures a lab contact record exists for the given doctor and phone.
        Returns the ID of the existing or newly created contact.
        """
        try:
            # Check for existing contact
            existing_contacts = await self.get_doctor_lab_contacts(doctor_uid, active_only=False)
            matching_contact = next((c for c in existing_contacts if c["contact_phone"] == phone), None)
            
            if matching_contact:
                return matching_contact["id"]
            
            # Create new contact
            new_contact_data = {
                "doctor_firebase_uid": doctor_uid,
                "lab_type": lab_type,
                "lab_name": lab_name,
                "contact_phone": phone,
                "is_active": True
            }
            new_contact = await self.create_lab_contact(new_contact_data)
            if new_contact:
                print(f"Auto-created lab contact record for {lab_name} ({phone})")
                return new_contact["id"]
            
            return None
        except Exception as e:
            print(f"Error ensuring lab contact exists: {e}")
            return None

    async def create_lab_report_request(self, request_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a lab report upload request"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("lab_report_requests").insert(request_data).execute()
            )
            
            if response.data:
                print(f"Lab report request created: {response.data[0]['id']}")
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating lab report request: {e}")
            return None

    async def get_lab_report_requests_by_phone(self, phone: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get lab report requests for a lab contact by phone (supports both profile contacts and lab_contacts table)"""
        try:
            loop = asyncio.get_event_loop()
            
            # First, get all doctors who have this phone number in their profile
            doctors_response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("doctors")
                .select("firebase_uid, pathology_lab_phone, radiology_lab_phone")
                .or_(f"pathology_lab_phone.eq.{phone},radiology_lab_phone.eq.{phone}")
                .execute()
            )
            
            all_requests = []
            
            if doctors_response.data:
                # Get requests for doctors who have this phone number in their profile
                for doctor in doctors_response.data:
                    doctor_uid = doctor['firebase_uid']
                    
                    # Determine which lab types this phone number can handle for this doctor
                    lab_types = []
                    if doctor.get('pathology_lab_phone') == phone:
                        lab_types.append('pathology')
                    if doctor.get('radiology_lab_phone') == phone:
                        lab_types.append('radiology')
                    
                    # Build query for this doctor's requests
                    query = (self.supabase.table("lab_report_requests")
                            .select("""
                                *,
                                patients!inner(
                                    first_name,
                                    last_name,
                                    phone
                                ),
                                visits!inner(
                                    visit_date,
                                    visit_type,
                                    chief_complaint
                                )
                            """)
                            .eq("doctor_firebase_uid", doctor_uid))
                    
                    # Filter by lab types that this phone can handle
                    if len(lab_types) == 1:
                        query = query.eq("report_type", lab_types[0])
                    elif len(lab_types) > 1:
                        # Phone handles both types for this doctor
                        query = query.in_("report_type", lab_types)
                    
                    if status:
                        query = query.eq("status", status)
                    
                    response = await loop.run_in_executor(
                        self.executor,
                        lambda: query.order("created_at", desc=True).execute()
                    )
                    
                    if response.data:
                        # Add lab_types info to each request for context
                        for req in response.data:
                            req["available_lab_types"] = lab_types
                            req["contact_source"] = "doctor_profile"
                        all_requests.extend(response.data)
            
            # Also check legacy lab_contacts table
            lab_contact = await self.get_lab_contact_by_phone(phone)
            if lab_contact and lab_contact.get("source") == "lab_contacts_table":
                query = (self.supabase.table("lab_report_requests")
                        .select("""
                            *,
                            patients!inner(
                                first_name,
                                last_name,
                                phone
                            ),
                            visits!inner(
                                visit_date,
                                visit_type
                            )
                        """)
                        .eq("lab_contact_id", lab_contact["id"]))
                
                if status:
                    query = query.eq("status", status)
                
                response = await loop.run_in_executor(
                    self.executor,
                    lambda: query.order("created_at", desc=True).execute()
                )
                
                if response.data:
                    for req in response.data:
                        req["contact_source"] = "lab_contacts_table"
                    all_requests.extend(response.data)
            
            # Sort all requests by creation date
            all_requests.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            return all_requests
            
        except Exception as e:
            print(f"Error getting lab report requests: {e}")
            return []

    async def get_lab_report_requests_by_visit_id(self, visit_id: int) -> List[Dict[str, Any]]:
        """Get all lab report requests for a specific visit"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("lab_report_requests")
                .select("*")
                .eq("visit_id", visit_id)
                .order("created_at", desc=True)
                .execute()
            )
            
            return response.data if response.data else []
        except Exception as e:
            print(f"Error getting lab report requests by visit ID: {e}")
            return []

    async def get_lab_report_request_by_token(self, request_token: str) -> Optional[Dict[str, Any]]:
        """Get lab report request by token"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("lab_report_requests")
                .select("""
                    *,
                    patients!inner(
                        first_name,
                        last_name,
                        phone
                    ),
                    visits!inner(
                        visit_date,
                        visit_type,
                        chief_complaint
                    ),
                    lab_contacts(
                        lab_name,
                        lab_type,
                        contact_phone
                    )
                """)
                .eq("request_token", request_token)
                .execute()
            )
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error getting lab report request by token: {e}")
            return None

    async def update_lab_report_request_status(self, request_id: int, status: str, report_id: Optional[int] = None) -> bool:
        """Update lab report request status"""
        try:
            update_data = {
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            if report_id:
                update_data["report_id"] = report_id
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("lab_report_requests")
                .update(update_data)
                .eq("id", request_id)
                .execute()
            )
            
            return bool(response.data)
        except Exception as e:
            print(f"Error updating lab report request status: {e}")
            return False

    # Frontdesk User Management Methods
    async def create_frontdesk_user(self, frontdesk_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new frontdesk user record"""
        try:
            print(f"Inserting frontdesk user data to Supabase: {frontdesk_data}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("frontdesk_users").insert(frontdesk_data).execute()
            )
            print(f"Supabase frontdesk insert response: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating frontdesk user: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_frontdesk_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get frontdesk user by username"""
        try:
            print(f"Fetching frontdesk user by username: {username}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("frontdesk_users")
                .select("*")
                .eq("username", username)
                .eq("is_active", True)
                .execute()
            )
            print(f"Supabase response for username lookup: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching frontdesk user by username: {e}")
            return None

    async def get_frontdesk_user_by_id(self, frontdesk_id: int) -> Optional[Dict[str, Any]]:
        """Get frontdesk user by ID"""
        try:
            print(f"Fetching frontdesk user by ID: {frontdesk_id}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("frontdesk_users")
                .select("*")
                .eq("id", frontdesk_id)
                .eq("is_active", True)
                .execute()
            )
            print(f"Supabase response for frontdesk ID lookup: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching frontdesk user by ID: {e}")
            return None

    async def update_frontdesk_user(self, frontdesk_id: int, update_data: Dict[str, Any]) -> bool:
        """Update frontdesk user profile"""
        try:
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("frontdesk_users")
                .update(update_data)
                .eq("id", frontdesk_id)
                .execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error updating frontdesk user: {e}")
            return False

    async def deactivate_frontdesk_user(self, frontdesk_id: int) -> bool:
        """Deactivate frontdesk user (soft delete)"""
        try:
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("frontdesk_users")
                .update({"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", frontdesk_id)
                .execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error deactivating frontdesk user: {e}")
            return False

    # Pharmacy Management Methods
    async def create_pharmacy_user(self, pharmacy_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new pharmacy user record"""
        try:
            print(f"Inserting pharmacy user data to Supabase: {pharmacy_data}")
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_users").insert(pharmacy_data).execute()
            )
            print(f"Supabase pharmacy insert response: {response}")
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating pharmacy user: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_pharmacy_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get pharmacy user by username"""
        try:
            print(f"Fetching pharmacy user by username: {username}")
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_users")
                .select("*")
                .eq("username", username)
                .eq("is_active", True)
                .execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching pharmacy user by username: {e}")
            return None

    async def get_pharmacy_user_by_id(self, pharmacy_id: int) -> Optional[Dict[str, Any]]:
        """Get pharmacy user by ID"""
        try:
            print(f"Fetching pharmacy user by ID: {pharmacy_id}")
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_users")
                .select("*")
                .eq("id", pharmacy_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching pharmacy user by ID: {e}")
            return None

    async def update_pharmacy_user(self, pharmacy_id: int, update_data: Dict[str, Any]) -> bool:
        """Update pharmacy user profile"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_users")
                .update(update_data)
                .eq("id", pharmacy_id)
                .execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error updating pharmacy user: {e}")
            return False

    async def get_pharmacy_users_by_hospital(self, hospital_name: str) -> List[Dict[str, Any]]:
        """Get all active pharmacy users for a hospital"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_users")
                .select("*")
                .eq("hospital_name", hospital_name)
                .eq("is_active", True)
                .order("created_at", desc=False)
                .execute()
            )
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching pharmacy users by hospital: {e}")
            return []

    async def create_pharmacy_inventory_item(self, item_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new pharmacy inventory item"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_inventory").insert(item_data).execute()
            )
            if response.data:
                inserted = response.data[0]
                item_id = inserted.get("id")
                pharmacy_id = inserted.get("pharmacy_id") or item_data.get("pharmacy_id")
                if item_id and pharmacy_id:
                    return await self.get_pharmacy_inventory_item_by_id(pharmacy_id, item_id)
                return inserted
            return None
        except Exception as e:
            print(f"Error creating pharmacy inventory item: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_pharmacy_inventory_item_by_id(self, pharmacy_id: int, item_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific inventory item by ID"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_inventory")
                .select("*, supplier:pharmacy_suppliers!left(id,name,contact_person,phone,email)")
                .eq("id", item_id)
                .eq("pharmacy_id", pharmacy_id)
                .limit(1)
                .execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching pharmacy inventory item by ID: {e}")
            return None

    async def get_pharmacy_inventory_items(self, pharmacy_id: int) -> List[Dict[str, Any]]:
        """Get all inventory items for a pharmacy"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_inventory")
                .select("*, supplier:pharmacy_suppliers!left(id,name,contact_person,phone,email)")
                .eq("pharmacy_id", pharmacy_id)
                .order("medicine_name", desc=False)
                .execute()
            )
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching pharmacy inventory items: {e}")
            return []

    async def update_pharmacy_inventory_item(self, pharmacy_id: int, item_id: int, update_data: Dict[str, Any]) -> bool:
        """Update a pharmacy inventory item"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_inventory")
                .update(update_data)
                .eq("id", item_id)
                .eq("pharmacy_id", pharmacy_id)
                .execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error updating pharmacy inventory item: {e}")
            return False

    async def adjust_pharmacy_inventory_stock(self, pharmacy_id: int, item_id: int, quantity_delta: int) -> Optional[Dict[str, Any]]:
        """Adjust stock quantity for an inventory item"""
        try:
            item = await self.get_pharmacy_inventory_item_by_id(pharmacy_id, item_id)
            if not item:
                return None
            current_qty = item.get("stock_quantity", 0) or 0
            new_qty = current_qty + quantity_delta
            if new_qty < 0:
                new_qty = 0
            update_data = {
                "stock_quantity": new_qty,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            success = await self.update_pharmacy_inventory_item(pharmacy_id, item_id, update_data)
            if success:
                return await self.get_pharmacy_inventory_item_by_id(pharmacy_id, item_id)
            return None
        except Exception as e:
            print(f"Error adjusting pharmacy inventory stock: {e}")
            return None

    async def create_pharmacy_prescription(self, prescription_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a pharmacy prescription entry"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_prescriptions").insert(prescription_data).execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating pharmacy prescription: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_pharmacy_prescription_by_id(self, prescription_id: int) -> Optional[Dict[str, Any]]:
        """Get pharmacy prescription by ID"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_prescriptions")
                .select("*")
                .eq("id", prescription_id)
                .limit(1)
                .execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching pharmacy prescription by ID: {e}")
            return None

    async def get_pharmacy_prescription_by_visit(self, visit_id: int) -> Optional[Dict[str, Any]]:
        """Get pharmacy prescription by visit ID"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_prescriptions")
                .select("*")
                .eq("visit_id", visit_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching pharmacy prescription by visit: {e}")
            return None

    async def get_pharmacy_prescriptions(self, hospital_name: str, pharmacy_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get pharmacy prescriptions for a hospital (optionally filtered by pharmacy)"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_prescriptions")
                .select("*")
                .eq("hospital_name", hospital_name)
                .order("created_at", desc=True)
                .execute()
            )
            prescriptions = response.data if response.data else []
            if pharmacy_id is not None:
                filtered = []
                for prescription in prescriptions:
                    if prescription.get("pharmacy_id") is None or prescription.get("pharmacy_id") == pharmacy_id:
                        filtered.append(prescription)
                prescriptions = filtered
            return prescriptions
        except Exception as e:
            print(f"Error fetching pharmacy prescriptions: {e}")
            return []

    async def update_pharmacy_prescription(self, prescription_id: int, update_data: Dict[str, Any]) -> bool:
        """Update pharmacy prescription"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_prescriptions")
                .update(update_data)
                .eq("id", prescription_id)
                .execute()
            )
            return bool(response.data)
        except Exception as e:
            print(f"Error updating pharmacy prescription: {e}")
            return False

    async def create_pharmacy_invoice(self, invoice_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a pharmacy invoice"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_invoices").insert(invoice_data).execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating pharmacy invoice: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_pharmacy_invoices_by_pharmacy(self, pharmacy_id: int) -> List[Dict[str, Any]]:
        """Get invoices for a pharmacy"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_invoices")
                .select("*")
                .eq("pharmacy_id", pharmacy_id)
                .order("generated_at", desc=True)
                .execute()
            )
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching pharmacy invoices: {e}")
            return []

    async def get_pharmacy_invoice_summary(self, pharmacy_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        """Get aggregated invoice summary for a pharmacy"""
        try:
            invoices = await self.get_pharmacy_invoices_by_pharmacy(pharmacy_id)
            if start_date or end_date:
                filtered = []
                for invoice in invoices:
                    generated_at = invoice.get("generated_at")
                    if not generated_at:
                        continue
                    date_str = generated_at[:10]
                    if start_date and date_str < start_date:
                        continue
                    if end_date and date_str > end_date:
                        continue
                    filtered.append(invoice)
                invoices = filtered

            total_sales = 0.0
            total_paid = 0.0
            pending_amount = 0.0
            paid_invoices = 0
            for invoice in invoices:
                amount = float(invoice.get("total_amount", 0) or 0)
                total_sales += amount
                status = invoice.get("status", "unpaid")
                if status == "paid":
                    total_paid += amount
                    paid_invoices += 1
                else:
                    pending_amount += amount

            return {
                "invoice_count": len(invoices),
                "total_sales": round(total_sales, 2),
                "total_paid": round(total_paid, 2),
                "pending_amount": round(pending_amount, 2),
                "paid_invoices": paid_invoices
            }
        except Exception as e:
            print(f"Error generating pharmacy invoice summary: {e}")
            return {
                "invoice_count": 0,
                "total_sales": 0.0,
                "total_paid": 0.0,
                "pending_amount": 0.0,
                "paid_invoices": 0
            }

    async def get_pharmacy_suppliers(self, pharmacy_id: int) -> List[Dict[str, Any]]:
        """Get all suppliers for a pharmacy"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_suppliers")
                .select("*")
                .eq("pharmacy_id", pharmacy_id)
                .order("name", desc=False)
                .execute()
            )
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching pharmacy suppliers: {e}")
            return []

    async def get_pharmacy_supplier_by_id(self, pharmacy_id: int, supplier_id: int) -> Optional[Dict[str, Any]]:
        """Get a supplier record by ID"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_suppliers")
                .select("*")
                .eq("pharmacy_id", pharmacy_id)
                .eq("id", supplier_id)
                .limit(1)
                .execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching pharmacy supplier by ID: {e}")
            return None

    async def create_pharmacy_supplier(self, supplier_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new pharmacy supplier"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_suppliers").insert(supplier_data).execute()
            )
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating pharmacy supplier: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def update_pharmacy_supplier(self, pharmacy_id: int, supplier_id: int, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update pharmacy supplier details and return updated record"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("pharmacy_suppliers")
                .update(update_data)
                .eq("pharmacy_id", pharmacy_id)
                .eq("id", supplier_id)
                .execute()
            )
            return await self.get_pharmacy_supplier_by_id(pharmacy_id, supplier_id)
        except Exception as e:
            print(f"Error updating pharmacy supplier: {e}")
            return None

    # Hospital-based queries for frontdesk users
    async def get_doctors_by_hospital(self, hospital_name: str) -> List[Dict[str, Any]]:
        """Get all doctors for a specific hospital (CACHED)"""
        try:
            print(f"Fetching doctors for hospital: {hospital_name}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("doctors")
                .select("*")
                .eq("hospital_name", hospital_name)
                .execute()
            )
            print(f"Supabase response for doctors by hospital: {response}")
            
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching doctors by hospital: {e}")
            return []

    async def get_patients_by_hospital(self, hospital_name: str) -> List[Dict[str, Any]]:
        """Get all patients under doctors of a specific hospital"""
        try:
            print(f"Fetching patients for hospital: {hospital_name}")
            
            # First get all doctor firebase_uids for this hospital
            doctors = await self.get_doctors_by_hospital(hospital_name)
            if not doctors:
                print(f"No doctors found for hospital: {hospital_name}")
                return []
            
            doctor_uids = [doctor["firebase_uid"] for doctor in doctors]
            print(f"Found {len(doctor_uids)} doctors for hospital: {hospital_name}")
            
            # Get all patients created by these doctors
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("patients")
                .select("*")
                .in_("created_by_doctor", doctor_uids)
                .execute()
            )
            print(f"Supabase response for patients by hospital: found {len(response.data) if response.data else 0} patients")
            
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching patients by hospital: {e}")
            return []

    async def get_doctors_with_patient_count_by_hospital(self, hospital_name: str) -> List[Dict[str, Any]]:
        """Get doctors with their patient count for a specific hospital (OPTIMIZED - SINGLE QUERY)"""
        try:
            print(f"✅ Fetching doctors with patient count for hospital: {hospital_name} (optimized)")
            
            loop = asyncio.get_event_loop()
            
            try:
                # Use optimized RPC function - single query with JOIN and GROUP BY
                response = await loop.run_in_executor(
                    self.executor,
                    lambda: self.supabase.rpc('get_doctors_with_patient_counts', {
                        'hospital_name_param': hospital_name
                    }).execute()
                )
                
                if response.data:
                    print(f"✅ Found {len(response.data)} doctors with counts using optimized function (1 query)")
                    return response.data
                else:
                    print(f"No doctors found for hospital: {hospital_name}")
                    return []
                    
            except Exception as rpc_error:
                # Fallback to old method if RPC function doesn't exist
                print(f"⚠️ RPC function not available, using fallback (N+1 method): {rpc_error}")
                
                # Get doctors for the hospital
                doctors = await self.get_doctors_by_hospital(hospital_name)
                if not doctors:
                    return []
                
                doctor_uids = [doctor["firebase_uid"] for doctor in doctors]
                
                # Fetch all patients in one query
                patients_response = await loop.run_in_executor(
                    self.executor,
                    lambda: self.supabase.table("patients")
                    .select("created_by_doctor")
                    .in_("created_by_doctor", doctor_uids)
                    .execute()
                )
                
                # Count patients per doctor in Python
                patient_count_map = {}
                if patients_response.data:
                    for patient in patients_response.data:
                        doctor_uid = patient['created_by_doctor']
                        patient_count_map[doctor_uid] = patient_count_map.get(doctor_uid, 0) + 1
                    print(f"Counted {len(patients_response.data)} patients using fallback method")
                
                # Add patient counts to doctor info
                doctors_with_counts = []
                for doctor in doctors:
                    doctor_with_count = doctor.copy()
                    doctor_with_count["patient_count"] = patient_count_map.get(doctor["firebase_uid"], 0)
                    doctors_with_counts.append(doctor_with_count)
                
                print(f"Found {len(doctors_with_counts)} doctors with patient counts (fallback)")
                return doctors_with_counts
            
        except Exception as e:
            print(f"❌ Error fetching doctors with patient count: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return []

    async def get_patients_with_doctor_info_by_hospital(self, hospital_name: str) -> List[Dict[str, Any]]:
        """Get patients with their doctor information for a specific hospital (OPTIMIZED - SINGLE QUERY)"""
        try:
            print(f"✅ Fetching patients with doctor info for hospital: {hospital_name} (optimized)")
            
            loop = asyncio.get_event_loop()
            
            try:
                # Use optimized RPC function - single query with JOIN
                response = await loop.run_in_executor(
                    self.executor,
                    lambda: self.supabase.rpc('get_patients_with_doctor_info', {
                        'hospital_name_param': hospital_name
                    }).execute()
                )
                
                if response.data:
                    # Transform the data to include doctor_name field
                    patients_with_doctor_info = []
                    for patient in response.data:
                        # The function returns doctor_name already, but ensure backward compatibility
                        patient_data = dict(patient)
                        if 'doctor_name' not in patient_data:
                            patient_data['doctor_name'] = f"{patient.get('doctor_first_name', '')} {patient.get('doctor_last_name', '')}".strip()
                        patient_data['doctor_specialization'] = patient.get('doctor_specialization', '')
                        patient_data['doctor_phone'] = patient.get('doctor_phone', '')
                        patients_with_doctor_info.append(patient_data)
                    
                    print(f"✅ Found {len(patients_with_doctor_info)} patients with doctor info using optimized function (1 query)")
                    return patients_with_doctor_info
                else:
                    print(f"No patients found for hospital: {hospital_name}")
                    return []
                    
            except Exception as rpc_error:
                # Fallback to old method if RPC function doesn't exist
                print(f"⚠️ RPC function not available, using fallback (N+1 method): {rpc_error}")
                
                # Get all patients for this hospital
                patients = await self.get_patients_by_hospital(hospital_name)
                if not patients:
                    return []
                
                # Get all doctors for this hospital for lookup
                doctors = await self.get_doctors_by_hospital(hospital_name)
                doctor_lookup = {doctor["firebase_uid"]: doctor for doctor in doctors}
                
                # Add doctor info to each patient
                patients_with_doctor_info = []
                for patient in patients:
                    doctor_uid = patient.get("created_by_doctor")
                    doctor_info = doctor_lookup.get(doctor_uid)
                    
                    patient_with_doctor = patient.copy()
                    if doctor_info:
                        patient_with_doctor["doctor_name"] = f"{doctor_info.get('first_name', '')} {doctor_info.get('last_name', '')}".strip()
                        patient_with_doctor["doctor_specialization"] = doctor_info.get("specialization", "")
                        patient_with_doctor["doctor_phone"] = doctor_info.get("phone", "")
                    else:
                        patient_with_doctor["doctor_name"] = "Unknown"
                        patient_with_doctor["doctor_specialization"] = ""
                        patient_with_doctor["doctor_phone"] = ""
                    
                    patients_with_doctor_info.append(patient_with_doctor)
                
                print(f"Found {len(patients_with_doctor_info)} patients with doctor info (fallback)")
                return patients_with_doctor_info
            
        except Exception as e:
            print(f"❌ Error fetching patients with doctor info: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return []

    async def validate_doctor_belongs_to_hospital(self, doctor_firebase_uid: str, hospital_name: str) -> bool:
        """Validate that a doctor belongs to a specific hospital"""
        try:
            print(f"Validating doctor {doctor_firebase_uid} belongs to hospital: {hospital_name}")
            
            # Get doctor info
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("doctors")
                .select("hospital_name")
                .eq("firebase_uid", doctor_firebase_uid)
                .execute()
            )
            
            if not response.data:
                print(f"Doctor not found: {doctor_firebase_uid}")
                return False
            
            doctor_hospital = response.data[0].get("hospital_name")
            is_valid = doctor_hospital == hospital_name
            
            print(f"Doctor hospital: {doctor_hospital}, Required: {hospital_name}, Valid: {is_valid}")
            return is_valid
            
        except Exception as e:
            print(f"Error validating doctor hospital: {e}")
            return False

    async def validate_patient_belongs_to_hospital(self, patient_id: int, hospital_name: str) -> bool:
        """Validate that a patient belongs to a specific hospital (OPTIMIZED - single query)"""
        try:
            print(f"Validating patient {patient_id} belongs to hospital: {hospital_name}")
            
            loop = asyncio.get_event_loop()
            
            try:
                # Use optimized RPC function - single query with JOIN
                response = await loop.run_in_executor(
                    self.executor,
                    lambda: self.supabase.rpc('validate_patient_in_hospital', {
                        'patient_id_param': patient_id,
                        'hospital_name_param': hospital_name
                    }).execute()
                )
                
                is_valid = bool(response.data)
                print(f"✅ Patient {patient_id} validation result: {is_valid} (optimized - 1 query)")
                return is_valid
                
            except Exception as rpc_error:
                # Fallback to old method
                print(f"⚠️ RPC function not available, using fallback: {rpc_error}")
                
                # Join patient with doctor in a single query to get hospital
                response = await loop.run_in_executor(
                    self.executor,
                    lambda: self.supabase.table("patients")
                    .select("id, created_by_doctor")
                    .eq("id", patient_id)
                    .execute()
                )
                
                if not response.data:
                    print(f"Patient not found: {patient_id}")
                    return False
                
                patient = response.data[0]
                patient_doctor_uid = patient.get("created_by_doctor")
                
                # Now check if this doctor belongs to the hospital
                doctor_response = await loop.run_in_executor(
                    self.executor,
                    lambda: self.supabase.table("doctors")
                    .select("hospital_name")
                    .eq("firebase_uid", patient_doctor_uid)
                    .eq("hospital_name", hospital_name)
                    .execute()
                )
                
                is_valid = bool(doctor_response.data)
                print(f"Patient {patient_id} belongs to hospital {hospital_name}: {is_valid} (fallback)")
                return is_valid
            
        except Exception as e:
            print(f"❌ Error validating patient hospital: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return False

    async def get_hospital_dashboard_optimized(self, hospital_name: str, recent_limit: int = 10) -> Optional[Dict[str, Any]]:
        """Get complete hospital dashboard data in a SINGLE optimized query"""
        try:
            print(f"🚀 Fetching hospital dashboard for: {hospital_name} (ultra-optimized)")
            
            loop = asyncio.get_event_loop()
            
            try:
                # Use ultra-optimized RPC function - SINGLE query for entire dashboard!
                response = await loop.run_in_executor(
                    self.executor,
                    lambda: self.supabase.rpc('get_hospital_dashboard_data', {
                        'hospital_name_param': hospital_name,
                        'recent_limit': recent_limit
                    }).execute()
                )
                
                if response.data:
                    dashboard_data = response.data
                    print(f"✅ Hospital dashboard loaded in 1 query! Doctors: {dashboard_data.get('total_doctors')}, Patients: {dashboard_data.get('total_patients')}")
                    return dashboard_data
                else:
                    print(f"No dashboard data found for hospital: {hospital_name}")
                    return None
                    
            except Exception as rpc_error:
                # Fallback to old method if RPC function doesn't exist
                print(f"⚠️ RPC function not available, using fallback (multiple queries): {rpc_error}")
                return None  # Let the calling code handle fallback
            
        except Exception as e:
            print(f"❌ Error fetching hospital dashboard: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def create_patient_by_frontdesk(self, patient_data: Dict[str, Any], doctor_firebase_uid: str) -> Optional[Dict[str, Any]]:
        """Create a new patient record via frontdesk with assigned doctor"""
        try:
            print(f"Creating patient via frontdesk for doctor: {doctor_firebase_uid}")
            print(f"Patient data: {patient_data}")
            
            # Prepare patient data with the selected doctor
            patient_db_data = patient_data.copy()
            patient_db_data["created_by_doctor"] = doctor_firebase_uid
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("patients").insert(patient_db_data).execute()
            )
            print(f"Supabase patient insert response: {response}")
            
            if response.data:
                created_patient = response.data[0]
                
                # Get the doctor info to include in response
                doctor_info = await self.get_doctor_by_firebase_uid(doctor_firebase_uid)
                if doctor_info:
                    created_patient["doctor_name"] = f"{doctor_info.get('first_name', '')} {doctor_info.get('last_name', '')}".strip()
                    created_patient["doctor_specialization"] = doctor_info.get("specialization", "")
                    created_patient["doctor_phone"] = doctor_info.get("phone", "")
                else:
                    created_patient["doctor_name"] = "Unknown"
                    created_patient["doctor_specialization"] = ""
                    created_patient["doctor_phone"] = ""
                
                return created_patient
            
            return None
        except Exception as e:
            print(f"Error creating patient via frontdesk: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    # Appointment Management Methods
    async def create_appointment(self, appointment_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new appointment"""
        try:
            print(f"Creating appointment with data: {appointment_data}")
            
            # Run the synchronous Supabase call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor, 
                lambda: self.supabase.table("appointments").insert(appointment_data).execute()
            )
            print(f"Supabase appointment insert response: {response}")
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error creating appointment: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

    async def get_appointments_by_hospital_and_date_range(self, hospital_name: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Get appointments for all doctors in a hospital within date range"""
        try:
            print(f"Fetching appointments for hospital: {hospital_name} from {start_date} to {end_date}")
            
            # First get all doctors for this hospital
            doctors = await self.get_doctors_by_hospital(hospital_name)
            if not doctors:
                print(f"No doctors found for hospital: {hospital_name}")
                return []
            
            doctor_uids = [doctor["firebase_uid"] for doctor in doctors]
            print(f"Found {len(doctor_uids)} doctors for hospital: {hospital_name}")
            
            # Get appointments for these doctors within date range
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("appointments")
                .select("""
                    *, 
                    patients:patient_id(id, first_name, last_name, phone),
                    doctors:doctor_firebase_uid(firebase_uid, first_name, last_name, specialization, phone)
                """)
                .in_("doctor_firebase_uid", doctor_uids)
                .gte("appointment_date", start_date)
                .lte("appointment_date", end_date)
                .order("appointment_date", desc=False)
                .order("appointment_time", desc=False)
                .execute()
            )
            
            appointments = response.data if response.data else []
            print(f"Found {len(appointments)} appointments for hospital: {hospital_name}")
            
            # Enrich appointments with doctor and patient info
            enriched_appointments = []
            for apt in appointments:
                enriched_apt = apt.copy()
                
                # Add doctor info
                doctor_info = apt.get("doctors")
                if doctor_info:
                    enriched_apt["doctor_name"] = f"{doctor_info.get('first_name', '')} {doctor_info.get('last_name', '')}".strip()
                    enriched_apt["doctor_specialization"] = doctor_info.get("specialization", "")
                    enriched_apt["doctor_phone"] = doctor_info.get("phone", "")
                else:
                    enriched_apt["doctor_name"] = "Unknown Doctor"
                    enriched_apt["doctor_specialization"] = ""
                    enriched_apt["doctor_phone"] = ""
                
                # Add patient info
                patient_info = apt.get("patients")
                if patient_info:
                    enriched_apt["patient_name"] = f"{patient_info.get('first_name', '')} {patient_info.get('last_name', '')}".strip()
                    enriched_apt["patient_phone"] = patient_info.get("phone", "")
                else:
                    enriched_apt["patient_name"] = None
                    enriched_apt["patient_phone"] = None
                
                enriched_appointments.append(enriched_apt)
            
            return enriched_appointments
            
        except Exception as e:
            print(f"Error fetching hospital appointments: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return []

    async def get_appointments_by_doctor_and_date(self, doctor_firebase_uid: str, appointment_date: str) -> List[Dict[str, Any]]:
        """Get appointments for a specific doctor on a specific date"""
        try:
            print(f"Fetching appointments for doctor: {doctor_firebase_uid} on {appointment_date}")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("appointments")
                .select("""
                    *, 
                    patients:patient_id(id, first_name, last_name, phone),
                    doctors:doctor_firebase_uid(firebase_uid, first_name, last_name, specialization, phone)
                """)
                .eq("doctor_firebase_uid", doctor_firebase_uid)
                .eq("appointment_date", appointment_date)
                .order("appointment_time", desc=False)
                .execute()
            )
            
            appointments = response.data if response.data else []
            print(f"Found {len(appointments)} appointments for doctor on {appointment_date}")
            
            return appointments
            
        except Exception as e:
            print(f"Error fetching doctor appointments: {e}")
            return []

    async def update_appointment(self, appointment_id: int, update_data: Dict[str, Any]) -> bool:
        """Update an appointment"""
        try:
            print(f"Updating appointment {appointment_id} with data: {update_data}")
            
            # Add updated timestamp
            update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("appointments")
                .update(update_data)
                .eq("id", appointment_id)
                .execute()
            )
            
            return bool(response.data)
            
        except Exception as e:
            print(f"Error updating appointment: {e}")
            return False

    async def delete_appointment(self, appointment_id: int) -> bool:
        """Delete an appointment"""
        try:
            print(f"Deleting appointment: {appointment_id}")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("appointments")
                .delete()
                .eq("id", appointment_id)
                .execute()
            )
            
            return bool(response.data)
            
        except Exception as e:
            print(f"Error deleting appointment: {e}")
            return False

    async def get_appointment_by_id(self, appointment_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific appointment by ID with related data"""
        try:
            print(f"Fetching appointment: {appointment_id}")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("appointments")
                .select("""
                    *, 
                    patients:patient_id(id, first_name, last_name, phone),
                    doctors:doctor_firebase_uid(firebase_uid, first_name, last_name, specialization, phone)
                """)
                .eq("id", appointment_id)
                .execute()
            )
            
            if response.data:
                appointment = response.data[0]
                
                # Enrich with doctor and patient info
                doctor_info = appointment.get("doctors")
                if doctor_info:
                    appointment["doctor_name"] = f"{doctor_info.get('first_name', '')} {doctor_info.get('last_name', '')}".strip()
                    appointment["doctor_specialization"] = doctor_info.get("specialization", "")
                    appointment["doctor_phone"] = doctor_info.get("phone", "")
                
                patient_info = appointment.get("patients")
                if patient_info:
                    appointment["patient_name"] = f"{patient_info.get('first_name', '')} {patient_info.get('last_name', '')}".strip()
                    appointment["patient_phone"] = patient_info.get("phone", "")
                
                return appointment
            
            return None
            
        except Exception as e:
            print(f"Error fetching appointment: {e}")
            return None

    async def check_appointment_conflicts(self, doctor_firebase_uid: str, appointment_date: str, 
                                        appointment_time: str, duration_minutes: int, 
                                        exclude_appointment_id: Optional[int] = None) -> bool:
        """Check if an appointment conflicts with existing appointments"""
        try:
            from datetime import datetime, timedelta
            
            # Parse the appointment time (handle both HH:MM and HH:MM:SS formats)
            if len(appointment_time.split(':')) == 2:
                apt_time = datetime.strptime(appointment_time, "%H:%M").time()
            else:
                apt_time = datetime.strptime(appointment_time, "%H:%M:%S").time()
            
            apt_datetime = datetime.combine(datetime.strptime(appointment_date, "%Y-%m-%d").date(), apt_time)
            
            # Calculate end time
            end_datetime = apt_datetime + timedelta(minutes=duration_minutes)
            end_time = end_datetime.time().strftime("%H:%M")
            
            print(f"Checking conflicts for doctor {doctor_firebase_uid} on {appointment_date} from {appointment_time} to {end_time}")
            
            # Get existing appointments for this doctor on this date
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.supabase.table("appointments")
                .select("id, appointment_time, duration_minutes, status")
                .eq("doctor_firebase_uid", doctor_firebase_uid)
                .eq("appointment_date", appointment_date)
                .neq("status", "cancelled")
                .execute()
            )
            
            existing_appointments = response.data if response.data else []
            
            # Check for conflicts
            for existing_apt in existing_appointments:
                # Skip the appointment we're updating
                if exclude_appointment_id and existing_apt["id"] == exclude_appointment_id:
                    continue
                
                # Calculate existing appointment time range (handle both HH:MM and HH:MM:SS formats)
                existing_time_str = existing_apt["appointment_time"]
                if len(existing_time_str.split(':')) == 2:
                    existing_time = datetime.strptime(existing_time_str, "%H:%M").time()
                else:
                    existing_time = datetime.strptime(existing_time_str, "%H:%M:%S").time()
                
                existing_datetime = datetime.combine(datetime.strptime(appointment_date, "%Y-%m-%d").date(), existing_time)
                existing_end_datetime = existing_datetime + timedelta(minutes=existing_apt["duration_minutes"])
                
                # Check for overlap
                if (apt_datetime < existing_end_datetime and end_datetime > existing_datetime):
                    print(f"Conflict found with appointment {existing_apt['id']}")
                    return True
            
            print("No conflicts found")
            return False
            
        except Exception as e:
            print(f"Error checking appointment conflicts: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return True  # Return True to be safe if we can't check

    async def get_appointment_statistics_by_hospital(self, hospital_name: str, start_date: str, end_date: str) -> Dict[str, Any]:
        """Get appointment statistics for a hospital"""
        try:
            appointments = await self.get_appointments_by_hospital_and_date_range(hospital_name, start_date, end_date)
            
            # Count appointments by status
            stats = {
                "total_appointments": len(appointments),
                "scheduled": 0,
                "confirmed": 0,
                "in_progress": 0,
                "completed": 0,
                "cancelled": 0,
                "no_show": 0
            }
            
            for apt in appointments:
                status = apt.get("status", "scheduled")
                if status in stats:
                    stats[status] += 1
            
            return stats
            
        except Exception as e:
            print(f"Error getting appointment statistics: {e}")
            return {"total_appointments": 0, "scheduled": 0, "confirmed": 0, "in_progress": 0, "completed": 0, "cancelled": 0, "no_show": 0}