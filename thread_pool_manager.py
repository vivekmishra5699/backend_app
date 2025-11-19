"""
Unified Thread Pool Manager
Consolidates all thread pools into a single shared pool to reduce overhead
"""
import concurrent.futures
import os
from typing import Optional
import atexit


class ThreadPoolManager:
    """
    Singleton thread pool manager that consolidates all thread pools.
    Reduces thread overhead from 52+ threads to 10-16 threads.
    """
    
    _instance: Optional['ThreadPoolManager'] = None
    _executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
    
    def __new__(cls):
        """Singleton pattern to ensure only one thread pool"""
        if cls._instance is None:
            cls._instance = super(ThreadPoolManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize unified thread pool"""
        if not hasattr(self, 'initialized'):
            self.initialized = True
            
            # Calculate optimal thread count based on CPU cores
            cpu_count = os.cpu_count() or 1
            
            # Rule of thumb for I/O-bound tasks: 2-4x CPU cores
            # For mixed workload (I/O + CPU): 2x CPU cores
            default_workers = min(16, cpu_count * 2)
            
            # Allow environment variable override
            max_workers = int(os.getenv("THREAD_POOL_MAX_WORKERS", default_workers))
            
            print(f"🔧 Initializing Unified Thread Pool Manager...")
            print(f"   - CPU cores: {cpu_count}")
            print(f"   - Max workers: {max_workers}")
            print(f"   - Optimization: Reducing from 52+ threads to {max_workers} threads")
            
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="unified_pool"
            )
            
            # Register cleanup on exit
            atexit.register(self.shutdown)
            
            print(f"✅ Unified Thread Pool created with {max_workers} workers")
    
    @property
    def executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """Get the shared thread pool executor"""
        if self._executor is None:
            raise RuntimeError("ThreadPoolManager not initialized")
        return self._executor
    
    def shutdown(self, wait: bool = True):
        """Shutdown the thread pool gracefully"""
        if self._executor:
            print("🛑 Shutting down unified thread pool...")
            self._executor.shutdown(wait=wait)
            print("✅ Unified thread pool shut down successfully")
    
    def get_stats(self) -> dict:
        """Get thread pool statistics"""
        if not self._executor:
            return {"status": "not_initialized"}
        
        # Note: ThreadPoolExecutor doesn't expose detailed stats
        # We can only return configuration
        return {
            "max_workers": self._executor._max_workers,
            "thread_name_prefix": self._executor._thread_name_prefix,
            "status": "active"
        }


# Global singleton instance
thread_pool_manager = ThreadPoolManager()


def get_executor() -> concurrent.futures.ThreadPoolExecutor:
    """
    Get the shared thread pool executor.
    Use this instead of creating new ThreadPoolExecutor instances.
    
    Example:
        executor = get_executor()
        result = await loop.run_in_executor(executor, blocking_function)
    """
    return thread_pool_manager.executor


def shutdown_thread_pool(wait: bool = True):
    """
    Shutdown the shared thread pool.
    Call this on application shutdown.
    
    Args:
        wait: Whether to wait for pending tasks to complete
    """
    thread_pool_manager.shutdown(wait=wait)
