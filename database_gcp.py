import logging
from typing import Optional, Dict, List, Any
from sqlalchemy import text
from connection_pool_gcp import gcp_db_pool

logger = logging.getLogger(__name__)

class DatabaseGCP:
    """
    GCP Cloud SQL implementation of the Database class.
    Migrating from Supabase ORM to raw SQL with SQLAlchemy + asyncpg.
    """
    
    def __init__(self):
        self.pool_manager = gcp_db_pool
        
    async def get_doctor_by_firebase_uid(self, firebase_uid: str) -> Optional[Dict[str, Any]]:
        """
        Get doctor profile by Firebase UID
        """
        query = text("""
            SELECT * FROM doctors 
            WHERE firebase_uid = :firebase_uid 
            LIMIT 1
        """)
        try:
            engine = await self.pool_manager.get_pool()
            async with engine.connect() as conn:
                result = await conn.execute(query, {"firebase_uid": firebase_uid})
                record = result.mappings().first()
                return dict(record) if record else None
        except Exception as e:
            logger.error(f"Error fetching doctor {firebase_uid}: {e}")
            return None

    async def create_doctor(self, doctor_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a new doctor profile
        """
        # Construct INSERT query dynamically based on keys
        columns = list(doctor_data.keys())
        # Use :param style for SQLAlchemy
        placeholders = [f":{col}" for col in columns]
        
        query = text(f"""
            INSERT INTO doctors ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
            RETURNING *
        """)
        
        try:
            engine = await self.pool_manager.get_pool()
            async with engine.connect() as conn:
                result = await conn.execute(query, doctor_data)
                await conn.commit() # Commit transaction
                record = result.mappings().first()
                return dict(record) if record else None
        except Exception as e:
            logger.error(f"Error creating doctor: {e}")
            return None

    # TODO: Migrate remaining methods from database.py
    # - get_patient
    # - create_patient
    # - create_visit
    # - etc.

# Global instance
db_gcp = DatabaseGCP()
