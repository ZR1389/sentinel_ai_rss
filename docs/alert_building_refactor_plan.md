# Alert Building Refactor Plan

## Current Issues with _build_alert_from_entry

### Complexity Metrics:
- **~250 lines** in single function
- **4 levels deep** nested try/except blocks  
- **Multiple concerns** mixed together:
  - Content filtering
  - Location detection
  - Batch processing
  - Geocoding
  - Alert construction
  - Error handling

### Problems:
1. **Unmaintainable**: Too complex to understand or modify safely
2. **Untestable**: Combinatorial explosion of test cases
3. **Error-prone**: Each nesting level adds failure modes
4. **Violates SRP**: Single function doing 6+ different jobs

## Refactoring Strategy

### Phase 1: Extract Pure Functions
- Content validation (filtering)
- Location extraction pipeline 
- Alert construction
- Source tag parsing

### Phase 2: Extract Classes
- LocationExtractor with strategy pattern
- AlertBuilder with fluent interface
- BatchProcessor with clear interface

### Phase 3: Simplify Main Function
- Chain of responsibility pattern
- Early returns for clarity
- Single level error handling

### Benefits:
- **Testable**: Each component can be unit tested
- **Maintainable**: Clear separation of concerns  
- **Extensible**: Easy to add new location strategies
- **Reliable**: Simpler error handling patterns
