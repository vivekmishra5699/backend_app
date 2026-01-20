import asyncio
import concurrent.futures
from typing import Optional, Dict, Any
import traceback
from dotenv import load_dotenv
import os
import datetime
from twilio.rest import Client
from twilio.base.exceptions import TwilioException

# Load environment variables
load_dotenv()

class WhatsAppService:
    def __init__(self):
        # Twilio WhatsApp configuration
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.whatsapp_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=20)
        
        # Initialize Twilio client
        if self.account_sid and self.auth_token:
            self.client = Client(self.account_sid, self.auth_token)
        else:
            self.client = None
        
        # Validate required credentials
        if not all([self.account_sid, self.auth_token, self.whatsapp_number]):
            print("WARNING: Twilio WhatsApp credentials not properly configured")
            print("Required environment variables:")
            print("- TWILIO_ACCOUNT_SID")
            print("- TWILIO_AUTH_TOKEN")
            print("- TWILIO_WHATSAPP_NUMBER")
            print(f"Current values:")
            print(f"- account_sid: {'Set' if self.account_sid else 'Missing'}")
            print(f"- auth_token: {'Set' if self.auth_token else 'Missing'}")
            print(f"- whatsapp_number: {self.whatsapp_number or 'Missing'}")
    
    async def send_message(self, to_phone: str, message: str) -> Dict[str, Any]:
        """Send a simple text message via Twilio WhatsApp"""
        try:
            # Validate credentials
            if not self.client:
                return {
                    "success": False,
                    "error": "Twilio client not configured - missing credentials"
                }
            
            # Format phone number for Twilio (with + prefix)
            phone_number = self._format_phone_number(to_phone)
            
            # Run the Twilio API call in a thread pool to make it async
            loop = asyncio.get_event_loop()
            message_obj = await loop.run_in_executor(
                self.executor,
                lambda: self.client.messages.create(
                    body=message,
                    from_=self.whatsapp_number,
                    to=f"whatsapp:{phone_number}"
                )
            )
            
            print(f"Twilio WhatsApp message sent successfully to {phone_number}")
            
            return {
                "success": True,
                "message_id": message_obj.sid,
                "phone_number": phone_number,
                "status": message_obj.status,
                "response": {
                    "sid": message_obj.sid,
                    "status": message_obj.status,
                    "to": message_obj.to,
                    "from": message_obj.from_
                }
            }
                
        except TwilioException as e:
            print(f"Twilio WhatsApp error: {e}")
            return {
                "success": False,
                "error": f"Twilio WhatsApp error: {e.msg if hasattr(e, 'msg') else str(e)}",
                "code": getattr(e, 'code', None)
            }
        except Exception as e:
            print(f"Error sending Twilio WhatsApp message: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            }
    
    async def send_media_message(self, to_phone: str, message: str, media_url: str) -> Dict[str, Any]:
        """Send a WhatsApp message with media via Twilio"""
        try:
            if not self.client:
                return {
                    "success": False,
                    "error": "Twilio client not configured"
                }
                
            phone_number = self._format_phone_number(to_phone)
            
            loop = asyncio.get_event_loop()
            message_obj = await loop.run_in_executor(
                self.executor,
                lambda: self.client.messages.create(
                    body=message,
                    media_url=[media_url],
                    from_=self.whatsapp_number,
                    to=f"whatsapp:{phone_number}"
                )
            )
            
            return {
                "success": True,
                "message_id": message_obj.sid,
                "phone_number": phone_number,
                "status": message_obj.status,
                "response": {
                    "sid": message_obj.sid,
                    "status": message_obj.status,
                    "to": message_obj.to,
                    "from": message_obj.from_
                }
            }
                
        except TwilioException as e:
            print(f"Twilio WhatsApp media error: {e}")
            return {
                "success": False,
                "error": f"Twilio WhatsApp error: {e.msg if hasattr(e, 'msg') else str(e)}"
            }
        except Exception as e:
            print(f"Error sending Twilio WhatsApp media message: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def send_report_upload_link(self, patient_name: str, doctor_name: str, 
                                    phone_number: str, upload_url: str, 
                                    tests_recommended: str, expires_at: str) -> Dict[str, Any]:
        """Send a formatted report upload link message via Twilio"""
        try:
            print(f"📤 Sending upload link to {patient_name} at {phone_number}")
            
            # Format the message
            message = self._format_upload_message(
                patient_name, doctor_name, upload_url, 
                tests_recommended, expires_at
            )
            
            # Send the message using Twilio
            result = await self.send_message(phone_number, message)
            
            if result["success"]:
                print(f"✅ Upload link sent to {patient_name}")
                return {
                    **result,
                    "method": "twilio_direct"
                }
            else:
                print(f"❌ Failed to send upload link to {patient_name}: {result.get('error')}")
                return result
            
        except Exception as e:
            print(f"Error sending report upload link: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def send_patient_profile_pdf(self, patient_name: str, doctor_name: str, 
                                     phone_number: str, pdf_url: str, 
                                     visits_count: int, reports_count: int) -> Dict[str, Any]:
        """Send patient profile PDF via WhatsApp"""
        try:
            # Format the phone number
            formatted_phone = self._format_phone_number(phone_number)
            
            # Create the message
            message = f"""🏥 *Medical Profile - {patient_name}*

Dear {patient_name},

Your complete medical profile has been prepared by {doctor_name}.

📋 *Profile Summary:*
• Total Visits: {visits_count}
• Total Reports: {reports_count}
• Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}

📎 *Download your profile:*
{pdf_url}

This profile contains:
✅ Personal & contact information
✅ Medical history & allergies
✅ All visit records & diagnoses
✅ Treatment plans & medications
✅ Test results & reports

⚠️ *Important:*
This is a confidential medical document. Please keep it secure and share only with authorized healthcare providers.

If you have any questions about your medical profile, please contact our clinic.

Best regards,
{doctor_name}"""

            # Send the message
            return await self.send_message(formatted_phone, message)
        
        except Exception as e:
            print(f"Error sending patient profile PDF via WhatsApp: {e}")
            return {
                "success": False,
                "error": str(e),
                "phone_number": phone_number
            }
    
    def _format_phone_number(self, phone: str) -> str:
        """Format phone number for Twilio WhatsApp (with + prefix)"""
        # Remove common formatting characters
        phone = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        
        # Ensure it starts with + and country code
        if not phone.startswith("+"):
            if len(phone) == 10 and phone.isdigit():
                phone = "+91" + phone  # Add India country code
            elif len(phone) > 10 and phone.isdigit():
                phone = "+" + phone  # Add + prefix
        
        return phone
    
    def _format_upload_message(self, patient_name: str, doctor_name: str, 
                             upload_url: str, tests_recommended: str, expires_at: str) -> str:
        """Format the upload message for WhatsApp"""
        from datetime import datetime
        
        # Parse and format the expiry date
        try:
            expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            formatted_expires = expires_dt.strftime('%d %B %Y at %I:%M %p')
        except:
            formatted_expires = expires_at
        
        message = f"""🏥 *Medical Report Upload Request*

Hello {patient_name},

{doctor_name} has requested you to upload your medical reports.

📋 *Tests Required:*
{tests_recommended}

📤 *Upload your reports here:*
{upload_url}

⏰ *Important:* This link will expire on {formatted_expires}

📌 *Instructions:*
• Click the link above to open the upload page
• Upload your medical reports (PDF, images, or documents)
• Maximum file size: 10MB per file
• Add notes if needed

🔒 Your reports will be securely stored and only accessible to your doctor.

Thank you!"""
        
        return message
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test Twilio WhatsApp connection"""
        try:
            if not self.client:
                return {
                    "success": False,
                    "error": "Twilio WhatsApp credentials not configured"
                }
            
            # Test by getting account info
            loop = asyncio.get_event_loop()
            account = await loop.run_in_executor(
                self.executor,
                lambda: self.client.api.account.fetch()
            )
            
            return {
                "success": True,
                "message": "Twilio WhatsApp connection successful",
                "account_sid": account.sid,
                "whatsapp_number": self.whatsapp_number,
                "status": account.status
            }
                
        except TwilioException as e:
            return {
                "success": False,
                "error": f"Twilio error: {e.msg if hasattr(e, 'msg') else str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_message_status(self, message_id: str) -> Dict[str, Any]:
        """Get the status of a sent message from Twilio"""
        try:
            if not self.client:
                return {
                    "success": False,
                    "error": "Twilio client not configured"
                }
            
            loop = asyncio.get_event_loop()
            message = await loop.run_in_executor(
                self.executor,
                lambda: self.client.messages(message_id).fetch()
            )
            
            return {
                "success": True,
                "message_id": message_id,
                "status": message.status,
                "to": message.to,
                "from": message.from_,
                "date_sent": str(message.date_sent) if message.date_sent else None,
                "response": {
                    "sid": message.sid,
                    "status": message.status,
                    "error_code": message.error_code,
                    "error_message": message.error_message
                }
            }
                
        except TwilioException as e:
            return {
                "success": False,
                "error": f"Twilio error: {e.msg if hasattr(e, 'msg') else str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def send_visit_report(self, patient_name: str, doctor_name: str, phone_number: str, 
                               report_url: str, visit_date: str, custom_message: str = "") -> Dict[str, Any]:
        """Send visit report via WhatsApp to patient"""
        try:
            message = self._create_visit_report_message(
                patient_name, doctor_name, report_url, visit_date, custom_message
            )
            
            return await self.send_message(phone_number, message)
            
        except Exception as e:
            print(f"Error sending visit report via WhatsApp: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def send_handwritten_visit_note(self, patient_name: str, doctor_name: str, phone_number: str, 
                                         pdf_url: str, visit_date: str, custom_message: str = "") -> Dict[str, Any]:
        """Send handwritten visit note via WhatsApp to patient"""
        try:
            message = self._create_handwritten_note_message(
                patient_name, doctor_name, pdf_url, visit_date, custom_message
            )
            
            return await self.send_message(phone_number, message)
            
        except Exception as e:
            print(f"Error sending handwritten visit note via WhatsApp: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def send_empirical_prescription(self, patient_name: str, doctor_name: str, phone_number: str, 
                                          pdf_url: str, visit_date: str, custom_message: str = "") -> Dict[str, Any]:
        """Send empirical prescription via WhatsApp with disclaimer about potential changes"""
        try:
            message = self._create_empirical_prescription_message(
                patient_name, doctor_name, pdf_url, visit_date, custom_message
            )
            
            return await self.send_message(phone_number, message)
            
        except Exception as e:
            print(f"Error sending empirical prescription via WhatsApp: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _create_visit_report_message(self, patient_name: str, doctor_name: str, 
                                   report_url: str, visit_date: str, custom_message: str = "") -> str:
        """Create a formatted visit report message"""
        
        # Format the visit date
        try:
            from datetime import datetime
            date_obj = datetime.strptime(visit_date, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%B %d, %Y")
        except Exception:
            formatted_date = visit_date
        
        base_message = f"""🏥 *Medical Visit Report*

Hello {patient_name},

{doctor_name} has prepared your medical visit report for your consultation on {formatted_date}.

📄 *Download your visit report:*
{report_url}

📱 *Report Details:*
• Visit Date: {formatted_date}
• Doctor: {doctor_name}
• Report generated on: {datetime.now().strftime("%B %d, %Y at %I:%M %p")}"""

        if custom_message.strip():
            base_message += f"""

💬 *Doctor's Message:*
{custom_message.strip()}"""

        base_message += """

🔒 This report is confidential and for your personal medical records.

Thank you for visiting our clinic!"""
        
        return base_message

    def _create_handwritten_note_message(self, patient_name: str, doctor_name: str, 
                                        pdf_url: str, visit_date: str, custom_message: str = "") -> str:
        """Create a formatted handwritten visit note message"""
        
        # Format the visit date
        try:
            from datetime import datetime
            date_obj = datetime.strptime(visit_date, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%B %d, %Y")
        except Exception:
            formatted_date = visit_date
        
        base_message = f"""✍️ *Handwritten Visit Notes*

Hello {patient_name},

{doctor_name} has completed your handwritten visit notes for your consultation on {formatted_date}.

📄 *Download your handwritten notes:*
{pdf_url}

📱 *Note Details:*
• Visit Date: {formatted_date}
• Doctor: {doctor_name}
• Notes completed on: {datetime.now().strftime("%B %d, %Y at %I:%M %p")}
• Format: Handwritten PDF"""

        if custom_message.strip():
            base_message += f"""

💬 *Doctor's Message:*
{custom_message.strip()}"""

        base_message += """

🔒 These handwritten notes are confidential and for your personal medical records.

Thank you for visiting our clinic!"""
        
        return base_message

    def _create_empirical_prescription_message(self, patient_name: str, doctor_name: str, 
                                               pdf_url: str, visit_date: str, custom_message: str = "") -> str:
        """Create a formatted empirical prescription message with disclaimer"""
        
        # Format the visit date
        try:
            from datetime import datetime
            date_obj = datetime.strptime(visit_date, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%B %d, %Y")
        except Exception:
            formatted_date = visit_date
        
        base_message = f"""⚕️ *EMPIRICAL PRESCRIPTION*

Hello {patient_name},

{doctor_name} has provided you with an *empirical prescription* based on your consultation on {formatted_date}.

📄 *Download your prescription:*
{pdf_url}

⚠️ *IMPORTANT NOTICE:*
━━━━━━━━━━━━━━━━━━━━━━━━
This is an *initial/empirical prescription* based on clinical assessment.

*This prescription may be MODIFIED based on:*
• Laboratory test results
• Diagnostic imaging reports
• Further clinical investigation
• Follow-up examination findings

*Please complete the recommended tests and return for follow-up.*
━━━━━━━━━━━━━━━━━━━━━━━━

📱 *Prescription Details:*
• Visit Date: {formatted_date}
• Doctor: {doctor_name}
• Type: Empirical (Initial) Prescription
• Issued on: {datetime.now().strftime("%B %d, %Y at %I:%M %p")}"""

        if custom_message.strip():
            base_message += f"""

💬 *Doctor's Message:*
{custom_message.strip()}"""

        base_message += """

🔒 This prescription is confidential and for your personal medical use only.
❌ Do not discontinue or modify medications without consulting your doctor.

Thank you for visiting our clinic!"""
        
        return base_message
    
    def __del__(self):
        """Cleanup thread pool executor"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
