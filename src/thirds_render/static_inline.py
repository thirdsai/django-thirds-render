"""The renderer runs on thirds.ai, so it cannot reach your /static/ URLs on localhost or a
private network. These helpers put local CSS, scripts and images into the page itself."""

import base64
import mimetypes
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles import finders


def static_path(url):
    """The file on disk for a /static/ URL, or None."""
    static_url = getattr(settings, "STATIC_URL", None)
    if not static_url:
        return None
    prefix = urlsplit(static_url).path
    path = urlsplit(url).path
    if not prefix or not path.startswith(prefix):
        return None
    return finders.find(path[len(prefix):]) or None


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def inline_static(html):
    def style(m):
        path = static_path(m["href"])
        return f"<style>{_read(path).decode()}</style>" if path else m[0]

    def script(m):
        path = static_path(m["src"])
        if not path:
            return m[0]
        return "<script>" + _read(path).decode().replace("</script", "<\\/script") + "</script>"

    def src(m):
        path = static_path(m["src"])
        if not path:
            return m[0]
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        return f'src="data:{mime};base64,{base64.b64encode(_read(path)).decode()}"'

    html = re.sub(r'<link\b[^>]*\brel="stylesheet"[^>]*\bhref="(?P<href>[^"]+)"[^>]*>', style, html)
    html = re.sub(r'<link\b[^>]*\bhref="(?P<href>[^"]+)"[^>]*\brel="stylesheet"[^>]*>', style, html)
    html = re.sub(r'<script\b[^>]*\bsrc="(?P<src>[^"]+)"[^>]*>\s*</script>', script, html)
    return re.sub(r'\bsrc="(?P<src>[^"]+)"', src, html)
