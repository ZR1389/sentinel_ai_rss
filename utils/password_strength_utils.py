# password_strength_utils.py — simple password policy helpers

import re

# Precompile for speed/readability
_UPPER = re.compile(r'[A-Z]')
_LOWER = re.compile(r'[a-z]')
_DIGIT = re.compile(r'\d')
# Treat ANY non-alphanumeric as special (covers _ - + = / \ ~ ` ; ' [ ] etc.)
_SPECIAL = re.compile(r'[^A-Za-z0-9]')
_WHITESPACE = re.compile(r'\s')

def is_strong_password(password: str, *, min_length: int = 8, allow_whitespace: bool = False) -> bool:
    """
    Returns True if password meets strength requirements:
      - At least `min_length` characters (default 8)
      - Contains ≥1 uppercase, ≥1 lowercase, ≥1 digit
      - Contains ≥1 non-alphanumeric character
      - (Optional) Disallow whitespace unless allow_whitespace=True

    Notes:
      - ASCII character classes; non-ASCII letters aren’t counted toward upper/lower checks.
    """
    if not isinstance(password, str):
        return False

    if len(password) < min_length:
        return False
    if not _UPPER.search(password):
        return False
    if not _LOWER.search(password):
        return False
    if not _DIGIT.search(password):
        return False
    if not _SPECIAL.search(password):
        return False
    if not allow_whitespace and _WHITESPACE.search(password):
        return False

    return True
