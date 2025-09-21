#!/usr/bin/env python3
"""
File: processors/utils/name_utils.py

Utility functions for player name normalization.
Used across multiple processors for consistent name handling.
"""

import re
import unicodedata
from typing import Optional


def normalize_name(name: str) -> Optional[str]:
    """
    Normalize a player name for consistent matching.
    
    Args:
        name: Player name to normalize
        
    Returns:
        Normalized name in lowercase without spaces or special characters
        
    Examples:
        "LeBron James" -> "lebronjames"
        "D'Angelo Russell" -> "dangelorussell"
        "P.J. Tucker" -> "pjtucker"
        "Nikola Jokić" -> "nikolajokic"
    """
    if not name:
        return None
    
    # Convert to lowercase
    normalized = name.lower()
    
    # Remove accents and special characters
    normalized = ''.join(
        c for c in unicodedata.normalize('NFD', normalized)
        if unicodedata.category(c) != 'Mn'
    )
    
    # Remove apostrophes, periods, hyphens, and other punctuation
    normalized = re.sub(r"['\.\-\s]+", '', normalized)
    
    # Remove any remaining non-alphanumeric characters
    normalized = re.sub(r'[^a-z0-9]', '', normalized)
    
    return normalized


def calculate_similarity(name1: str, name2: str) -> float:
    """
    Calculate similarity score between two names.
    
    Args:
        name1: First name
        name2: Second name
        
    Returns:
        Similarity score between 0 and 1
    """
    if not name1 or not name2:
        return 0.0
    
    # Normalize both names
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)
    
    if norm1 == norm2:
        return 1.0
    
    # Calculate Levenshtein distance ratio
    # This is a simple implementation - could be replaced with more sophisticated algorithm
    longer = max(len(norm1), len(norm2))
    if longer == 0:
        return 1.0
        
    distance = levenshtein_distance(norm1, norm2)
    return (longer - distance) / longer


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate the Levenshtein distance between two strings.
    
    Args:
        s1: First string
        s2: Second string
        
    Returns:
        The minimum number of single-character edits required
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # j+1 instead of j since previous_row and current_row are one character longer than s2
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def parse_full_name(full_name: str) -> dict:
    """
    Parse a full name into components.
    
    Args:
        full_name: Full player name
        
    Returns:
        Dictionary with 'first', 'last', and optional 'suffix' keys
        
    Examples:
        "LeBron James" -> {'first': 'LeBron', 'last': 'James'}
        "Gary Payton II" -> {'first': 'Gary', 'last': 'Payton', 'suffix': 'II'}
    """
    if not full_name:
        return {}
    
    # Handle suffixes (Jr., III, etc.)
    suffix_pattern = r'\s+(Jr\.?|Sr\.?|I{1,3}|IV|V)$'
    suffix_match = re.search(suffix_pattern, full_name, re.IGNORECASE)
    
    suffix = None
    if suffix_match:
        suffix = suffix_match.group(1)
        full_name = full_name[:suffix_match.start()]
    
    # Split name
    parts = full_name.strip().split()
    
    result = {}
    if len(parts) >= 2:
        result['first'] = parts[0]
        result['last'] = ' '.join(parts[1:])  # Handle multi-word last names
    elif len(parts) == 1:
        result['first'] = parts[0]
        result['last'] = ''
    
    if suffix:
        result['suffix'] = suffix
    
    return result