"""Server-side caching utilities for CloudSense"""

import time
import hashlib
import json
import logging
import os
import tempfile
from typing import Dict, Any, Optional, Union
from flask import current_app

logger = logging.getLogger(__name__)

# In-memory cache storage
_cache_storage: Dict[str, Dict[str, Any]] = {}
_cache_timestamps: Dict[str, float] = {}
_cache_stats = {
    'hits': 0,
    'misses': 0,
    'sets': 0,
    'evictions': 0
}

# Maximum cache size to prevent memory issues
MAX_CACHE_SIZE = 1000

# Persistent cache settings
CACHE_DIR = os.path.expanduser('~/.cloudsense-cache')
CACHE_INDEX_FILE = os.path.join(CACHE_DIR, 'cache_index.json')


def generate_cache_key(*args, **kwargs) -> str:
    """
    Generate a unique cache key from function arguments
    
    Args:
        *args: Function positional arguments
        **kwargs: Function keyword arguments
        
    Returns:
        str: Unique cache key
    """
    # Create a string representation of all arguments
    key_data = {
        'args': args,
        'kwargs': kwargs
    }
    
    # Serialize to JSON for consistent key generation
    key_string = json.dumps(key_data, sort_keys=True, default=str)
    
    # Generate MD5 hash for compact key
    key_hash = hashlib.md5(key_string.encode()).hexdigest()
    
    return f"cloudsense_cache_{key_hash}"


def get_cache_duration() -> int:
    """Get cache duration from config or default"""
    try:
        return current_app.config.get('CACHE_DURATION', 3600)
    except RuntimeError:
        # Outside app context, use default
        return 3600


def _ensure_cache_dir():
    """Ensure cache directory exists"""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)


def _get_cache_file_path(cache_key: str) -> str:
    """Get file path for cache entry"""
    safe_key = hashlib.md5(cache_key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{safe_key}.json")


def _load_cache_index() -> Dict[str, float]:
    """Load cache index from disk"""
    try:
        if os.path.exists(CACHE_INDEX_FILE):
            with open(CACHE_INDEX_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"Failed to load cache index: {e}")
    return {}


def _save_cache_index(index: Dict[str, float]):
    """Save cache index to disk"""
    try:
        _ensure_cache_dir()
        with open(CACHE_INDEX_FILE, 'w') as f:
            json.dump(index, f)
    except Exception as e:
        logger.debug(f"Failed to save cache index: {e}")


def _load_persistent_cache_entry(cache_key: str) -> Optional[Dict[str, Any]]:
    """Load cache entry from disk"""
    try:
        cache_file = _get_cache_file_path(cache_key)
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"Failed to load cache entry {cache_key[:20]}...: {e}")
    return None


def _save_persistent_cache_entry(cache_key: str, data: Dict[str, Any]):
    """Save cache entry to disk"""
    try:
        _ensure_cache_dir()
        cache_file = _get_cache_file_path(cache_key)
        with open(cache_file, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        logger.debug(f"Failed to save cache entry {cache_key[:20]}...: {e}")


def _cleanup_expired_persistent_cache():
    """Clean up expired persistent cache files"""
    try:
        if not os.path.exists(CACHE_DIR):
            return
        
        index = _load_cache_index()
        cache_duration = get_cache_duration()
        current_time = time.time()
        cleaned_keys = []
        
        for cache_key, timestamp in list(index.items()):
            if current_time - timestamp > cache_duration:
                # Remove expired entry
                cache_file = _get_cache_file_path(cache_key)
                if os.path.exists(cache_file):
                    os.remove(cache_file)
                del index[cache_key]
                cleaned_keys.append(cache_key)
        
        if cleaned_keys:
            _save_cache_index(index)
            logger.debug(f"Cleaned up {len(cleaned_keys)} expired persistent cache entries")
            
    except Exception as e:
        logger.debug(f"Failed to cleanup persistent cache: {e}")


def init_persistent_cache():
    """Initialize persistent cache (cleanup expired entries)"""
    _cleanup_expired_persistent_cache()


def get_cached_data(cache_key: str, custom_duration: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Get cached data if still valid (checks both memory and persistent cache)
    
    Args:
        cache_key: Unique cache key
        custom_duration: Override default cache duration
        
    Returns:
        Cached data if valid, None if expired or not found
    """
    global _cache_stats
    cache_duration = custom_duration or get_cache_duration()
    current_time = time.time()
    
    # First check in-memory cache
    if cache_key in _cache_storage:
        cache_age = current_time - _cache_timestamps[cache_key]
        if cache_age < cache_duration:
            _cache_stats['hits'] += 1
            logger.debug(f"Memory cache HIT for key: {cache_key[:20]}... (age: {cache_age:.1f}s)")
            return _cache_storage[cache_key]
        else:
            # Memory cache expired
            logger.debug(f"Memory cache EXPIRED for key: {cache_key[:20]}... (age: {cache_age:.1f}s)")
            evict_cache_entry(cache_key)
    
    # Check persistent cache
    try:
        index = _load_cache_index()
        if cache_key in index:
            cache_age = current_time - index[cache_key]
            if cache_age < cache_duration:
                # Load from persistent cache
                persistent_data = _load_persistent_cache_entry(cache_key)
                if persistent_data:
                    # Load back into memory cache
                    _cache_storage[cache_key] = persistent_data
                    _cache_timestamps[cache_key] = index[cache_key]
                    _cache_stats['hits'] += 1
                    logger.debug(f"Persistent cache HIT for key: {cache_key[:20]}... (age: {cache_age:.1f}s)")
                    return persistent_data
            else:
                # Persistent cache expired - clean it up
                logger.debug(f"Persistent cache EXPIRED for key: {cache_key[:20]}... (age: {cache_age:.1f}s)")
                cache_file = _get_cache_file_path(cache_key)
                if os.path.exists(cache_file):
                    os.remove(cache_file)
                del index[cache_key]
                _save_cache_index(index)
    except Exception as e:
        logger.debug(f"Error checking persistent cache: {e}")
    
    _cache_stats['misses'] += 1
    return None


def set_cached_data(cache_key: str, data: Dict[str, Any]) -> None:
    """
    Cache the data with timestamp (saves to both memory and persistent cache)
    
    Args:
        cache_key: Unique cache key
        data: Data to cache
    """
    global _cache_stats
    current_time = time.time()
    
    # Enforce maximum cache size
    if len(_cache_storage) >= MAX_CACHE_SIZE:
        evict_oldest_entries(int(MAX_CACHE_SIZE * 0.1))  # Remove 10% of entries
    
    # Store in memory cache
    _cache_storage[cache_key] = data
    _cache_timestamps[cache_key] = current_time
    _cache_stats['sets'] += 1
    
    # Store in persistent cache
    try:
        _save_persistent_cache_entry(cache_key, data)
        
        # Update cache index
        index = _load_cache_index()
        index[cache_key] = current_time
        _save_cache_index(index)
        
        logger.debug(f"Cache SET for key: {cache_key[:20]}... (memory + persistent, cache size: {len(_cache_storage)})")
    except Exception as e:
        logger.debug(f"Failed to save to persistent cache: {e}")
        logger.debug(f"Cache SET for key: {cache_key[:20]}... (memory only, cache size: {len(_cache_storage)})")


def evict_cache_entry(cache_key: str) -> None:
    """Remove a specific cache entry"""
    global _cache_stats
    
    if cache_key in _cache_storage:
        del _cache_storage[cache_key]
        del _cache_timestamps[cache_key]
        _cache_stats['evictions'] += 1


def evict_oldest_entries(count: int) -> None:
    """Evict the oldest cache entries"""
    if not _cache_timestamps:
        return
    
    # Sort by timestamp (oldest first)
    sorted_entries = sorted(_cache_timestamps.items(), key=lambda x: x[1])
    
    for cache_key, _ in sorted_entries[:count]:
        evict_cache_entry(cache_key)
    
    logger.debug(f"Evicted {count} oldest cache entries")


def clear_cache() -> None:
    """Clear all cached data (memory and persistent)"""
    global _cache_storage, _cache_timestamps, _cache_stats
    
    # Clear memory cache
    entries_cleared = len(_cache_storage)
    _cache_storage.clear()
    _cache_timestamps.clear()
    
    # Clear persistent cache
    try:
        if os.path.exists(CACHE_DIR):
            import shutil
            shutil.rmtree(CACHE_DIR)
        logger.debug(f"Cache cleared: {entries_cleared} memory entries and persistent cache removed")
    except Exception as e:
        logger.debug(f"Cache cleared: {entries_cleared} memory entries removed (persistent cache clear failed: {e})")


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics"""
    total_requests = _cache_stats['hits'] + _cache_stats['misses']
    hit_rate = (_cache_stats['hits'] / total_requests * 100) if total_requests > 0 else 0
    
    return {
        'total_entries': len(_cache_storage),
        'hits': _cache_stats['hits'],
        'misses': _cache_stats['misses'],
        'sets': _cache_stats['sets'],
        'evictions': _cache_stats['evictions'],
        'hit_rate_percent': round(hit_rate, 2),
        'total_requests': total_requests,
        'max_cache_size': MAX_CACHE_SIZE
    }


def get_cache_entry_info(cache_key: str) -> Optional[Dict[str, Any]]:
    """Get information about a specific cache entry (checks both memory and persistent cache)"""
    cache_duration = get_cache_duration()
    current_time = time.time()
    
    # Check memory cache first
    if cache_key in _cache_storage:
        cached_at = _cache_timestamps[cache_key]
        cache_age = current_time - cached_at
        remaining_time = cache_duration - cache_age
        
        return {
            'cached_at': cached_at,
            'age_seconds': cache_age,
            'remaining_seconds': max(0, remaining_time),
            'is_expired': cache_age >= cache_duration,
            'source': 'memory'
        }
    
    # Check persistent cache
    try:
        index = _load_cache_index()
        if cache_key in index:
            cached_at = index[cache_key]
            cache_age = current_time - cached_at
            remaining_time = cache_duration - cache_age
            
            return {
                'cached_at': cached_at,
                'age_seconds': cache_age,
                'remaining_seconds': max(0, remaining_time),
                'is_expired': cache_age >= cache_duration,
                'source': 'persistent'
            }
    except Exception as e:
        logger.debug(f"Error getting persistent cache info: {e}")
    
    return None


def cache_result(cache_duration: Optional[int] = None):
    """
    Decorator to cache function results
    
    Args:
        cache_duration: Override default cache duration
        
    Usage:
        @cache_result()
        def expensive_function(arg1, arg2):
            return expensive_computation(arg1, arg2)
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Generate cache key from function name and arguments
            cache_key = generate_cache_key(func.__name__, *args, **kwargs)
            
            # Try to get cached result
            cached_data = get_cached_data(cache_key, cache_duration)
            if cached_data is not None:
                return cached_data
            
            # Cache miss - call the actual function  
            logger.debug(f"Cache MISS for {func.__name__} - fetching fresh data")
            result = func(*args, **kwargs)
            
            # Cache the result
            if result and not isinstance(result, dict) or 'error' not in result:
                set_cached_data(cache_key, result)
            
            return result
        
        return wrapper
    return decorator


def invalidate_cache_pattern(pattern: str) -> int:
    """
    Invalidate cache entries matching a pattern
    
    Args:
        pattern: Pattern to match in cache keys
        
    Returns:
        Number of entries invalidated
    """
    keys_to_remove = [key for key in _cache_storage.keys() if pattern in key]
    
    for key in keys_to_remove:
        evict_cache_entry(key)
    
    logger.debug(f"Invalidated {len(keys_to_remove)} cache entries matching pattern: {pattern}")
    return len(keys_to_remove)


def cleanup_expired_cache() -> int:
    """
    Clean up expired cache entries
    
    Returns:
        Number of expired entries removed
    """
    current_time = time.time()
    cache_duration = get_cache_duration()
    
    expired_keys = [
        key for key, timestamp in _cache_timestamps.items()
        if current_time - timestamp > cache_duration
    ]
    
    for key in expired_keys:
        evict_cache_entry(key)
    
    if expired_keys:
        logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")
    
    return len(expired_keys)
