"""
Appointment Reminder Service
============================

This service handles automatic appointment reminders via WhatsApp.
It runs as a background task and sends reminders 24 hours before
scheduled appointments.

Features:
- Checks both follow-up appointments (visits table) and standalone appointments
- Sends WhatsApp reminders 24 hours before the appointment
- Tracks sent reminders to avoid duplicates
- Supports retry logic for failed sends
- Configurable per-doctor settings
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class AppointmentReminderService:
    """
    Background service for sending automatic appointment reminders.
    
    This service:
    1. Periodically checks for appointments needing reminders
    2. Creates reminder records in the database
    3. Sends WhatsApp messages to patients
    4. Tracks success/failure and supports retries
    """
    
    def __init__(self, db_manager, whatsapp_service):
        """
        Initialize the appointment reminder service.
        
        Args:
            db_manager: DatabaseManager instance for database operations
            whatsapp_service: WhatsAppService instance for sending messages
        """
        self.db = db_manager
        self.whatsapp = whatsapp_service
        self._running = False
        self._task = None
        
        # Configuration
        self.check_interval_minutes = 15  # How often to check for reminders
        self.default_hours_before = 24    # Default reminder time before appointment
        self.max_retries = 3              # Maximum retry attempts for failed sends
        self.retry_delay_minutes = 30     # Delay between retries
        
        print("📅 AppointmentReminderService initialized")
    
    async def start(self):
        """Start the reminder service background task"""
        if self._running:
            print("⚠️ Reminder service already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._reminder_loop())
        print("✅ Appointment reminder service started")
    
    def stop(self):
        """Stop the reminder service"""
        self._running = False
        if self._task:
            self._task.cancel()
        print("🛑 Appointment reminder service stopped")
    
    async def _reminder_loop(self):
        """Main loop that checks for and sends reminders"""
        print("🔄 Starting appointment reminder loop...")
        
        while self._running:
            try:
                # Process reminders
                await self._process_reminders()
                
                # Process pending retry queue
                await self._process_retry_queue()
                
            except asyncio.CancelledError:
                print("📅 Reminder loop cancelled")
                break
            except Exception as e:
                print(f"❌ Error in reminder loop: {e}")
                import traceback
                traceback.print_exc()
            
            # Wait before next check
            await asyncio.sleep(self.check_interval_minutes * 60)
        
        print("📅 Reminder loop ended")
    
    async def _process_reminders(self):
        """Check for appointments needing reminders and schedule them"""
        try:
            print("📅 Checking for appointments needing reminders...")
            
            # Get appointments that need reminders
            appointments = await self.db.get_appointments_needing_reminders(
                hours_before=self.default_hours_before
            )
            
            if not appointments:
                print("📅 No appointments need reminders at this time")
                return
            
            print(f"📅 Found {len(appointments)} appointments needing reminders")
            
            for appointment in appointments:
                try:
                    await self._create_and_send_reminder(appointment)
                except Exception as e:
                    print(f"❌ Error processing reminder for appointment: {e}")
                    continue
                
                # Small delay between sends to avoid rate limiting
                await asyncio.sleep(1)
                
        except Exception as e:
            print(f"❌ Error processing reminders: {e}")
    
    async def _create_and_send_reminder(self, appointment: Dict[str, Any]):
        """Create a reminder record and send the WhatsApp message"""
        try:
            # Calculate scheduled send time (24 hours before appointment)
            appointment_date = datetime.strptime(
                appointment["appointment_date"], "%Y-%m-%d"
            ).date()
            
            # Get appointment time or default to 9:00 AM
            appointment_time_str = appointment.get("appointment_time")
            if appointment_time_str:
                try:
                    if isinstance(appointment_time_str, str):
                        appointment_time = datetime.strptime(
                            appointment_time_str, "%H:%M:%S"
                        ).time()
                    else:
                        appointment_time = appointment_time_str
                except:
                    try:
                        appointment_time = datetime.strptime(
                            appointment_time_str, "%H:%M"
                        ).time()
                    except:
                        appointment_time = datetime.strptime("09:00", "%H:%M").time()
            else:
                appointment_time = datetime.strptime("09:00", "%H:%M").time()
            
            appointment_datetime = datetime.combine(appointment_date, appointment_time)
            appointment_datetime = appointment_datetime.replace(tzinfo=timezone.utc)
            
            # Scheduled send time is 24 hours before
            scheduled_send_time = appointment_datetime - timedelta(hours=self.default_hours_before)
            
            # Only create and send reminder if:
            # - Scheduled time is in the past or within 30 minutes from now
            # - This catches appointments that need to be sent now
            now = datetime.now(timezone.utc)
            time_until_send = scheduled_send_time - now
            
            # Skip if reminder should be sent more than 30 minutes from now
            # The service runs every 15 mins, so 30 mins gives buffer
            if time_until_send > timedelta(minutes=30):
                print(f"⏰ Appointment for {appointment['patient_name']} on {appointment_date}: reminder scheduled in {time_until_send}")
                return  # Don't create record yet, will catch it in a later run
            
            # Generate the message
            message = self._generate_reminder_message(appointment)
            
            # Create reminder record
            reminder_data = {
                "visit_id": appointment.get("visit_id"),
                "appointment_id": appointment.get("appointment_id"),
                "patient_id": appointment["patient_id"],
                "doctor_firebase_uid": appointment["doctor_firebase_uid"],
                "appointment_date": appointment["appointment_date"],
                "appointment_time": appointment_time_str,
                "patient_name": appointment["patient_name"],
                "patient_phone": appointment["patient_phone"],
                "doctor_name": appointment["doctor_name"],
                "hospital_name": appointment.get("hospital_name"),
                "reminder_type": "24h_before",
                "scheduled_send_time": scheduled_send_time.isoformat(),
                "status": "pending",
                "message_content": message,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            # Create the reminder record
            reminder = await self.db.create_appointment_reminder(reminder_data)
            
            if not reminder:
                print(f"❌ Failed to create reminder record for patient {appointment['patient_name']}")
                return
            
            # Send immediately since we're within the 30-minute window
            await self._send_reminder(reminder["id"], appointment["patient_phone"], message)
                
        except Exception as e:
            print(f"❌ Error creating/sending reminder: {e}")
            import traceback
            traceback.print_exc()
    
    async def _send_reminder(self, reminder_id: int, phone: str, message: str) -> bool:
        """Send a WhatsApp reminder message"""
        try:
            print(f"📤 Sending reminder to {phone}...")
            
            # Send via WhatsApp
            result = await self.whatsapp.send_message(
                to_phone=phone,
                message=message
            )
            
            if result.get("success"):
                # Update reminder as sent
                await self.db.update_appointment_reminder(reminder_id, {
                    "status": "sent",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "whatsapp_message_id": result.get("message_id"),
                    "whatsapp_status": result.get("status")
                })
                print(f"✅ Reminder sent successfully (ID: {result.get('message_id')})")
                return True
            else:
                # Update reminder as failed
                error_msg = result.get("error", "Unknown error")
                retry_count = await self._increment_retry_count(reminder_id)
                
                if retry_count < self.max_retries:
                    next_retry = datetime.now(timezone.utc) + timedelta(minutes=self.retry_delay_minutes)
                    await self.db.update_appointment_reminder(reminder_id, {
                        "status": "pending",
                        "error_message": error_msg,
                        "retry_count": retry_count,
                        "next_retry_at": next_retry.isoformat()
                    })
                    print(f"⚠️ Reminder failed, will retry ({retry_count}/{self.max_retries}): {error_msg}")
                else:
                    await self.db.update_appointment_reminder(reminder_id, {
                        "status": "failed",
                        "error_message": error_msg
                    })
                    print(f"❌ Reminder failed after {self.max_retries} retries: {error_msg}")
                return False
                
        except Exception as e:
            print(f"❌ Error sending reminder: {e}")
            await self.db.update_appointment_reminder(reminder_id, {
                "status": "failed",
                "error_message": str(e)
            })
            return False
    
    async def _increment_retry_count(self, reminder_id: int) -> int:
        """Get current retry count and increment it"""
        try:
            # This would be better with a proper atomic increment, but for now:
            response = await self.db.supabase.table("appointment_reminders").select(
                "retry_count"
            ).eq("id", reminder_id).execute()
            
            if response.data:
                return (response.data[0].get("retry_count") or 0) + 1
            return 1
        except:
            return 1
    
    async def _process_retry_queue(self):
        """Process reminders that need to be retried"""
        try:
            # Get pending reminders that are due for retry
            pending = await self.db.get_pending_reminders()
            
            for reminder in pending:
                try:
                    # Check if it's time to send/retry
                    scheduled_time = reminder.get("scheduled_send_time") or reminder.get("next_retry_at")
                    if scheduled_time:
                        if isinstance(scheduled_time, str):
                            scheduled_dt = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
                        else:
                            scheduled_dt = scheduled_time
                        
                        if scheduled_dt > datetime.now(timezone.utc):
                            continue  # Not time yet
                    
                    # Send the reminder
                    await self._send_reminder(
                        reminder["id"],
                        reminder["patient_phone"],
                        reminder.get("message_content") or self._generate_reminder_message(reminder)
                    )
                    
                    # Small delay between sends
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    print(f"❌ Error processing retry for reminder {reminder['id']}: {e}")
                    continue
                    
        except Exception as e:
            print(f"❌ Error processing retry queue: {e}")
    
    def _generate_reminder_message(self, appointment: Dict[str, Any]) -> str:
        """Generate a friendly reminder message for the patient"""
        
        patient_name = appointment.get("patient_name", "Patient")
        doctor_name = appointment.get("doctor_name", "your doctor")
        hospital_name = appointment.get("hospital_name", "our clinic")
        appointment_date = appointment.get("appointment_date", "")
        appointment_time = appointment.get("appointment_time", "")
        
        # Format the date nicely
        try:
            date_obj = datetime.strptime(appointment_date, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%d %B %Y")  # e.g., "20 January 2026"
            day_name = date_obj.strftime("%A")  # e.g., "Monday"
        except:
            formatted_date = appointment_date
            day_name = ""
        
        # Format time if available
        time_str = ""
        if appointment_time:
            try:
                if isinstance(appointment_time, str):
                    if len(appointment_time) > 5:  # HH:MM:SS format
                        time_obj = datetime.strptime(appointment_time, "%H:%M:%S")
                    else:
                        time_obj = datetime.strptime(appointment_time, "%H:%M")
                    time_str = f" at {time_obj.strftime('%I:%M %p')}"  # e.g., "10:30 AM"
            except:
                time_str = f" at {appointment_time}"
        
        # Build the message
        message = f"""🏥 *Appointment Reminder*

Dear {patient_name},

This is a friendly reminder about your upcoming appointment.

📅 *Appointment Details:*
• Date: {day_name}, {formatted_date}{time_str}
• Doctor: {doctor_name}
• Location: {hospital_name}

📝 *Important:*
• Please arrive 10-15 minutes before your scheduled time
• Bring any previous prescriptions or medical reports
• If you need to reschedule, please contact us in advance

We look forward to seeing you!

Best regards,
{hospital_name}

---
_This is an automated reminder. Please do not reply to this message._"""
        
        return message
    
    async def send_immediate_reminder(self, visit_id: Optional[int] = None, 
                                       appointment_id: Optional[int] = None,
                                       custom_message: Optional[str] = None) -> Dict[str, Any]:
        """
        Send an immediate reminder for a specific appointment.
        This can be called manually from an API endpoint.
        """
        try:
            if not visit_id and not appointment_id:
                return {"success": False, "error": "Either visit_id or appointment_id is required"}
            
            # Get appointment details
            if visit_id:
                response = await self.db.supabase.table("visits").select("""
                    id,
                    patient_id,
                    doctor_firebase_uid,
                    follow_up_date,
                    follow_up_time,
                    visit_type,
                    patients!inner(id, first_name, last_name, phone),
                    doctors:doctor_firebase_uid(first_name, last_name, hospital_name)
                """).eq("id", visit_id).execute()
                
                if not response.data:
                    return {"success": False, "error": "Visit not found"}
                
                visit = response.data[0]
                patient = visit.get("patients", {})
                doctor = visit.get("doctors", {})
                
                appointment_data = {
                    "visit_id": visit["id"],
                    "patient_id": patient["id"],
                    "doctor_firebase_uid": visit["doctor_firebase_uid"],
                    "appointment_date": visit["follow_up_date"],
                    "appointment_time": visit.get("follow_up_time"),
                    "patient_name": f"{patient.get('first_name', '')} {patient.get('last_name', '')}".strip(),
                    "patient_phone": patient.get("phone"),
                    "doctor_name": f"Dr. {doctor.get('first_name', '')} {doctor.get('last_name', '')}".strip(),
                    "hospital_name": doctor.get("hospital_name", "")
                }
            else:
                response = await self.db.supabase.table("appointments").select("""
                    id,
                    patient_id,
                    doctor_firebase_uid,
                    appointment_date,
                    appointment_time,
                    appointment_type,
                    patients:patient_id(id, first_name, last_name, phone),
                    doctors:doctor_firebase_uid(first_name, last_name, hospital_name)
                """).eq("id", appointment_id).execute()
                
                if not response.data:
                    return {"success": False, "error": "Appointment not found"}
                
                appt = response.data[0]
                patient = appt.get("patients", {})
                doctor = appt.get("doctors", {})
                
                appointment_data = {
                    "appointment_id": appt["id"],
                    "patient_id": patient["id"],
                    "doctor_firebase_uid": appt["doctor_firebase_uid"],
                    "appointment_date": appt["appointment_date"],
                    "appointment_time": appt.get("appointment_time"),
                    "patient_name": f"{patient.get('first_name', '')} {patient.get('last_name', '')}".strip(),
                    "patient_phone": patient.get("phone"),
                    "doctor_name": f"Dr. {doctor.get('first_name', '')} {doctor.get('last_name', '')}".strip(),
                    "hospital_name": doctor.get("hospital_name", "")
                }
            
            if not appointment_data.get("patient_phone"):
                return {"success": False, "error": "Patient does not have a phone number"}
            
            # Generate message
            message = custom_message or self._generate_reminder_message(appointment_data)
            
            # Create reminder record
            reminder_data = {
                "visit_id": appointment_data.get("visit_id"),
                "appointment_id": appointment_data.get("appointment_id"),
                "patient_id": appointment_data["patient_id"],
                "doctor_firebase_uid": appointment_data["doctor_firebase_uid"],
                "appointment_date": appointment_data["appointment_date"],
                "appointment_time": appointment_data.get("appointment_time"),
                "patient_name": appointment_data["patient_name"],
                "patient_phone": appointment_data["patient_phone"],
                "doctor_name": appointment_data["doctor_name"],
                "hospital_name": appointment_data.get("hospital_name"),
                "reminder_type": "custom",
                "scheduled_send_time": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
                "message_content": message,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            reminder = await self.db.create_appointment_reminder(reminder_data)
            
            if not reminder:
                return {"success": False, "error": "Failed to create reminder record"}
            
            # Send immediately
            success = await self._send_reminder(
                reminder["id"],
                appointment_data["patient_phone"],
                message
            )
            
            return {
                "success": success,
                "reminder_id": reminder["id"],
                "patient_name": appointment_data["patient_name"],
                "patient_phone": appointment_data["patient_phone"],
                "appointment_date": appointment_data["appointment_date"]
            }
            
        except Exception as e:
            print(f"❌ Error sending immediate reminder: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    async def get_service_status(self) -> Dict[str, Any]:
        """Get the current status of the reminder service"""
        try:
            # Get some basic stats
            pending_count = 0
            sent_today = 0
            failed_today = 0
            
            try:
                from datetime import date
                today = date.today().isoformat()
                
                pending_response = await self.db.supabase.table("appointment_reminders").select(
                    "id", count="exact"
                ).eq("status", "pending").execute()
                pending_count = pending_response.count if pending_response.count else 0
                
                sent_response = await self.db.supabase.table("appointment_reminders").select(
                    "id", count="exact"
                ).eq("status", "sent").gte("sent_at", today).execute()
                sent_today = sent_response.count if sent_response.count else 0
                
                failed_response = await self.db.supabase.table("appointment_reminders").select(
                    "id", count="exact"
                ).eq("status", "failed").gte("updated_at", today).execute()
                failed_today = failed_response.count if failed_response.count else 0
                
            except Exception as e:
                print(f"Error getting reminder stats: {e}")
            
            return {
                "running": self._running,
                "check_interval_minutes": self.check_interval_minutes,
                "default_hours_before": self.default_hours_before,
                "pending_reminders": pending_count,
                "sent_today": sent_today,
                "failed_today": failed_today
            }
        except Exception as e:
            return {
                "running": self._running,
                "error": str(e)
            }
