"""Vercel entry point: serves every /api/* request with the same handler as backend/app.py.

vercel.json sends /api/<path> here as /api/index?__path=<path>. Vercel may hand over either the
original path or the rewritten one, so original_path() accepts both.
"""

import sys
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import RequestHandler  # noqa: E402


def original_path(raw: str) -> str:
    """The path the client asked for, without the rewrite's __path parameter."""
    parts = urlsplit(raw)
    query = parse_qsl(parts.query, keep_blank_values=True)
    rewritten = [value for name, value in query if name == "__path"]
    rest = urlencode([(name, value) for name, value in query if name != "__path"])
    path = parts.path
    if rewritten and path.rstrip("/") in ("/api/index", "/api/index.py", "/api"):
        # The value may arrive encoded once more than the query string itself.
        path = "/api/" + quote(unquote("/".join(rewritten)), safe="/:")
    return f"{path}?{rest}" if rest else path


class handler(RequestHandler):  # Vercel looks for this exact name
    def parse_request(self) -> bool:
        parsed = super().parse_request()
        if parsed:
            self.path = original_path(self.path)
        return parsed
