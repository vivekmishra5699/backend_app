"""
AI Analysis Background Processor

This service processes queued AI analysis tasks in the background.
It continuously checks for pending analyses and processes them.
"""

import asyncio
import traceback
import httpx
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class AIAnalysisProcessor:
    def __init__(self, db_manager, ai_service):
        """Initialize the AI analysis processor"""
        self.db = db_manager
        self.ai_service = ai_service
        self.is_running = False
        self.process_interval = 10  # Check every 10 seconds
        self.max_concurrent = 10  # Process max 10 analyses concurrently
        
        print("🔄 AI Analysis Processor initialized")
    
    async def start_processing(self):
        """Start the background processing loop"""
        self.is_running = True
        print("🚀 Starting AI Analysis background processor...")
        
        while self.is_running:
            try:
                await self.process_pending_analyses()
                await asyncio.sleep(self.process_interval)
            except Exception as e:
                print(f"❌ Error in processing loop: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                await asyncio.sleep(self.process_interval)
    
    def stop_processing(self):
        """Stop the background processing"""
        self.is_running = False
        print("⏹️  AI Analysis processor stopped")
    
    async def process_pending_analyses(self):
        """Process pending AI analyses from the queue"""
        try:
            # Get pending analyses from all doctors (limit to prevent overload)
            pending_analyses = []
            
            # Get unique doctors first, then get their pending analyses
            # For now, we'll get pending from all doctors - in production, you might want to optimize this
            queue_items = await self.get_all_pending_analyses(limit=self.max_concurrent)
            
            if not queue_items:
                return  # No pending analyses
            
            print(f"📋 Found {len(queue_items)} pending AI analyses to process")
            
            # Process analyses concurrently
            tasks = []
            for queue_item in queue_items:
                task = asyncio.create_task(self.process_single_analysis(queue_item))
                tasks.append(task)
            
            # Wait for all tasks to complete
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                
        except Exception as e:
            print(f"❌ Error processing pending analyses: {e}")
            print(f"Traceback: {traceback.format_exc()}")
    
    async def get_all_pending_analyses(self, limit: int = 10) -> list:
        """Get pending analyses from the queue"""
        try:
            # Use a direct query to get pending analyses
            # This is a simplified version - in production you might want to batch by doctor
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.db.supabase.table("ai_analysis_queue")
                    .select("*")
                    .eq("status", "pending")
                    .order("priority", desc=True)
                    .order("queued_at")
                    .limit(limit)
                    .execute()
            )
            
            return response.data if response.data else []
            
        except Exception as e:
            print(f"❌ Error getting pending analyses: {e}")
            return []
    
    async def process_single_analysis(self, queue_item: Dict[str, Any]):
        """Process a single AI analysis from the queue"""
        queue_id = queue_item["id"]
        report_id = queue_item["report_id"]
        visit_id = queue_item["visit_id"]
        patient_id = queue_item["patient_id"]
        doctor_firebase_uid = queue_item["doctor_firebase_uid"]
        
        try:
            print(f"🔍 Processing AI analysis for report {report_id}")
            
            # Update status to processing
            await self.db.update_ai_analysis_queue_status(queue_id, "processing")
            
            # Check if analysis already exists (avoid duplicate processing)
            existing_analysis = await self.db.get_ai_analysis_by_report_id(report_id, doctor_firebase_uid)
            if existing_analysis:
                print(f"⚠️  Analysis already exists for report {report_id}, marking as completed")
                await self.db.update_ai_analysis_queue_status(queue_id, "completed")
                return
            
            # Get report, visit, patient, and doctor data
            report = await self.db.get_report_by_id(report_id, doctor_firebase_uid)
            visit = await self.db.get_visit_by_id(visit_id, doctor_firebase_uid) 
            patient = await self.db.get_patient_by_id(patient_id, doctor_firebase_uid)
            doctor = await self.db.get_doctor_by_firebase_uid(doctor_firebase_uid)
            
            if not all([report, visit, patient, doctor]):
                error_msg = "Missing required data (report, visit, patient, or doctor)"
                print(f"❌ {error_msg} for queue item {queue_id}")
                await self.db.update_ai_analysis_queue_status(queue_id, "failed", error_msg)
                return
            
            # Download the file for analysis
            file_content = await self.download_report_file(report["file_url"])
            if not file_content:
                error_msg = "Failed to download report file"
                print(f"❌ {error_msg} for report {report_id}")
                await self.db.update_ai_analysis_queue_status(queue_id, "failed", error_msg)
                return
            
            # Perform AI analysis
            start_time = datetime.now()
            analysis_result = await self.ai_service.analyze_document(
                file_content=file_content,
                file_name=report["file_name"],
                file_type=report["file_type"],
                patient_context=patient,
                visit_context=visit,
                doctor_context=doctor
            )
            
            # Calculate processing time
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            
            if analysis_result["success"]:
                # Store analysis results
                analysis_data = {
                    "report_id": report_id,
                    "visit_id": visit_id,
                    "patient_id": patient_id,
                    "doctor_firebase_uid": doctor_firebase_uid,
                    "analysis_type": "document_analysis",
                    "model_used": analysis_result["model_used"],
                    "confidence_score": analysis_result["analysis"]["confidence_score"],
                    "raw_analysis": analysis_result["analysis"]["raw_analysis"],
                    "document_summary": analysis_result["analysis"]["structured_analysis"].get("document_summary"),
                    "clinical_significance": analysis_result["analysis"]["structured_analysis"].get("clinical_significance"),
                    "correlation_with_patient": analysis_result["analysis"]["structured_analysis"].get("correlation_with_patient"),
                    "actionable_insights": analysis_result["analysis"]["structured_analysis"].get("actionable_insights"),
                    "patient_communication": analysis_result["analysis"]["structured_analysis"].get("patient_communication"),
                    "clinical_notes": analysis_result["analysis"]["structured_analysis"].get("clinical_notes"),
                    "key_findings": analysis_result["analysis"]["key_findings"],
                    "analysis_success": True,
                    "analysis_error": None,
                    "processing_time_ms": int(processing_time),
                    "analyzed_at": analysis_result["processed_at"],
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                
                created_analysis = await self.db.create_ai_analysis(analysis_data)
                if created_analysis:
                    print(f"✅ AI analysis completed for report {report_id} (Queue ID: {queue_id})")
                    print(f"   Processing time: {processing_time:.0f}ms")
                    print(f"   Confidence: {analysis_result['analysis']['confidence_score']:.2f}")
                    await self.db.update_ai_analysis_queue_status(queue_id, "completed")
                else:
                    error_msg = "Failed to save analysis results to database"
                    print(f"❌ {error_msg} for report {report_id}")
                    await self.db.update_ai_analysis_queue_status(queue_id, "failed", error_msg)
            else:
                # Analysis failed
                error_msg = analysis_result["error"]
                print(f"❌ AI analysis failed for report {report_id}: {error_msg}")
                
                # Store failed analysis
                analysis_data = {
                    "report_id": report_id,
                    "visit_id": visit_id,
                    "patient_id": patient_id,
                    "doctor_firebase_uid": doctor_firebase_uid,
                    "analysis_type": "document_analysis",
                    "model_used": "gemini-2.0-flash-exp",
                    "confidence_score": 0.0,
                    "raw_analysis": "",
                    "analysis_success": False,
                    "analysis_error": error_msg,
                    "processing_time_ms": int(processing_time),
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                
                await self.db.create_ai_analysis(analysis_data)
                await self.db.update_ai_analysis_queue_status(queue_id, "failed", error_msg)
                
        except Exception as e:
            error_msg = f"Processing error: {str(e)}"
            print(f"❌ Error processing analysis for queue item {queue_id}: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            await self.db.update_ai_analysis_queue_status(queue_id, "failed", error_msg)
    
    async def download_report_file(self, file_url: str) -> Optional[bytes]:
        """Download a report file from the given URL"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(file_url)
                if response.status_code == 200:
                    return response.content
                else:
                    print(f"❌ Failed to download file: HTTP {response.status_code}")
                    return None
        except Exception as e:
            print(f"❌ Error downloading file: {e}")
            return None
    
    async def get_processing_stats(self) -> Dict[str, Any]:
        """Get statistics about the processing queue"""
        try:
            # Get queue statistics
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.db.supabase.table("ai_analysis_queue")
                    .select("status")
                    .execute()
            )
            
            queue_items = response.data if response.data else []
            
            stats = {
                "total_queued": len(queue_items),
                "pending": len([item for item in queue_items if item["status"] == "pending"]),
                "processing": len([item for item in queue_items if item["status"] == "processing"]),
                "completed": len([item for item in queue_items if item["status"] == "completed"]),
                "failed": len([item for item in queue_items if item["status"] == "failed"]),
                "processor_running": self.is_running
            }
            
            return stats
            
        except Exception as e:
            print(f"❌ Error getting processing stats: {e}")
            return {
                "total_queued": 0,
                "pending": 0,
                "processing": 0,
                "completed": 0,
                "failed": 0,
                "processor_running": self.is_running
            }

async def run_background_processor():
    """Standalone function to run the background processor"""
    try:
        # Initialize services
        from database import DatabaseManager
        from ai_analysis_service import AIAnalysisService
        from supabase import create_client
        
        # Setup Supabase client
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        if not supabase_url or not supabase_key:
            print("❌ Missing Supabase credentials")
            return
        
        supabase = create_client(supabase_url, supabase_key)
        db = DatabaseManager(supabase)
        ai_service = AIAnalysisService()
        
        # Create and start processor
        processor = AIAnalysisProcessor(db, ai_service)
        await processor.start_processing()
        
    except KeyboardInterrupt:
        print("\n⏹️  Background processor stopped by user")
    except Exception as e:
        print(f"❌ Error running background processor: {e}")
        print(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    print("🔄 Starting AI Analysis Background Processor")
    print("=" * 50)
    asyncio.run(run_background_processor())
