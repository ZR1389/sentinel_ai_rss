#!/usr/bin/env python3
"""Test itinerary manager functions (syntax check)."""

import sys

try:
    # Test imports
    from utils.itinerary_manager import (
        create_itinerary,
        list_itineraries,
        get_itinerary,
        update_itinerary,
        delete_itinerary,
        get_itinerary_stats
    )
    print("✓ All itinerary_manager functions imported successfully")
    
    # Check function signatures
    import inspect
    
    funcs = [
        create_itinerary,
        list_itineraries,
        get_itinerary,
        update_itinerary,
        delete_itinerary,
        get_itinerary_stats
    ]
    
    for func in funcs:
        sig = inspect.signature(func)
        print(f"✓ {func.__name__}{sig}")
    
    print("\n✅ All syntax checks passed!")
    sys.exit(0)
    
except Exception as e:
    print(f"❌ Import/syntax error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
