import html
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

try:
    from weasyprint import HTML
    _HAVE_WEASY = True
except Exception as e:  # pragma: no cover - environment dependent
    logger.warning("WeasyPrint not available: %s", e)
    _HAVE_WEASY = False

try:
    import markdown  # type: ignore
    _HAVE_MARKDOWN = True
except Exception:  # pragma: no cover - optional dependency
    _HAVE_MARKDOWN = False

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
OUTPUT_DIR_DEFAULT = os.path.join("downloads", "intelligence_reports")


def _render_body_html(report_body: str) -> str:
    """Render markdown to HTML, with a fallback to preformatted text."""
    safe_text = report_body or ""
    if _HAVE_MARKDOWN:
        try:
            return markdown.markdown(safe_text)
        except Exception as e:  # pragma: no cover
            logger.debug("markdown render failed, falling back: %s", e)
    escaped = html.escape(safe_text)
    return f"<pre class='report-body'>{escaped}</pre>"


def generate_intelligence_report_pdf(
    report_title: str,
    report_body: str,
    request_meta: Dict[str, Any],
    analyst_email: Optional[str] = None,
    user_email: Optional[str] = None,
    output_dir: Optional[str] = None,
    file_tag: Optional[str] = None
) -> Optional[str]:
    """Render an intelligence report PDF using a dedicated template.

    Args:
        report_title: Title to display in the PDF.
        report_body: Markdown or plaintext body of the report.
        request_meta: Metadata for the request (type, target, scope, etc.).
        analyst_email: Optional analyst email for attribution.
        user_email: Optional requester email for header/footer context.
        output_dir: Optional override for output directory.
        file_tag: Optional tag to prefix the filename (defaults to request ID).

    Returns:
        Absolute path to the generated PDF, or None on failure.
    """
    if not _HAVE_WEASY:
        logger.error("Cannot generate intelligence PDF: WeasyPrint missing")
        return None

    output_dir = output_dir or OUTPUT_DIR_DEFAULT
    os.makedirs(output_dir, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"])
    )
    template = env.get_template("intelligence_report.html")

    body_html = _render_body_html(report_body)
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    report_id = request_meta.get("id") if isinstance(request_meta, dict) else None
    client_name = user_email or request_meta.get("client_name") if isinstance(request_meta, dict) else None
    report_date = datetime.utcnow().strftime("%Y-%m-%d")

    context = {
        "title": report_title or request_meta.get("title") or "Intelligence Report",
        "body_html": body_html,
        "generated_at": now_str,
        "analyst_email": analyst_email,
        "user_email": user_email,
        "request": request_meta or {},
        "report_id": report_id or file_tag or uuid.uuid4().hex,
        "client_name": client_name or "Client",
        "report_date": report_date,
        "classification": "CONFIDENTIAL",
        "prepared_by": "Zika Risk Intelligence",
    }

    try:
        html_str = template.render(**context)
        tag = file_tag or request_meta.get("id") or uuid.uuid4().hex
        filename = f"{tag}_{int(datetime.utcnow().timestamp())}.pdf"
        pdf_path = os.path.join(output_dir, filename)
        HTML(string=html_str, base_url=TEMPLATE_DIR).write_pdf(pdf_path)
        logger.info("Generated intelligence report PDF at %s", pdf_path)
        return os.path.abspath(pdf_path)
    except Exception as e:  # pragma: no cover - IO heavy
        logger.error("Failed to render intelligence report PDF: %s", e)
        return None
