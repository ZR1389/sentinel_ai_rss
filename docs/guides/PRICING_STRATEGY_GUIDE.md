# Pricing Strategy Guide

**Last Updated**: November 15, 2025  
**Status**: Recommendations for Pricing Page

---

## 🎯 Recommended Pricing Structure

### Option A: Standard SaaS Pricing (Recommended)

| Plan | Monthly Price | Annual Price | Savings |
|------|---------------|--------------|---------|
| **FREE** | $0 | $0 | - |
| **PRO** | $49/month | $490/year | $98 (17%) |
| **ENTERPRISE** | $199/month | $1,990/year | $398 (17%) |

**Why this pricing?**
- FREE tier creates viral growth (no credit card needed)
- $49/month PRO hits sweet spot for individual professionals
- $199/month ENTERPRISE targets corporate security teams
- 17% annual discount encourages longer commitment

---

### Option B: Lower Entry Point (If targeting broader market)

| Plan | Monthly Price | Annual Price | Savings |
|------|---------------|--------------|---------|
| **FREE** | $0 | $0 | - |
| **STARTER** | $19/month | $190/year | $38 (17%) |
| **PRO** | $49/month | $490/year | $98 (17%) |
| **ENTERPRISE** | $149/month | $1,490/year | $298 (17%) |

**Additional STARTER limits** (requires code changes):
```python
"STARTER": {
    "chat_messages_per_month": 100,
    "alerts_days": 14,
    "alerts_max_results": 50,
    "map_days": 14,
    "timeline_days": 14,
    "statistics_days": 14,
    "monitoring_days": 14,
}
```

---

### Option C: Aggressive Growth Pricing (Maximize signups)

| Plan | Monthly Price | Annual Price | Savings |
|------|---------------|--------------|---------|
| **FREE** | $0 | $0 | - |
| **PRO** | $29/month | $290/year | $58 (17%) |
| **ENTERPRISE** | $99/month | $990/year | $198 (17%) |

**Why lower prices?**
- Easier to convert FREE → PRO at $29/month
- Targets individual travelers, not just corporations
- Faster market penetration
- Can raise prices later with grandfathering

---

## 📊 Feature Comparison (For Pricing Page)

### Current Backend Implementation (Option A):

| Feature | FREE | PRO | ENTERPRISE |
|---------|------|-----|------------|
| **Monthly Price** | $0 | $49 | $199 |
| **AI Chat Messages** | 3/month | 1,000/month | 5,000/month |
| **Historical Data** | 7 days | 30 days | 90 days |
| **Map Alerts** | 30 per query | 100 per query | 500 per query |
| **Timeline View** | 7-day window | 30-day window | 90-day window |
| **Statistics Dashboard** | 7-day data | 30-day data | 90-day data |
| **Coverage Monitoring** | 7-day data | 30-day data | 90-day data |
| **Email Alerts** | ❌ | ✅ | ✅ |
| **Push Notifications** | ❌ | ✅ | ✅ |
| **Telegram Integration** | ❌ | ✅ | ✅ |
| **PDF Reports** | ❌ | ✅ | ✅ |
| **Real-time Updates** | ❌ | ✅ | ✅ |
| **API Access** | ❌ | ❌ | ✅ |
| **Priority Support** | ❌ | ❌ | ✅ |
| **Custom Integrations** | ❌ | ❌ | ✅ |
| **Dedicated Account Manager** | ❌ | ❌ | ✅ |

---

## 💡 Value Propositions

### FREE Plan - "Try Before You Buy"
**Headline**: "Get Started with Global Threat Intelligence"

**Key Benefits**:
- ✅ Access 7 days of verified threat data
- ✅ Try our AI threat analyst (3 free queries)
- ✅ View threats on interactive map
- ✅ No credit card required
- ✅ Perfect for casual travelers

**CTA**: "Start Free Trial" → Auto-upgrade prompt after 3 chat messages used

---

### PRO Plan - "For Serious Travelers & Security Professionals"
**Headline**: "Extended Intelligence for Travel Planning"

**Key Benefits**:
- ✅ 30-day historical threat data
- ✅ 1,000 AI chat queries per month
- ✅ Email & push notifications
- ✅ PDF threat reports
- ✅ Timeline analysis
- ✅ Priority email support

**Use Cases**:
- Travel risk managers planning trips
- Journalists covering conflict zones
- NGO workers in high-risk areas
- Business travelers to emerging markets
- Security consultants

**CTA**: "Upgrade to PRO" → 14-day money-back guarantee

---

### ENTERPRISE Plan - "Complete Intelligence Platform"
**Headline**: "Advanced Features for Corporate Security Teams"

**Key Benefits**:
- ✅ 90-day threat intelligence archive
- ✅ 5,000 AI chat queries per month
- ✅ Full API access for integrations
- ✅ Priority support + dedicated account manager
- ✅ Custom threat monitoring
- ✅ White-label reports
- ✅ SSO integration (optional add-on)
- ✅ Custom data retention policies

**Use Cases**:
- Fortune 500 security operations centers
- Government agencies
- Private security firms
- International corporations
- Crisis management teams

**CTA**: "Contact Sales" → Custom quote for 10+ seats

---

## 🎨 Pricing Page Design Recommendations

### Hero Section:
```
"Simple, Transparent Pricing"
"Start free. Upgrade when you need more."
```

### Plan Cards Layout:
```
┌─────────────┬─────────────┬─────────────┐
│    FREE     │     PRO     │ ENTERPRISE  │
│             │  ⭐ POPULAR │   CUSTOM    │
├─────────────┼─────────────┼─────────────┤
│    $0       │  $49/month  │ $199/month  │
│   forever   │  or $490/yr │ or $1990/yr │
├─────────────┼─────────────┼─────────────┤
│ 3 AI chats  │ 1,000 chats │ 5,000 chats │
│ 7-day data  │ 30-day data │ 90-day data │
│ Basic map   │ Full map    │ API access  │
│ ❌ Alerts   │ ✅ Alerts   │ ✅ Priority │
└─────────────┴─────────────┴─────────────┘
  [Try Free]  [Start Trial]  [Contact Us]
```

### FAQ Section:
**Q: Can I upgrade or downgrade anytime?**  
A: Yes! Upgrade instantly, downgrades take effect at end of billing cycle.

**Q: What happens to my data if I downgrade?**  
A: Your data is safe. You'll just see a smaller time window (e.g., 7 days instead of 30).

**Q: Do you offer refunds?**  
A: Yes, 14-day money-back guarantee on PRO and ENTERPRISE plans.

**Q: Is there a student discount?**  
A: Yes! 50% off PRO plan with valid .edu email.

**Q: Can I get a custom plan?**  
A: Contact sales for custom ENTERPRISE plans with tailored features.

---

## 🧮 Pricing Calculator (Optional)

### ROI Calculator for ENTERPRISE:
```
"How much does a security incident cost your organization?"

Average security incident cost: $4.45M
Risk reduction with Sentinel AI: 30%
Monthly savings: $111,250
Annual savings: $1,335,000

ENTERPRISE plan cost: $1,990/year
ROI: 66,983%
```

---

## 📈 Upsell Strategy

### When to show upgrade prompts:

1. **After 1st chat message** (FREE users):
   - Tooltip: "2 messages left this month. Upgrade to PRO for 1,000."

2. **After 3rd chat message** (FREE users):
   - Modal: "You've reached your monthly limit. Upgrade to continue chatting."
   - CTA: "Upgrade to PRO ($49/month)" vs "Stay on FREE (reset next month)"

3. **When viewing 7-day map data** (FREE users):
   - Banner: "Viewing last 7 days. Upgrade to PRO for 30-day history."

4. **When trying to enable email alerts** (FREE users):
   - Modal: "Email alerts are a PRO feature. Upgrade now?"

5. **When approaching 1,000 chat limit** (PRO users):
   - Email: "You've used 900/1,000 messages. Upgrade to ENTERPRISE for 5,000?"

---

## 💳 Payment Integration

### Recommended Payment Provider: Stripe

**Why Stripe?**
- ✅ Easy subscription management
- ✅ Automatic invoice generation
- ✅ PCI compliance handled
- ✅ Supports 135+ currencies
- ✅ 14-day trial management
- ✅ Proration for upgrades/downgrades

**Implementation Steps** (not included in current backend):
1. Add Stripe API key to Railway environment
2. Create webhook endpoint for subscription events
3. Update `users.plan` and `subscription_status` on payment
4. Send confirmation emails on upgrade/downgrade
5. Handle failed payments with grace period

---

## 🌍 Regional Pricing (Optional)

### Purchasing Power Parity (PPP) Pricing:

| Region | PRO Price | ENTERPRISE Price | Adjustment |
|--------|-----------|------------------|------------|
| **US/EU/UK** | $49/month | $199/month | Standard |
| **LATAM** | $29/month | $119/month | -40% |
| **Asia** | $34/month | $139/month | -30% |
| **Africa** | $24/month | $99/month | -50% |

**Implementation**: Detect user location via IP, offer regional pricing automatically.

---

## 🎁 Promotional Strategies

### Launch Offer:
- **50% off first 3 months** for early adopters
- Code: `SENTINEL50`
- Limited to first 1,000 PRO signups

### Referral Program:
- Refer a friend → both get 1 month PRO free
- Refer 5 friends → get ENTERPRISE for 6 months free

### Annual Discount:
- Pay annually → save 17% (2 months free)
- Auto-renews unless cancelled

### Student Discount:
- Valid .edu email → 50% off PRO plan
- Must verify annually

### Non-Profit Discount:
- Registered 501(c)(3) → 75% off ENTERPRISE plan
- Must provide EIN verification

---

## ✅ Recommended Action

**For Now**: Use **Option A** pricing structure ($0 / $49 / $199)

**Why?**
- ✅ Backend already configured for these limits
- ✅ Premium pricing positions you as serious security tool
- ✅ Easier to discount later than raise prices
- ✅ Targets corporate customers (higher LTV)
- ✅ FREE tier drives viral growth

**Monitor These Metrics**:
- FREE → PRO conversion rate (target: 5%)
- PRO → ENTERPRISE conversion rate (target: 15%)
- Monthly churn rate (target: <5%)
- Average customer lifetime value

**Adjust Pricing If**:
- FREE → PRO conversion < 2% after 3 months → Consider $29/month PRO
- PRO users consistently hit 1,000 chat limit → Add $79/month "PRO+" tier
- Many ENTERPRISE inquiries asking for lower price → Offer $149/month "TEAM" tier

---

**Questions?** Contact marketing team or check FREEMIUM_IMPLEMENTATION_SUMMARY.md for technical details.
