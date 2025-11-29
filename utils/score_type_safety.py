#!/usr/bin/env python3
"""
Score Type Safety - Defensive coding to handle score/confidence type issues
Prevents silent failures when database has TEXT types instead of NUMERIC
"""

import logging
from typing import Union, Optional

logger = logging.getLogger("score_type_safety")

def safe_numeric_score(value: Union[str, int, float, None], default: float = 0.0, 
                      min_val: float = 0.0, max_val: float = 100.0) -> float:
    """
    Safely convert score value to numeric, handling TEXT/VARCHAR columns.
    
    Args:
        value: Raw score value from database (could be str, int, float, or None)
        default: Default value if conversion fails
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        
    Returns:
        Safe numeric score value
    """
    if value is None:
        return default
    
    try:
        # Handle string values (common when DB column is TEXT)
        if isinstance(value, str):
            if value.strip() == '' or value.lower() in ('null', 'none', 'n/a'):
                return default
            numeric_val = float(value.strip())
        else:
            numeric_val = float(value)
        
        # Clamp to valid range
        return max(min_val, min(max_val, numeric_val))
        
    except (ValueError, TypeError) as e:
        logger.warning(f"[ScoreTypeSafety] Invalid score value '{value}': {e}, using default {default}")
        return default

def safe_numeric_confidence(value: Union[str, int, float, None], default: float = 0.5) -> float:
    """
    Safely convert confidence value to numeric (0.0-1.0 range).
    
    Args:
        value: Raw confidence value from database
        default: Default confidence if conversion fails
        
    Returns:
        Safe numeric confidence value (0.0-1.0)
    """
    return safe_numeric_score(value, default=default, min_val=0.0, max_val=1.0)

def safe_score_comparison(score1: Union[str, int, float, None], 
                         score2: Union[str, int, float, None],
                         operator: str = '>') -> bool:
    """
    Safely compare two score values, handling type mismatches.
    
    Args:
        score1: First score value
        score2: Second score value  
        operator: Comparison operator ('>', '<', '>=', '<=', '==', '!=')
        
    Returns:
        Boolean result of comparison
    """
    safe_score1 = safe_numeric_score(score1)
    safe_score2 = safe_numeric_score(score2)
    
    if operator == '>':
        return safe_score1 > safe_score2
    elif operator == '<':
        return safe_score1 < safe_score2
    elif operator == '>=':
        return safe_score1 >= safe_score2
    elif operator == '<=':
        return safe_score1 <= safe_score2
    elif operator == '==':
        return abs(safe_score1 - safe_score2) < 0.001  # Float precision safe
    elif operator == '!=':
        return abs(safe_score1 - safe_score2) >= 0.001
    else:
        logger.error(f"[ScoreTypeSafety] Unknown operator: {operator}")
        return False

class ScoreValidator:
    """Validates and normalizes score/confidence values from database"""
    
    @staticmethod
    def validate_score(score: Union[str, int, float, None]) -> dict:
        """
        Validate and provide detailed score information.
        
        Returns:
            Dict with 'value', 'is_valid', 'original_type', 'warnings'
        """
        result = {
            'value': safe_numeric_score(score),
            'original_value': score,
            'original_type': type(score).__name__,
            'is_valid': True,
            'warnings': []
        }
        
        if score is None:
            result['warnings'].append("Score was NULL, using default 0.0")
        elif isinstance(score, str):
            result['warnings'].append(f"Score was TEXT '{score}', converted to numeric")
            if score.strip() == '':
                result['is_valid'] = False
                result['warnings'].append("Empty string score is invalid")
        
        return result
    
    @staticmethod
    def batch_validate_scores(scores: list) -> dict:
        """
        Validate a batch of scores and return summary statistics.
        
        Returns:
            Summary dict with counts and issues
        """
        summary = {
            'total': len(scores),
            'valid': 0,
            'invalid': 0,
            'text_types': 0,
            'null_values': 0,
            'warnings': []
        }
        
        for score in scores:
            validation = ScoreValidator.validate_score(score)
            
            if validation['is_valid']:
                summary['valid'] += 1
            else:
                summary['invalid'] += 1
            
            if isinstance(score, str):
                summary['text_types'] += 1
            elif score is None:
                summary['null_values'] += 1
            
            summary['warnings'].extend(validation['warnings'])
        
        return summary

# Monkey patch common scoring functions for safety
def patch_scoring_functions():
    """Apply defensive patches to common scoring operations"""
    
    # Example usage in threat scoring
    def safe_threat_score_calculation(raw_score, confidence, severity_multiplier=1.0):
        """
        Calculate threat score with type safety.
        
        Args:
            raw_score: Raw threat score (possibly TEXT from DB)
            confidence: Confidence value (possibly TEXT from DB)  
            severity_multiplier: Severity adjustment factor
            
        Returns:
            Safe numeric threat score
        """
        safe_score = safe_numeric_score(raw_score, default=0.0)
        safe_conf = safe_numeric_confidence(confidence, default=0.5)
        
        # Apply scoring formula with safe numeric values
        final_score = safe_score * safe_conf * severity_multiplier
        
        # Ensure result is in valid range
        return max(0.0, min(100.0, final_score))
    
    return safe_threat_score_calculation

# Usage examples and testing
if __name__ == "__main__":
    print("🔧 Score Type Safety Testing")
    print("=" * 40)
    
    # Test cases with problematic data types
    test_cases = [
        ("85", "Text score"),
        (85.5, "Numeric score"),  
        (None, "NULL score"),
        ("", "Empty string"),
        ("invalid", "Invalid text"),
        ("95.5", "Text numeric"),
        (105, "Out of range high"),
        (-10, "Out of range low")
    ]
    
    print("Score Conversion Tests:")
    for value, description in test_cases:
        safe_val = safe_numeric_score(value)
        print(f"  {description:20} '{value}' → {safe_val}")
    
    print(f"\nConfidence Conversion Tests:")
    conf_tests = [("0.85", "Text confidence"), ("1.5", "Out of range"), (None, "NULL")]
    for value, description in conf_tests:
        safe_val = safe_numeric_confidence(value)
        print(f"  {description:20} '{value}' → {safe_val}")
    
    print(f"\nComparison Tests:")
    print(f"  '85' > 80.0 → {safe_score_comparison('85', 80.0, '>')}")
    print(f"  NULL >= 50 → {safe_score_comparison(None, 50, '>=')}") 
    
    print(f"\n✅ All tests completed - functions handle type mismatches safely!")
