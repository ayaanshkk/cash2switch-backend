# backend/numeric_parse.py
"""
Utility functions for safely parsing numeric values from database fields
that may be stored as VARCHAR or have commas/whitespace
"""


def safe_float(value):
    """
    Safely convert a value to float, handling:
    - None/empty values → 0.0
    - Strings with commas (e.g., "1,234.56")
    - Strings with whitespace
    - Already numeric values
    
    Args:
        value: Any value that should be converted to float
        
    Returns:
        float: Parsed float value or 0.0 if parsing fails
        
    Examples:
        >>> safe_float("1,234.56")
        1234.56
        >>> safe_float(None)
        0.0
        >>> safe_float("  123  ")
        123.0
        >>> safe_float(123)
        123.0
    """
    try:
        if value is None or value == '':
            return 0.0
        
        # If already a number, just convert
        if isinstance(value, (int, float)):
            return float(value)
        
        # Handle string values
        if isinstance(value, str):
            # Remove commas and whitespace
            cleaned = value.replace(',', '').strip()
            if not cleaned:
                return 0.0
            return float(cleaned)
        
        # Try direct conversion for other types
        return float(value)
        
    except (ValueError, TypeError, AttributeError):
        # If all else fails, return 0.0
        return 0.0


def safe_int(value):
    """
    Safely convert a value to int, handling:
    - None/empty values → 0
    - Strings with commas
    - Floating point values (rounds down)
    
    Args:
        value: Any value that should be converted to int
        
    Returns:
        int: Parsed int value or 0 if parsing fails
    """
    try:
        if value is None or value == '':
            return 0
        
        # If already an int, return it
        if isinstance(value, int):
            return value
        
        # If float, convert to int
        if isinstance(value, float):
            return int(value)
        
        # Handle string values
        if isinstance(value, str):
            cleaned = value.replace(',', '').strip()
            if not cleaned:
                return 0
            return int(float(cleaned))  # Convert via float to handle "123.45" → 123
        
        return int(value)
        
    except (ValueError, TypeError, AttributeError):
        return 0


def safe_decimal(value):
    """
    Safely convert a value to Decimal for precise financial calculations
    
    Args:
        value: Any value that should be converted to Decimal
        
    Returns:
        Decimal: Parsed Decimal value or Decimal('0') if parsing fails
    """
    from decimal import Decimal, InvalidOperation
    
    try:
        if value is None or value == '':
            return Decimal('0')
        
        # If already a Decimal, return it
        if isinstance(value, Decimal):
            return value
        
        # Handle numeric types
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        
        # Handle string values
        if isinstance(value, str):
            cleaned = value.replace(',', '').strip()
            if not cleaned:
                return Decimal('0')
            return Decimal(cleaned)
        
        return Decimal(str(value))
        
    except (ValueError, TypeError, AttributeError, InvalidOperation):
        return Decimal('0')