#!/usr/bin/env python3
"""
File: shared/utils/player_name_normalizer.py

Player name normalization utilities for consistent player name handling across all processors.

This module provides standardized name normalization functions to ensure consistent
name matching between different data sources (NBA.com, Basketball Reference, Ball Don't Lie, etc.)
"""

import re
import unicodedata
from typing import Optional


def normalize_name_for_lookup(name: str) -> str:
    """
    Create normalized lookup key from player name for database matching.
    
    This is the primary normalization function used across all processors
    for consistent name matching and database lookups.
    
    Args:
        name: Original player name (e.g., "LeBron James Jr.", "José Alvarado")
        
    Returns:
        Normalized name suitable for lookups (e.g., "lebronjamesjr", "josealvarado")
        
    Examples:
        >>> normalize_name_for_lookup("LeBron James Jr.")
        'lebronjamesjr'
        >>> normalize_name_for_lookup("José Alvarado")
        'josealvarado'
        >>> normalize_name_for_lookup("O'Neal")
        'oneal'
        >>> normalize_name_for_lookup("Dāvis Bertāns")
        'davisbertans'
    """
    if not name:
        return ""
    
    # Convert to lowercase first
    normalized = name.lower()
    
    # Remove/normalize diacritics and accents (ā → a, é → e, etc.)
    normalized = remove_diacritics(normalized)
    
    # Remove common punctuation and separators
    normalized = normalized.replace(' ', '')      # spaces
    normalized = normalized.replace('-', '')      # hyphens
    normalized = normalized.replace("'", '')      # apostrophes
    normalized = normalized.replace('.', '')      # periods (NEW - this was missing)
    normalized = normalized.replace(',', '')      # commas
    normalized = normalized.replace('_', '')      # underscores
    
    # Remove any remaining non-alphanumeric characters
    normalized = re.sub(r'[^a-z0-9]', '', normalized)
    
    return normalized


def remove_diacritics(text: str) -> str:
    """
    Remove diacritics and accents from text, converting to ASCII equivalents.
    
    Examples:
        >>> remove_diacritics("José")
        'jose'
        >>> remove_diacritics("Dāvis Bertāns")
        'davis bertans'
        >>> remove_diacritics("Bogdanović")
        'bogdanovic'
    """
    if not text:
        return ""
    
    # Normalize to NFD (decomposed form) to separate base chars from diacritics
    nfd = unicodedata.normalize('NFD', text)
    
    # Filter out combining characters (diacritics/accents)
    ascii_text = ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')
    
    return ascii_text


def extract_suffix(name: str) -> tuple[str, Optional[str]]:
    """
    Extract name suffix (Jr., Sr., II, III, etc.) from player name.
    
    Args:
        name: Full player name
        
    Returns:
        Tuple of (name_without_suffix, suffix_or_none)
        
    Examples:
        >>> extract_suffix("Charlie Brown Jr.")
        ('Charlie Brown', 'Jr.')
        >>> extract_suffix("John Smith III")
        ('John Smith', 'III')
        >>> extract_suffix("LeBron James")
        ('LeBron James', None)
    """
    if not name:
        return "", None
    
    # Define common suffixes - SORTED BY LENGTH DESC to avoid partial matches
    # e.g., "III" must be checked before "II" since "iii".endswith("ii") is True
    suffixes = [
        'Junior', 'Senior',  # Longest first
        'Jr.', 'Sr.',
        'III', 'IV', 'V', 'II',  # Roman numerals: III before II!
        '3rd', '4th', '5th', '2nd',  # Ordinals
        'Jr', 'Sr',  # Without periods last
    ]
    
    name_trimmed = name.strip()
    
    for suffix in suffixes:
        # Check if name ends with this suffix (case insensitive)
        if name_trimmed.lower().endswith(suffix.lower()):
            # Extract the base name (without suffix)
            base_name = name_trimmed[:-len(suffix)].strip()
            return base_name, suffix
    
    return name_trimmed, None


def standardize_name_format(first_name: str, last_name: str, suffix: str = None) -> str:
    """
    Create standardized full name format.
    
    Args:
        first_name: Player's first name
        last_name: Player's last name  
        suffix: Optional suffix (Jr., Sr., etc.)
        
    Returns:
        Standardized full name
        
    Examples:
        >>> standardize_name_format("LeBron", "James")
        'LeBron James'
        >>> standardize_name_format("Charlie", "Brown", "Jr.")
        'Charlie Brown Jr.'
    """
    if not first_name and not last_name:
        return ""
    
    parts = []
    if first_name:
        parts.append(first_name.strip())
    if last_name:
        parts.append(last_name.strip())
    if suffix:
        parts.append(suffix.strip())
    
    return ' '.join(parts)


# NOTE: create_name_variants function removed as it's not currently needed
# The processor only requires simple normalization for lookup keys
# This function could be added back later if comprehensive name matching is needed


# Backward compatibility aliases for existing code
def normalize_name(name: str) -> str:
    """Alias for normalize_name_for_lookup for backward compatibility."""
    return normalize_name_for_lookup(name)


def handle_suffix_names(name: str) -> str:
    """Alias for extract_suffix()[0] for backward compatibility."""
    base_name, _ = extract_suffix(name)
    return base_name


# Test cases for validation
if __name__ == "__main__":
    # Test cases
    test_names = [
        "LeBron James",
        "LeBron James Jr.",
        "Charlie Brown Jr.",
        "José Alvarado", 
        "Dāvis Bertāns",
        "Bogdanović",
        "O'Neal",
        "De'Andre Jordan",
        "Karl-Anthony Towns",
        "Taurean Prince",
        "P.J. Tucker",
        "T.J. McConnell",
        "Michael Porter Jr.",
        "",
    ]
    
    print("Player Name Normalization Test Results:")
    print("=" * 60)
    
    for name in test_names:
        if not name:
            continue
            
        try:
            # Test core normalization function
            normalized = normalize_name_for_lookup(name)
            ascii_name = remove_diacritics(name)
            base_name, suffix = extract_suffix(name)
            
            print(f"\nOriginal: '{name}'")
            print(f"Normalized: '{normalized}'")
            print(f"ASCII: '{ascii_name}'")
            print(f"Without suffix: '{base_name}'")
            print(f"Suffix: {suffix}")
            
            # Show the specific fixes this addresses
            if '.' in name:
                print(f"  ✓ Fixed period issue: '{name}' → '{normalized}'")
            if any(char in name for char in ["'", "-"]):
                print(f"  ✓ Fixed punctuation: removed apostrophes/hyphens")
            if suffix:
                print(f"  ✓ Detected suffix: '{suffix}'")
                
        except Exception as e:
            print(f"ERROR with '{name}': {e}")
    
    print(f"\n{'=' * 60}")
    print("Testing specific issues from your database:")
    print(f"{'=' * 60}")
    
    # Test the specific cases from the user's database
    problem_cases = [
        ("Charlie Brown Jr.", "charliebrownjr.", "charliebrownjr"),  # current vs expected
        ("P.J. Tucker", "p.j.tucker", "pjtucker"),
        ("T.J. McConnell", "t.j.mcconnell", "tjmcconnell"),
        ("Michael Porter Jr.", "michaelporterjr.", "michaelporterjr"),
    ]
    
    for original, current_bad, expected_good in problem_cases:
        new_result = normalize_name_for_lookup(original)
        status = "✅ FIXED" if new_result == expected_good else "❌ STILL BROKEN"
        print(f"\n{original}:")
        print(f"  Current (bad): '{current_bad}'")
        print(f"  Expected: '{expected_good}'")
        print(f"  New result: '{new_result}' {status}")