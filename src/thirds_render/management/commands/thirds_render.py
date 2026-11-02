"""Render a Django template or a saved thirds.ai template to a file.

    python manage.py thirds_render invoices/invoice.html out/invoice.pdf --context ctx.json
    python manage.py thirds_render cards/og.html out/card.png --width 1200 --height 630
    python manage.py thirds_render --saved-template tpl_... out/card.png --data data.json
    python manage.py thirds_render --check
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ...client import ThirdsClient, ThirdsError
from ...shortcuts import render_saved_template, render_template

EXT = {".pdf": "pdf", ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}


def _json_file(path):
    if not path:
        return {}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CommandError(f"Could not read JSON from {path}: {e}") from None
    if not isinstance(value, dict):
        raise CommandError(f"{path} must hold one JSON object.")
    return value


class Command(BaseCommand):
    help = "Render a template to PDF or PNG with thirds.ai. The output type follows the file extension."

    def add_arguments(self, parser):
        parser.add_argument("template", nargs="?", help="Django template name, for example invoices/invoice.html")
        parser.add_argument("output", nargs="?", help="Output file: .pdf, .png, .jpg or .webp")
        parser.add_argument("--context", help="JSON file with the template context")
        parser.add_argument("--saved-template", help="Render this saved thirds.ai template id instead")
        parser.add_argument("--template-version", type=int, help="Saved template version (default: latest)")
        parser.add_argument("--data", help="JSON file with the saved template data")
        parser.add_argument("--width", type=int, help="Image width in pixels")
        parser.add_argument("--height", type=int, help="Image height in pixels")
        parser.add_argument("--page", help="PDF page format, for example A4 or Letter")
        parser.add_argument("--reference", help="Your reference, kept in the thirds.ai job history")
        parser.add_argument("--check", action="store_true", help="Only report whether a key is set. Sends nothing.")

    def handle(self, *args, **o):
        client = ThirdsClient()
        if o["check"]:
            self.stdout.write(f"API key: {'set' if client.has_key else 'missing'}. Base URL: {client.base_url}")
            return
        if o["saved_template"]:
            out = o["template"] if not o["output"] else o["output"]
        else:
            out = o["output"]
            if not o["template"]:
                raise CommandError("Give a template name, or --saved-template.")
        if not out:
            raise CommandError("Give an output file.")
        out = Path(out)
        kind = EXT.get(out.suffix.lower())
        if not kind:
            raise CommandError("The output file must end in .pdf, .png, .jpg, .jpeg or .webp.")
        if not client.has_key:
            raise CommandError("THIRDS_API_KEY is not set. Nothing was sent.")

        options = {"reference": o["reference"]} if o["reference"] else {}
        if kind == "pdf":
            if o["page"]:
                options["pdf"] = {"format": o["page"]}
        else:
            options.update(width=o["width"], height=o["height"])
        try:
            if o["saved_template"]:
                result = render_saved_template(o["saved_template"], _json_file(o["data"]), kind,
                                               version=o["template_version"], client=client, **options)
            else:
                result = render_template(o["template"], _json_file(o["context"]), kind=kind, client=client, **options)
        except ThirdsError as e:
            raise CommandError(str(e)) from None
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(result.content)
        self.stdout.write(self.style.SUCCESS(f"Wrote {out} ({len(result.content)} bytes, job {result.job_id})"))
