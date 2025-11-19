import os
from google.cloud import storage
from typing import Optional
import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GCPStorageManager:
    """
    Manages file operations with Google Cloud Storage.
    Replaces Supabase Storage functionality.
    """
    
    def __init__(self):
        self.project_id = os.getenv("GCP_PROJECT_ID")
        self.bucket_name = os.getenv("GCS_BUCKET_NAME")
        
        if not self.bucket_name:
            logger.warning("⚠️ GCS_BUCKET_NAME not set in environment variables")
            
        try:
            self.client = storage.Client()
            self.bucket = self.client.bucket(self.bucket_name)
            logger.info(f"✅ GCP Storage Manager initialized for bucket: {self.bucket_name}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize GCP Storage Manager: {e}")
            self.client = None
            self.bucket = None

    def upload_file(self, file_path: str, destination_blob_name: str, content_type: str = "application/pdf") -> Optional[str]:
        """
        Uploads a file to the bucket.
        
        Args:
            file_path: Path to the local file to upload
            destination_blob_name: Name of the object in the bucket (e.g. 'reports/123.pdf')
            content_type: MIME type of the file
            
        Returns:
            Public URL of the uploaded file or None if failed
        """
        if not self.bucket:
            logger.error("Storage bucket not initialized")
            return None
            
        try:
            blob = self.bucket.blob(destination_blob_name)
            blob.upload_from_filename(file_path, content_type=content_type)
            
            logger.info(f"✅ File {file_path} uploaded to {destination_blob_name}")
            
            # Return the public URL (assuming bucket is public or we use signed URLs)
            # For private buckets, you might want to return a signed URL instead
            return blob.public_url
            
        except Exception as e:
            logger.error(f"❌ Error uploading file to GCS: {e}")
            return None

    def upload_bytes(self, file_content: bytes, destination_blob_name: str, content_type: str = "application/pdf") -> Optional[str]:
        """
        Uploads bytes content directly to the bucket.
        """
        if not self.bucket:
            logger.error("Storage bucket not initialized")
            return None
            
        try:
            blob = self.bucket.blob(destination_blob_name)
            blob.upload_from_string(file_content, content_type=content_type)
            
            logger.info(f"✅ Bytes uploaded to {destination_blob_name}")
            return blob.public_url
            
        except Exception as e:
            logger.error(f"❌ Error uploading bytes to GCS: {e}")
            return None

    def generate_signed_url(self, blob_name: str, expiration_minutes: int = 60) -> Optional[str]:
        """
        Generates a signed URL for a blob.
        """
        if not self.bucket:
            return None
            
        try:
            blob = self.bucket.blob(blob_name)
            url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(minutes=expiration_minutes),
                method="GET"
            )
            return url
        except Exception as e:
            logger.error(f"❌ Error generating signed URL: {e}")
            return None

    def delete_file(self, blob_name: str) -> bool:
        """
        Deletes a file from the bucket.
        """
        if not self.bucket:
            return False
            
        try:
            blob = self.bucket.blob(blob_name)
            blob.delete()
            logger.info(f"✅ File {blob_name} deleted")
            return True
        except Exception as e:
            logger.error(f"❌ Error deleting file from GCS: {e}")
            return False

# Global instance
gcp_storage = GCPStorageManager()
