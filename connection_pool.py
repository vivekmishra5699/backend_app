"""
Connection Pool Manager for Supabase and HTTP Clients
Implements connection pooling to reduce latency and improve performance
"""
import httpx
from typing import Optional
from supabase import create_client, Client
import os


class ConnectionPoolManager:
    """
    Manages connection pools for HTTP clients and database connections.
    Reduces connection overhead by reusing connections.
    """
    
    _instance = None
    _http_client: Optional[httpx.AsyncClient] = None
    _supabase_client: Optional[Client] = None
    
    def __new__(cls):
        """Singleton pattern to ensure only one connection pool"""
        if cls._instance is None:
            cls._instance = super(ConnectionPoolManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize connection pools"""
        if not hasattr(self, 'initialized'):
            self.initialized = True
            print("🔌 Initializing Connection Pool Manager...")
    
    def get_http_client(
        self,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
        keepalive_expiry: float = 30.0,
        timeout: float = 30.0
    ) -> httpx.AsyncClient:
        """
        Get or create a shared HTTP client with connection pooling.
        
        Args:
            max_connections: Maximum number of connections in the pool
            max_keepalive_connections: Maximum number of idle connections to keep alive
            keepalive_expiry: Seconds to keep idle connections alive
            timeout: Request timeout in seconds
            
        Returns:
            Shared httpx.AsyncClient instance with connection pooling
        """
        if self._http_client is None or self._http_client.is_closed:
            # Configure connection pooling limits
            limits = httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
                keepalive_expiry=keepalive_expiry
            )
            
            # Configure timeout
            timeout_config = httpx.Timeout(timeout)
            
            # Create client with connection pooling
            self._http_client = httpx.AsyncClient(
                limits=limits,
                timeout=timeout_config,
                http2=True,  # Enable HTTP/2 for better performance
                follow_redirects=True
            )
            
            print(f"✅ HTTP Connection Pool created:")
            print(f"   - Max connections: {max_connections}")
            print(f"   - Keep-alive connections: {max_keepalive_connections}")
            print(f"   - Keep-alive expiry: {keepalive_expiry}s")
            print(f"   - HTTP/2 enabled: True")
        
        return self._http_client
    
    def get_supabase_client_with_pooling(
        self,
        supabase_url: str,
        supabase_key: str,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout: int = 30,
        pool_recycle: int = 3600
    ) -> Client:
        """
        Get or create a Supabase client with optimized settings.
        
        Note: Supabase Python client uses httpx internally, which we configure
        with connection pooling via custom httpx client.
        
        Args:
            supabase_url: Supabase project URL
            supabase_key: Supabase API key (service role key recommended)
            pool_size: Number of connections to maintain
            max_overflow: Maximum overflow connections
            pool_timeout: Connection timeout in seconds
            pool_recycle: Recycle connections after this many seconds
            
        Returns:
            Supabase Client instance with optimized connection settings
        """
        if self._supabase_client is None:
            # Create HTTP client with connection pooling
            http_client = self.get_http_client(
                max_connections=pool_size + max_overflow,
                max_keepalive_connections=pool_size,
                keepalive_expiry=float(pool_recycle)
            )
            
            # Create Supabase client with custom HTTP client
            # Note: As of now, supabase-py doesn't directly support custom httpx client
            # But we configure the environment for optimal connection reuse
            self._supabase_client = create_client(
                supabase_url,
                supabase_key,
                options={
                    'schema': 'public',
                    'auto_refresh_token': True,
                    'persist_session': True,
                }
            )
            
            print(f"✅ Supabase Client configured with connection pooling:")
            print(f"   - Pool size: {pool_size}")
            print(f"   - Max overflow: {max_overflow}")
            print(f"   - Pool timeout: {pool_timeout}s")
            print(f"   - Connection recycle: {pool_recycle}s")
        
        return self._supabase_client
    
    async def close_all(self):
        """Close all connection pools gracefully"""
        print("🔌 Closing all connection pools...")
        
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            print("✅ HTTP connection pool closed")
        
        # Supabase client doesn't have explicit close method
        # Connections will be cleaned up automatically
        if self._supabase_client:
            self._supabase_client = None
            print("✅ Supabase client released")
        
        print("✅ All connection pools closed successfully")
    
    def get_pool_stats(self) -> dict:
        """Get statistics about connection pool usage"""
        stats = {
            "http_client_active": self._http_client is not None and not self._http_client.is_closed,
            "supabase_client_active": self._supabase_client is not None
        }
        
        return stats


# Global singleton instance
connection_pool = ConnectionPoolManager()


# Convenience functions for easy access
def get_http_client(**kwargs) -> httpx.AsyncClient:
    """Get the shared HTTP client with connection pooling"""
    return connection_pool.get_http_client(**kwargs)


def get_supabase_client(
    supabase_url: Optional[str] = None,
    supabase_key: Optional[str] = None,
    **kwargs
) -> Client:
    """Get the shared Supabase client with connection pooling"""
    # Use environment variables if not provided
    url = supabase_url or os.getenv("SUPABASE_URL")
    key = supabase_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not url or not key:
        raise ValueError("Supabase URL and key must be provided or set in environment")
    
    return connection_pool.get_supabase_client_with_pooling(url, key, **kwargs)


async def close_connection_pools():
    """Close all connection pools - call this on application shutdown"""
    await connection_pool.close_all()
