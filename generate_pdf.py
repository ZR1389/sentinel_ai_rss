# generate_pdf.py — paid-only, unmetered • v2025-08-13
from __future__ import annotations
import os
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger("generate_pdf")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

try:
    from plan_utils import user_has_paid_plan as _is_paid
except Exception:
    def _is_paid(_email: str) -> bool:
        return False

# Using reportlab for a portable baseline; replace with wkhtmltopdf if you prefer
try:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas
    _HAVE_RL = True
except Exception as e:
    logger.info("reportlab not installed: %s", e)
    _HAVE_RL = False

def generate_pdf_advisory(user_email: str, title: str, body_text: str, out_path: Optional[str] = None) -> Optional[str]:
    """
    Paid-only, unmetered PDF export. Returns path to PDF or None if denied/failed.
    """
    if not _is_paid(user_email):
        logger.debug("pdf export denied: user not on paid plan (%s)", user_email)
        return None
    if not _HAVE_RL:
        logger.warning("reportlab missing; cannot generate PDF")
        return None

    out_path = out_path or f"/tmp/sentinel_advisory_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    try:
        c = canvas.Canvas(out_path, pagesize=LETTER)
        w, h = LETTER
        x, y = 50, h - 50
        c.setFont("Helvetica-Bold", 16)
        c.drawString(x, y, title[:120])
        y -= 24
        c.setFont("Helvetica", 10)

        # basic wrapping
        for line in body_text.splitlines():
            for chunk in [line[i:i+95] for i in range(0, len(line), 95)]:
                y -= 14
                if y < 50:
                    c.showPage()
                    y = h - 50
                    c.setFont("Helvetica", 10)
                c.drawString(x, y, chunk)
        c.showPage()
        c.save()
        return out_path
    except Exception as e:
        logger.error("generate_pdf_advisory failed: %s", e)
        return None
