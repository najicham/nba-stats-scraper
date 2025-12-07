"""
Hash utility functions for ProcessPool workers.

These functions are module-level and picklable for use with ProcessPoolExecutor.
"""
import hashlib
from typing import Any, Dict, List, Optional


def compute_hash_from_dict(data: Dict[str, Any], fields: Optional[List[str]] = None) -> str:
    """
    Compute SHA256 hash (16 chars) from a dictionary.

    This is a static function suitable for ProcessPool workers.

    Args:
        data: Dictionary containing values to hash
        fields: Optional list of fields to include. If None, uses all keys.

    Returns:
        16-character hex hash string
    """
    if fields is None:
        fields = sorted(data.keys())

    hash_values = []
    for field in sorted(fields):
        value = data.get(field)
        # Normalize value to string representation
        if value is None:
            normalized = "NULL"
        elif isinstance(value, (int, float)):
            normalized = str(value)
        elif isinstance(value, str):
            normalized = value.strip()
        else:
            normalized = str(value)
        hash_values.append(f"{field}:{normalized}")

    # Create canonical string (sorted for consistency)
    canonical_string = "|".join(hash_values)

    # Compute SHA256 hash
    hash_bytes = canonical_string.encode('utf-8')
    sha256_hash = hashlib.sha256(hash_bytes).hexdigest()

    # Return first 16 characters
    return sha256_hash[:16]


def compute_hash_static(record: dict, hash_fields: list) -> str:
    """
    Compute SHA256 hash (16 chars) from meaningful fields only.

    Static version for ProcessPool workers. Alias for compute_hash_from_dict
    with explicit field list.

    Args:
        record: Dictionary containing the record data
        hash_fields: List of field names to include in hash

    Returns:
        16-character hex hash string
    """
    hash_values = []
    for field in hash_fields:
        value = record.get(field)
        # Normalize value to string representation
        if value is None:
            normalized = "NULL"
        elif isinstance(value, (int, float)):
            normalized = str(value)
        elif isinstance(value, str):
            normalized = value.strip()
        else:
            normalized = str(value)
        hash_values.append(f"{field}:{normalized}")

    # Create canonical string (sorted for consistency)
    canonical_string = "|".join(sorted(hash_values))

    # Compute SHA256 hash
    hash_bytes = canonical_string.encode('utf-8')
    sha256_hash = hashlib.sha256(hash_bytes).hexdigest()

    # Return first 16 characters
    return sha256_hash[:16]
