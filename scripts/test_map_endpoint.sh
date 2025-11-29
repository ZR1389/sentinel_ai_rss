#!/bin/bash
# Test /alerts/latest endpoint on Railway

echo "Testing map endpoint..."
echo ""

# Get a test token (you'll need to replace this with a real token from /auth/login)
TOKEN="${TEST_TOKEN:-YOUR_TOKEN_HERE}"

if [ "$TOKEN" = "YOUR_TOKEN_HERE" ]; then
    echo "❌ Please set TEST_TOKEN environment variable first:"
    echo "   export TEST_TOKEN='your_actual_jwt_token'"
    echo ""
    echo "Get token by:"
    echo "   curl -X POST https://sentinelairss-production.up.railway.app/auth/login \\"
    echo "        -H 'Content-Type: application/json' \\"
    echo "        -d '{\"email\":\"your@email.com\",\"password\":\"YourPass\"}' | jq -r .access_token"
    exit 1
fi

echo "1. Testing without filters..."
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://sentinelairss-production.up.railway.app/alerts/latest?limit=5" \
  | jq '{ok, features_count: (.features | length), first_feature: .features[0]}'

echo ""
echo "2. Testing with global query..."
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://sentinelairss-production.up.railway.app/alerts/latest?limit=10&days=7" \
  | jq '{ok, features_count: (.features | length), items_count: (.items | length)}'

echo ""
echo "3. Testing with location filter..."
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://sentinelairss-production.up.railway.app/alerts/latest?lat=40&lon=20&radius=500&limit=20" \
  | jq '{ok, features_count: (.features | length)}'

echo ""
echo "Done!"
