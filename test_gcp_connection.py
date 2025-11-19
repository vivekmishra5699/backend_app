import asyncio
import os
from dotenv import load_dotenv
import logging

# Load environment variables BEFORE importing modules that use them
load_dotenv()

from connection_pool_gcp import gcp_db_pool
from gcp_storage import gcp_storage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_database_connection():
    print("\n🧪 Testing Cloud SQL Connection...")
    try:
        engine = await gcp_db_pool.get_pool()
        from sqlalchemy import text
        async with engine.connect() as conn:
            # Run a simple query
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✅ Database Connected! Version: {version}")
            return True
    except Exception as e:
        print(f"❌ Database Connection Failed: {e}")
        return False
    finally:
        await gcp_db_pool.close()

def test_storage_connection():
    print("\n🧪 Testing Cloud Storage Connection...")
    try:
        if not gcp_storage.bucket:
            print("❌ Storage Bucket not initialized (check credentials/bucket name)")
            return False
        
        print(f"✅ Storage Bucket '{gcp_storage.bucket_name}' initialized successfully")
        
        # Optional: List files to verify permissions
        blobs = list(gcp_storage.client.list_blobs(gcp_storage.bucket_name, max_results=1))
        print(f"   (Bucket access verified, found {len(blobs)} items)")
        return True
    except Exception as e:
        print(f"❌ Storage Connection Failed: {e}")
        return False

async def main():
    print("🚀 Starting GCP Connectivity Test")
    print(f"   Project: {os.getenv('GCP_PROJECT_ID')}")
    print(f"   Instance: {os.getenv('INSTANCE_CONNECTION_NAME')}")
    
    db_success = await test_database_connection()
    storage_success = test_storage_connection()
    
    if db_success and storage_success:
        print("\n🎉 All systems go! You are ready to migrate.")
    else:
        print("\n⚠️  Some checks failed. Please review the errors above.")

if __name__ == "__main__":
    asyncio.run(main())
