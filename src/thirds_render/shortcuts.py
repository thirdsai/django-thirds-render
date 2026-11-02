"""Helpers for views, models and the admin."""

import io
import re

from django.core.files.base import ContentFile
from django.http import FileResponse
from django.template.loader import render_to_string

from .client import ThirdsClient
from .static_inline import inline_static as _inline_static

KINDS = ("pdf", "png", "jpeg", "webp")


def _client(client):
    return client or ThirdsClient()


def _send(client, kind, html=None, template_id=None, data=None, version=None, width=None, height=None, **options):
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if kind == "pdf":
        return client.pdf(html, template_id=template_id, data=data, version=version, **options)
    return client.image(html, template_id=template_id, data=data, version=version, format=kind,
                        width=width, height=height, **options)


def render_html(html, kind="pdf", *, data=None, inline_static=True, client=None, **options):
    """Render an HTML string. With ``data``, thirds.ai fills it as an inline Jinja style template."""
    if inline_static:
        html = _inline_static(html)
    return _send(_client(client), kind, html=html, data=data, **options)


def render_template(template_name, context=None, request=None, kind="pdf", *, inline_static=True, client=None,
                    **options):
    """Render a Django template with your context, then send the HTML to thirds.ai."""
    html = render_to_string(template_name, context or {}, request=request)
    return render_html(html, kind, inline_static=inline_static, client=client, **options)


def render_saved_template(template_id, data=None, kind="pdf", *, version=None, client=None, **options):
    """Render a template saved in your thirds.ai account."""
    return _send(_client(client), kind, template_id=template_id, data=data or {}, version=version, **options)


def safe_filename(name, fallback="render"):
    """A name the API and storage both accept: letters, digits, space, dot, dash, underscore."""
    name = re.sub(r"[^A-Za-z0-9 ._-]+", "-", str(name)).strip(" .-") or fallback
    name = re.sub(r"\.{2,}", ".", name)
    return name[:100]


def file_response(result, filename, as_attachment=True):
    """A FileResponse for a RenderResult."""
    name = filename if filename.lower().endswith("." + result.extension) else f"{filename}.{result.extension}"
    return FileResponse(io.BytesIO(result.content), as_attachment=as_attachment, filename=name,
                        content_type=result.media_type)


def save_to_field(instance, field_name, result, filename=None, save=True):
    """Store a RenderResult in a FileField or ImageField. Returns the stored name."""
    base = safe_filename(filename or f"{instance._meta.model_name}-{instance.pk}")
    if not base.lower().endswith("." + result.extension):
        base = f"{base}.{result.extension}"
    getattr(instance, field_name).save(base, ContentFile(result.content), save=save)
    return getattr(instance, field_name).name
