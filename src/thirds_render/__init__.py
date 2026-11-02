"""Render Django templates and HTML to PDF and PNG with the thirds.ai API."""

from .client import RenderResult, ThirdsClient, ThirdsError
from .shortcuts import (
    file_response,
    render_html,
    render_saved_template,
    render_template,
    save_to_field,
)

__all__ = [
    "RenderResult",
    "ThirdsClient",
    "ThirdsError",
    "file_response",
    "render_html",
    "render_saved_template",
    "render_template",
    "save_to_field",
]
__version__ = "0.1.0"
