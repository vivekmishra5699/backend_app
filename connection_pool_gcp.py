import os
import asyncio
import asyncpg
from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GCPConnectionPool:
    """
    Manages connection pool for Google Cloud SQL (PostgreSQL).
    Uses SQLAlchemy + Cloud SQL Connector.
    """
    
    _instance = None
    _engine: AsyncEngine = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GCPConnectionPool, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self.connector = None
            
    async def init_pool(self):
        """Initialize the SQLAlchemy AsyncEngine using Cloud SQL Connector"""
        if self._engine:
            return self._engine

        # Get configuration from environment
        instance_connection_name = os.getenv("INSTANCE_CONNECTION_NAME")
        db_user = os.getenv("DB_USER")
        db_pass = os.getenv("DB_PASS")
        db_name = os.getenv("DB_NAME")
        
        if not all([instance_connection_name, db_user, db_pass, db_name]):
            logger.error("❌ Missing Cloud SQL configuration in .env")
            raise ValueError("Missing Cloud SQL configuration")

        # Initialize Cloud SQL Connector
        self.connector = Connector()

        async def getconn():
            conn = await self.connector.connect_async(
                instance_connection_name,
                "asyncpg",
                user=db_user,
                password=db_pass,
                db=db_name,
                ip_type=IPTypes.PUBLIC 
            )
            return conn

        # Create SQLAlchemy AsyncEngine
        try:
            self._engine = create_async_engine(
                "postgresql+asyncpg://",
                async_creator=getconn,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=1800,
            )
            logger.info(f"✅ Cloud SQL Engine initialized for {instance_connection_name}")
            return self._engine
        except Exception as e:
            logger.error(f"❌ Failed to create Cloud SQL engine: {e}")
            raise

    async def get_pool(self):
        """Get the existing engine or initialize it"""
        if self._engine is None:
            await self.init_pool()
        return self._engine

    async def close(self):
        """Close the engine and connector"""
        if self._engine:
            await self._engine.dispose()
            logger.info("✅ Cloud SQL Engine disposed")
        if self.connector:
            await self.connector.close_async()
            logger.info("✅ Cloud SQL Connector closed")

# Global instance
gcp_db_pool = GCPConnectionPool()

async def get_db_connection():
    """Dependency to get a database connection from the pool"""
    engine = await gcp_db_pool.get_pool()
    async with engine.connect() as conn:
        yield conn
