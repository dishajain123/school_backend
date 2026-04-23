import os
import sys


def _ensure_macos_dyld_paths() -> None:
    """Make Homebrew shared libs visible to cffi on macOS."""
    if sys.platform != "darwin":
        return

    paths = [
        "/opt/homebrew/lib",  # Apple Silicon Homebrew
        "/usr/local/lib",     # Intel Homebrew/macOS default
    ]
    existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    current = [p for p in existing.split(":") if p]
    changed = False
    for path in paths:
        if path not in current and os.path.isdir(path):
            current.append(path)
            changed = True
    if changed:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(current)


def generate_pdf(html_content: str) -> bytes:
    """
    Synchronous WeasyPrint render.
    """
    _ensure_macos_dyld_paths()

    try:
        from weasyprint import HTML
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "PDF generator dependency is not available. "
            "Install WeasyPrint system libraries (glib/pango/cairo) "
            "to enable server-side PDF generation."
        ) from exc
    try:
        return HTML(string=html_content).write_pdf()
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "PDF generation failed in WeasyPrint. "
            "Ensure native libraries are installed (glib/pango/cairo)."
        ) from exc
