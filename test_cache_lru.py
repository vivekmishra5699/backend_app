"""
Test script to verify LRU cache functionality
"""
import asyncio
from query_cache import QueryCache


async def test_lru_cache():
    print("=" * 60)
    print("Testing LRU Cache with Size Limits")
    print("=" * 60)
    
    # Create a small cache for testing (max 5 entries, 1MB)
    cache = QueryCache(default_ttl=60, max_size=5, max_memory_mb=1)
    
    print("\n1. Adding 5 entries (should fit)...")
    for i in range(5):
        await cache.set(f"key_{i}", f"value_{i}")
    
    stats = await cache.get_stats()
    print(f"✓ Total entries: {stats['total_entries']}/{stats['max_size']}")
    print(f"✓ Memory usage: {stats['total_size_mb']:.3f}MB / {stats['max_memory_mb']:.1f}MB")
    
    print("\n2. Adding 6th entry (should trigger LRU eviction)...")
    await cache.set("key_5", "value_5")
    
    stats = await cache.get_stats()
    print(f"✓ Total entries: {stats['total_entries']}/{stats['max_size']}")
    print(f"✓ Total evictions: {stats['evictions']}")
    
    print("\n3. Checking if oldest entry (key_0) was evicted...")
    value = await cache.get("key_0")
    if value is None:
        print("✓ key_0 was evicted (LRU working correctly)")
    else:
        print("✗ key_0 still exists (LRU not working)")
    
    print("\n4. Checking if newer entries exist...")
    for i in range(1, 6):
        value = await cache.get(f"key_{i}")
        if value:
            print(f"✓ key_{i} exists")
    
    print("\n5. Accessing key_1 to make it recently used...")
    await cache.get("key_1")
    
    print("\n6. Adding another entry (should evict key_2, not key_1)...")
    await cache.set("key_6", "value_6")
    
    key_1_exists = await cache.get("key_1") is not None
    key_2_exists = await cache.get("key_2") is not None
    
    if key_1_exists and not key_2_exists:
        print("✓ LRU working perfectly! key_1 (recently accessed) kept, key_2 evicted")
    else:
        print(f"✗ LRU issue: key_1={key_1_exists}, key_2={key_2_exists}")
    
    print("\n7. Final cache statistics:")
    stats = await cache.get_stats()
    print(f"   Total entries: {stats['total_entries']}/{stats['max_size']}")
    print(f"   Active entries: {stats['active_entries']}")
    print(f"   Memory usage: {stats['total_size_mb']:.3f}MB")
    print(f"   Hit rate: {stats['hit_rate_pct']:.1f}%")
    print(f"   Hits: {stats['hits']}, Misses: {stats['misses']}")
    print(f"   Total evictions: {stats['evictions']}")
    print(f"   Size utilization: {stats['size_utilization_pct']:.1f}%")
    print(f"   Memory utilization: {stats['memory_utilization_pct']:.1f}%")
    
    print("\n8. Testing cache cleanup...")
    await cache.cleanup_expired()
    stats = await cache.get_stats()
    print(f"✓ After cleanup: {stats['total_entries']} entries remain")
    
    print("\n9. Testing cache clear...")
    await cache.clear()
    stats = await cache.get_stats()
    print(f"✓ After clear: {stats['total_entries']} entries remain")
    
    print("\n" + "=" * 60)
    print("✅ LRU Cache Test Complete!")
    print("=" * 60)


async def test_ttl_expiration():
    print("\n" + "=" * 60)
    print("Testing TTL Expiration")
    print("=" * 60)
    
    # Create cache with short TTL for testing
    cache = QueryCache(default_ttl=2, max_size=100, max_memory_mb=10)
    
    print("\n1. Adding entry with 2 second TTL...")
    await cache.set("test_key", "test_value")
    
    print("2. Immediately retrieving (should HIT)...")
    value = await cache.get("test_key")
    print(f"✓ Got value: {value}")
    
    print("3. Waiting 3 seconds...")
    await asyncio.sleep(3)
    
    print("4. Retrieving after expiration (should MISS)...")
    value = await cache.get("test_key")
    if value is None:
        print("✓ Entry expired correctly")
    else:
        print(f"✗ Entry should have expired but got: {value}")
    
    stats = await cache.get_stats()
    print(f"\nStats - Hits: {stats['hits']}, Misses: {stats['misses']}, Hit rate: {stats['hit_rate_pct']:.1f}%")
    
    print("\n" + "=" * 60)
    print("✅ TTL Test Complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_lru_cache())
    asyncio.run(test_ttl_expiration())
