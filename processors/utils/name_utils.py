"""
processors/utils/name_utils.py
Name normalization utilities for processors.
Matches the scraper's name normalization patterns.
"""

import re
import unicodedata
from difflib import SequenceMatcher


def normalize_name(full_name: str) -> str:
    """
    Normalize player name for consistent lookups.
    Matches the scraper's normalization logic.
    
    'LeBron James' -> 'lebronjames'
    'P.J. Tucker' -> 'pjtucker'
    'De'Aaron Fox' -> 'dearonfox'
    """
    if not full_name:
        return ""
    
    # Convert to lowercase
    normalized = full_name.lower()
    
    # Remove all non-alphanumeric characters
    normalized = re.sub(r'[^a-z0-9]', '', normalized)
    
    return normalized


def clean_unicode_text(text: str) -> str:
    """
    Clean Unicode text - matches scraper's implementation.
    Converts accented characters to ASCII equivalents.
    
    Examples:
    - "Dāvis Bertāns" → "Davis Bertans"
    - "Nikola Jokić" → "Nikola Jokic"
    """
    if not text:
        return ""
    
    try:
        # Normalize Unicode to decomposed form
        normalized = unicodedata.normalize('NFD', text)
        
        # Remove combining characters (accents)
        ascii_text = ''.join(
            char for char in normalized 
            if unicodedata.category(char) != 'Mn'
        )
        
        # Ensure valid ASCII
        ascii_text = ascii_text.encode('ascii', 'ignore').decode('ascii')
        
        # Clean up spaces
        ascii_text = ' '.join(ascii_text.split())
        
        return ascii_text
        
    except Exception:
        # Fallback to simple ASCII conversion
        try:
            return text.encode('ascii', 'ignore').decode('ascii')
        except:
            return text


def calculate_similarity(name1: str, name2: str) -> float:
    """
    Calculate similarity between two names.
    Returns float between 0 and 1.
    """
    if not name1 or not name2:
        return 0.0
    
    return SequenceMatcher(None, name1, name2).ratio()


def find_fuzzy_match(lookup_name: str, candidates: list, threshold: float = 0.85):
    """
    Find fuzzy match for a name in a list of candidates.
    Returns best match if above threshold, else None.
    """
    best_match = None
    best_score = 0
    
    for candidate in candidates:
        score = calculate_similarity(lookup_name, candidate)
        if score > threshold and score > best_score:
            best_match = candidate
            best_score = score
    
    if best_match:
        return {
            "match": best_match,
            "score": best_score
        }
    
    return None