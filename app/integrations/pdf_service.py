from typing import Any


def generate_pdf(html_content: str) -> bytes:
    """
    Synchronous WeasyPrint render.
    """
    try:
        from weasyprint import HTML
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "WeasyPrint is required to generate PDFs. "
            "Install it to use pdf_service.generate_pdf()."
        ) from exc

    return HTML(string=html_content).write_pdf()
