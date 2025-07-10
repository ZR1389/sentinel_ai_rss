from fpdf import FPDF
from fpdf.enums import XPos, YPos
from datetime import date
from threat_scorer import assess_threat_level
from rss_processor import get_clean_alerts
import os
from pathlib import Path

def get_threat_color(level):
    if level == "Low":
        return (0, 150, 0)
    elif level == "Moderate":
        return (255, 165, 0)
    elif level == "High":
        return (255, 0, 0)
    elif level == "Critical":
        return (139, 0, 0)
    else:
        return (100, 100, 100)

def generate_pdf(output_path=None):
    raw_alerts = get_clean_alerts()
    scored_alerts = []

    for alert in raw_alerts:
        try:
            level = assess_threat_level(f"{alert['title']}: {alert['summary']}")
        except Exception:
            level = "Unrated"

        scored_alerts.append({
            "title": alert["title"],
            "summary": alert["summary"],
            "link": alert.get("link"),
            "source": alert["source"],
            "level": level
        })

    class PDF(FPDF):
        def header(self):
            self.set_font("NotoSans", "", 16)
            self.set_text_color(0)
            self.cell(0, 10, f"Sentinel AI Daily Brief — {date.today().isoformat()}", ln=True, align='C')
            self.ln(8)

        def footer(self):
            self.set_y(-15)
            self.set_font("NotoSans", "", 8)
            self.set_text_color(100)
            self.cell(0, 10, "Sentinel AI Powered by Zika Risk | www.zikarisk.com", align='C')

        def chapter_body(self, alerts):
            for alert in alerts:
                self.set_text_color(0)
                self.set_font("NotoSans", "", 13)
                self.multi_cell(0, 8, alert["title"], align='L')
                self.ln(1)

                self.set_text_color(100, 100, 100)
                self.set_font("NotoSans", "", 10)
                self.cell(0, 6, f"Source: {alert['source']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                self.set_text_color(*get_threat_color(alert["level"]))
                self.set_font("NotoSans", "", 10)
                self.cell(0, 6, f"Threat Level: {alert['level']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                self.set_text_color(0)
                self.set_font("NotoSans", "", 11)
                self.multi_cell(0, 7, alert["summary"], align='L')

                self.ln(6)

    pdf = PDF()
    font_path = Path(__file__).parent / "fonts" / "NotoSans-Regular.ttf"
    pdf.add_font("NotoSans", "", str(font_path), uni=True)
    pdf.set_font("NotoSans", "", 12)
    pdf.add_page()
    pdf.chapter_body(scored_alerts)

    if output_path is None:
        output_path = str(Path.home() / f"Desktop/daily-brief-{date.today().isoformat()}.pdf")
    pdf.output(output_path)
    print(f"PDF created: {output_path}")
    return output_path

if __name__ == "__main__":
    generate_pdf()