from fpdf import FPDF
from datetime import date
from threat_scorer import assess_threat_level
from rss_processor import get_clean_alerts
import os

# ✅ Fetch alerts (already cleaned and parsed)
raw_alerts = get_clean_alerts()

# ✅ Assess threat level per alert
scored_alerts = []
for alert in raw_alerts:
    text = f"{alert['title']}: {alert['summary']}"
    try:
        level = assess_threat_level(text)
    except Exception:
        level = "Unrated"
    scored_alerts.append({
        "title": alert["title"],
        "summary": alert["summary"],
        "link": alert["link"],
        "source": alert["source"],
        "level": level
    })

# ✅ Color map by threat level
def get_threat_color(level):
    if level == "Low":
        return (0, 150, 0)        # Green
    elif level == "Moderate":
        return (255, 165, 0)      # Orange
    elif level == "High":
        return (255, 0, 0)        # Red
    elif level == "Critical":
        return (139, 0, 0)        # Dark Red
    else:
        return (100, 100, 100)    # Gray for "Unrated" or unknown

# ✅ Custom PDF class
class PDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 16)
        self.set_text_color(237, 0, 0)
        self.cell(0, 10, f"Sentinel AI Daily Brief — {date.today().isoformat()}", ln=True, align='C')
        self.ln(10)

    def chapter_body(self, alerts):
        for alert in alerts:
            # 🔹 Title
            self.set_text_color(0)
            self.set_font("Arial", "B", 12)
            self.multi_cell(0, 10, f"📰 {alert['title']}", align='L')

            # 🔹 Source + Threat Level
            level_color = get_threat_color(alert["level"])
            self.set_text_color(100, 100, 100)
            self.set_font("Arial", "I", 11)
            self.cell(0, 8, f"Source: {alert['source']}", ln=True)
            self.set_text_color(*level_color)
            self.cell(0, 8, f"Threat Level: {alert['level']}", ln=True)

            # 🔹 Summary
            self.set_text_color(0)
            self.set_font("Arial", "", 12)
            self.multi_cell(0, 10, f"{alert['summary']}", align='L')

            # 🔹 Link
            if alert["link"]:
                self.set_text_color(0, 0, 255)
                self.set_font("Arial", "U", 11)
                self.cell(0, 10, alert["link"], ln=True, link=alert["link"])

            # 🔹 Spacing
            self.set_font("Arial", "", 12)
            self.set_text_color(0)
            self.ln(6)

# ✅ Generate and save PDF
pdf = PDF()
pdf.add_page()
pdf.chapter_body(scored_alerts)

# ✅ Output path
pdf_path = os.path.expanduser(f"~/Desktop/daily-brief-{date.today().isoformat()}.pdf")
pdf.output(pdf_path)

print(f"✅ PDF created: {pdf_path}")




