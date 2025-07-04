from fpdf import FPDF
from datetime import date
from threat_scorer import assess_threat_level
from rss_processor import get_clean_alerts, FEEDS
from translator import translate_text
import os

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

def generate_translated_pdf(language="en"):
    raw_alerts = get_clean_alerts()
    scored_alerts = []

    for alert in raw_alerts:
        text = f"{alert['title']}: {alert['summary']}"
        try:
            level = assess_threat_level(text)
        except Exception:
            level = "Unrated"

        translated_title = translate_text(alert["title"], target_lang=language)
        translated_summary = translate_text(alert["summary"], target_lang=language)

        scored_alerts.append({
            "title": translated_title,
            "summary": translated_summary,
            "link": alert["link"],
            "source": alert["source"],
            "level": level
        })

    class PDF(FPDF):
        def header(self):
            self.set_font("NotoSans", "", 16)
            self.set_text_color(237, 0, 0)
            heading = translate_text("Sentinel AI Daily Brief", target_lang=language)
            self.cell(0, 10, f"{heading} — {date.today().isoformat()}", ln=True, align='C')
            self.ln(10)

        def chapter_body(self, alerts):
            for alert in alerts:
                self.set_text_color(0)
                self.set_font("NotoSans", "", 13)
                self.multi_cell(0, 10, f"{alert['title']}", align='L')

                level_color = get_threat_color(alert["level"])
                self.set_text_color(100, 100, 100)
                self.set_font("NotoSans", "", 11)
                src_label = translate_text("Source", target_lang=language)
                self.cell(0, 8, f"{src_label}: {alert['source']}", ln=True)

                self.set_text_color(*level_color)
                level_label = translate_text("Threat Level", target_lang=language)
                self.cell(0, 8, f"{level_label}: {alert['level']}", ln=True)

                self.set_text_color(0)
                self.set_font("NotoSans", "", 12)
                self.multi_cell(0, 10, f"{alert['summary']}", align='L')

                if alert["link"]:
                    self.set_text_color(0, 0, 255)
                    self.set_font("NotoSans", "", 11)
                    self.set_underline(True)
                    self.cell(0, 10, alert["link"], ln=True, link=alert["link"])
                    self.set_underline(False)

                self.set_font("NotoSans", "", 12)
                self.set_text_color(0)
                self.ln(6)

    pdf = PDF()
    pdf.add_page()

    # Register NotoSans font before use
    pdf.add_font("NotoSans", "", "fonts/NotoSans-Regular.ttf", uni=True)
    pdf.set_font("NotoSans", "", 12)

    pdf.chapter_body(scored_alerts)

    output_path = os.path.expanduser(f"~/Desktop/daily-brief-{language}-{date.today().isoformat()}.pdf")
    pdf.output(output_path)
    print(f"PDF created: {output_path}")
    return output_path
