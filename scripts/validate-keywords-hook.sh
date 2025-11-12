#!/bin/bash
#
# Pre-commit hook for threat keywords validation
#
# This script validates threat_keywords.json before allowing commits.
# Install by running: ln -sf ../../scripts/validate-keywords-hook.sh .git/hooks/pre-commit
#

# Exit on any error
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🔍 Validating threat keywords before commit...${NC}"

# Check if threat_keywords.json is being modified
if git diff --cached --name-only | grep -q "config/threat_keywords.json"; then
    echo -e "${YELLOW}📝 threat_keywords.json modified, running validation...${NC}"
    
    # Check if validation script exists
    if [ ! -f "validate_keywords.py" ]; then
        echo -e "${RED}❌ validate_keywords.py not found${NC}"
        echo -e "${RED}   Please ensure validation script is present${NC}"
        exit 1
    fi
    
    # Run the validation script
    if python validate_keywords.py --path config/threat_keywords.json; then
        echo -e "${GREEN}✅ Keyword validation passed${NC}"
    else
        echo -e "${RED}❌ Keyword validation failed${NC}"
        echo -e "${RED}   Please fix the issues above before committing${NC}"
        echo -e "${YELLOW}   Run: python validate_keywords.py --path config/threat_keywords.json${NC}"
        exit 1
    fi
    
    # Check if keywords can be loaded by the application
    echo -e "${YELLOW}🔧 Testing keywords integration...${NC}"
    if python -c "
from keywords_loader import _load_keyword_data, validate_keywords
import logging
logging.basicConfig(level=logging.WARNING)
try:
    data = _load_keyword_data()
    validate_keywords(data)
    print('✅ Keywords integration test passed')
except Exception as e:
    print(f'❌ Keywords integration test failed: {e}')
    exit(1)
"; then
        echo -e "${GREEN}✅ Keywords integration test passed${NC}"
    else
        echo -e "${RED}❌ Keywords integration test failed${NC}"
        echo -e "${RED}   Keywords file is valid but cannot be loaded by application${NC}"
        exit 1
    fi
    
    # Optional: Check for large changes
    ADDED_LINES=$(git diff --cached --numstat config/threat_keywords.json | cut -f1)
    REMOVED_LINES=$(git diff --cached --numstat config/threat_keywords.json | cut -f2)
    
    if [ "$ADDED_LINES" -gt 50 ] || [ "$REMOVED_LINES" -gt 50 ]; then
        echo -e "${YELLOW}⚠️  Large change detected: +${ADDED_LINES}/-${REMOVED_LINES} lines${NC}"
        echo -e "${YELLOW}   Consider reviewing the change carefully${NC}"
        echo -e "${YELLOW}   Add 'LARGE_CHANGE_OK' to commit message to bypass this warning${NC}"
        
        # Check if override is in commit message
        COMMIT_MSG=$(git log --format=%B -n 1 HEAD 2>/dev/null || echo "")
        if [[ ! "$COMMIT_MSG" =~ LARGE_CHANGE_OK ]]; then
            echo -e "${RED}❌ Large change not approved${NC}"
            echo -e "${YELLOW}   Add 'LARGE_CHANGE_OK' to your commit message if this is intentional${NC}"
            # Don't exit for large changes, just warn
            # exit 1
        fi
    fi
    
else
    echo -e "${GREEN}✅ threat_keywords.json not modified, skipping validation${NC}"
fi

# Check for other Python files that might import keywords
PYTHON_FILES=$(git diff --cached --name-only | grep "\.py$" || true)

if [ -n "$PYTHON_FILES" ]; then
    echo -e "${YELLOW}🐍 Checking Python files for keywords imports...${NC}"
    
    for file in $PYTHON_FILES; do
        if [ -f "$file" ] && grep -q "keywords_loader\|threat_keywords" "$file"; then
            echo -e "${YELLOW}   📄 $file uses keywords, validating imports...${NC}"
            
            # Basic syntax check
            if ! python -m py_compile "$file"; then
                echo -e "${RED}❌ Syntax error in $file${NC}"
                exit 1
            fi
        fi
    done
    
    echo -e "${GREEN}✅ Python files validation passed${NC}"
fi

echo -e "${GREEN}🎉 All validations passed! Commit allowed.${NC}"
exit 0
