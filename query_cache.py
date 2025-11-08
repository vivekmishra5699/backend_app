"""
Simple TTL-based caching system with LRU eviction for database queries
Reduces repeated queries for data that doesn't change frequently
Features:
- TTL-based expiration
- LRU eviction when max size is reached
- Automatic cleanup of expired entries
- Memory-bounded to prevent leaks
"""

import time
from typing import Any, Optional, Dict, Callable
from collections import OrderedDict
import asyncio
import hashlib
import json
import sys


class QueryCache:
    """Thread-safe TTL-based LRU cache for database query results"""
    
    def __init__(self, default_ttl: int = 300, max_size: int = 1000, max_memory_mb: int = 100):
        """
        Initialize cache with LRU eviction
        
        Args:
            default_ttl: Default time-to-live in seconds (default: 5 minutes)
            max_size: Maximum number of entries (default: 1000)
            max_memory_mb: Maximum memory usage in MB (default: 100MB)
        """
        self.cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        
        print(f"✅ QueryCache initialized: max_size={max_size}, max_memory={max_memory_mb}MB, default_ttl={default_ttl}s")
    
    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate a unique cache key from function arguments"""
        # Create a deterministic string from arguments
        key_data = {
            'prefix': prefix,
            'args': args,
            'kwargs': sorted(kwargs.items())
        }
        key_string = json.dumps(key_data, sort_keys=True, default=str)
        # Hash it to keep keys manageable
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def _get_entry_size(self, entry: Dict[str, Any]) -> int:
        """Estimate size of a cache entry in bytes"""
        try:
            # Rough estimation using sys.getsizeof
            return sys.getsizeof(entry['value']) + sys.getsizeof(entry)
        except:
            # Fallback to string length estimation
            return len(str(entry))
    
    def _get_total_size(self) -> int:
        """Get total cache size in bytes"""
        total = 0
        for entry in self.cache.values():
            total += self._get_entry_size(entry)
        return total
    
    async def _evict_lru(self):
        """Evict least recently used entry"""
        if self.cache:
            # OrderedDict maintains insertion order, pop first (oldest)
            evicted_key, _ = self.cache.popitem(last=False)
            self._evictions += 1
            print(f"Cache LRU EVICTION: {evicted_key[:16]}... (total evictions: {self._evictions})")
    
    async def _enforce_limits(self):
        """Enforce size and memory limits"""
        # Remove expired entries first
        now = time.time()
        expired_keys = [
            key for key, entry in self.cache.items()
            if now >= entry['expires_at']
        ]
        for key in expired_keys:
            del self.cache[key]
        
        # Evict LRU entries if over size limit
        while len(self.cache) >= self.max_size:
            await self._evict_lru()
        
        # Evict LRU entries if over memory limit
        while self._get_total_size() > self.max_memory_bytes and self.cache:
            await self._evict_lru()
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired (LRU: moves to end)"""
        async with self._lock:
            if key in self.cache:
                entry = self.cache[key]
                if time.time() < entry['expires_at']:
                    # Move to end (most recently used)
                    self.cache.move_to_end(key)
                    self._hits += 1
                    print(f"Cache HIT for key: {key[:16]}... (hit rate: {self._get_hit_rate():.1f}%)")
                    return entry['value']
                else:
                    # Expired, remove it
                    print(f"Cache EXPIRED for key: {key[:16]}...")
                    del self.cache[key]
            self._misses += 1
            print(f"Cache MISS for key: {key[:16]}... (hit rate: {self._get_hit_rate():.1f}%)")
            return None
    
    def _get_hit_rate(self) -> float:
        """Calculate cache hit rate percentage"""
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return (self._hits / total) * 100
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Set value in cache with TTL and enforce limits"""
        ttl = ttl if ttl is not None else self.default_ttl
        async with self._lock:
            # Enforce limits before adding new entry
            await self._enforce_limits()
            
            # Add or update entry (will be at end of OrderedDict)
            self.cache[key] = {
                'value': value,
                'expires_at': time.time() + ttl,
                'created_at': time.time()
            }
            # Move to end if updating existing key
            self.cache.move_to_end(key)
            
            entry_size = self._get_entry_size(self.cache[key])
            print(f"Cache SET for key: {key[:16]}... (TTL: {ttl}s, size: {entry_size//1024}KB, total: {len(self.cache)}/{self.max_size})")
    
    async def delete(self, key: str):
        """Delete a specific key from cache"""
        async with self._lock:
            if key in self.cache:
                del self.cache[key]
                print(f"Cache DELETE for key: {key[:16]}...")
    
    async def clear(self):
        """Clear entire cache"""
        async with self._lock:
            count = len(self.cache)
            self.cache.clear()
            print(f"Cache CLEARED ({count} entries)")
    
    async def clear_prefix(self, prefix: str):
        """Clear all cache entries with a specific prefix"""
        async with self._lock:
            keys_to_delete = [k for k in self.cache.keys() if k.startswith(prefix)]
            for key in keys_to_delete:
                del self.cache[key]
            print(f"Cache CLEARED prefix '{prefix}' ({len(keys_to_delete)} entries)")
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        async with self._lock:
            now = time.time()
            total_entries = len(self.cache)
            expired_entries = sum(1 for entry in self.cache.values() if now >= entry['expires_at'])
            active_entries = total_entries - expired_entries
            total_size = self._get_total_size()
            
            return {
                'total_entries': total_entries,
                'active_entries': active_entries,
                'expired_entries': expired_entries,
                'max_size': self.max_size,
                'size_utilization_pct': (total_entries / self.max_size * 100) if self.max_size > 0 else 0,
                'total_size_bytes': total_size,
                'total_size_mb': total_size / (1024 * 1024),
                'max_memory_mb': self.max_memory_bytes / (1024 * 1024),
                'memory_utilization_pct': (total_size / self.max_memory_bytes * 100) if self.max_memory_bytes > 0 else 0,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate_pct': self._get_hit_rate(),
                'evictions': self._evictions
            }
    
    async def cleanup_expired(self):
        """Remove expired entries from cache"""
        async with self._lock:
            now = time.time()
            keys_to_delete = [
                key for key, entry in self.cache.items() 
                if now >= entry['expires_at']
            ]
            for key in keys_to_delete:
                del self.cache[key]
            if keys_to_delete:
                print(f"Cache cleanup removed {len(keys_to_delete)} expired entries")


def cached(ttl: int = 300, key_prefix: str = ""):
    """
    Decorator to cache async function results
    
    Usage:
        @cached(ttl=600, key_prefix="doctors")
        async def get_doctors_by_hospital(self, hospital_name: str):
            ...
    """
    def decorator(func: Callable):
        async def wrapper(self, *args, **kwargs):
            # Check if object has cache attribute
            if not hasattr(self, 'cache'):
                # No cache, just call the function
                return await func(self, *args, **kwargs)
            
            cache: QueryCache = self.cache
            
            # Generate cache key
            prefix = key_prefix or func.__name__
            cache_key = cache._generate_key(prefix, *args, **kwargs)
            
            # Try to get from cache
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Not in cache, call function
            result = await func(self, *args, **kwargs)
            
            # Store in cache (only if result is not None/empty)
            if result is not None:
                await cache.set(cache_key, result, ttl=ttl)
            
            return result
        
        return wrapper
    return decorator


# Cache invalidation helpers
async def invalidate_doctor_cache(cache: QueryCache, hospital_name: str = None):
    """Invalidate cache entries related to doctors"""
    if hospital_name:
        # Clear specific hospital's doctor cache
        await cache.clear_prefix(f"get_doctors_by_hospital_{hospital_name}")
        await cache.clear_prefix(f"get_doctors_with_patient_count_{hospital_name}")
    else:
        # Clear all doctor caches
        await cache.clear_prefix("get_doctors")


async def invalidate_patient_cache(cache: QueryCache, hospital_name: str = None):
    """Invalidate cache entries related to patients"""
    if hospital_name:
        await cache.clear_prefix(f"get_patients_by_hospital_{hospital_name}")
        await cache.clear_prefix(f"get_patients_with_doctor_info_{hospital_name}")
    else:
        await cache.clear_prefix("get_patients")


async def invalidate_appointment_cache(cache: QueryCache, hospital_name: str = None):
    """Invalidate cache entries related to appointments"""
    if hospital_name:
        await cache.clear_prefix(f"get_appointments_by_hospital_{hospital_name}")
    else:
        await cache.clear_prefix("get_appointments")
