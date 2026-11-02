"""Live suite against https://thirds.ai. Skipped unless THIRDS_LIVE=1 and THIRDS_API_KEY is set.

Spends at most 3 credits (three successful renders). The other checks are free
because failed or refused requests cost nothing. Set THIRDS_LIVE_OUT to keep the files.
"""

import io
import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from thirds_render import ThirdsClient, ThirdsError, render_html

from .testapp.models import Invoice

LIVE = os.environ.get("THIRDS_LIVE") == "1" and bool(os.environ.get("THIRDS_API_KEY", "").strip())
OUT = Path(os.environ.get("THIRDS_LIVE_OUT") or tempfile.mkdtemp(prefix="thirds-live-"))
MEDIA = tempfile.mkdtemp(prefix="thirds-live-media-")
SPENT = []


def spend(label):
    SPENT.append(label)
    assert len(SPENT) <= 3, f"live budget exceeded: {SPENT}"


@unittest.skipUnless(LIVE, "set THIRDS_LIVE=1 and THIRDS_API_KEY to run the live suite")
@override_settings(THIRDS_API_KEY=os.environ.get("THIRDS_API_KEY"), MEDIA_ROOT=MEDIA,
                   THIRDS_RENDER={"POLL_INTERVAL": 1.0, "DEADLINE": 120})
class LiveTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        print(f"\nlive credits spent by this suite: {len(SPENT)} {SPENT}")

    def test_1_admin_action_pdf_into_filefield(self):
        invoice = Invoice.objects.create(number="LIVE-1", customer="Zoë Łukasiewicz", total="1234.50")
        admin = User.objects.create_superuser("admin", "a@example.test", "pw")
        self.client.force_login(admin)
        spend("admin action pdf")
        response = self.client.post("/admin/testapp/invoice/", {"action": "thirds_render_pdf", "_selected_action": [invoice.pk]}, follow=True)
        self.assertContains(response, "Rendered 1 file.")
        invoice.refresh_from_db()
        self.assertEqual(invoice.pdf.name, "invoices/invoice-LIVE-1.pdf")
        with invoice.pdf.open("rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertGreater(len(data), 1000)
        (OUT / "admin-action-invoice-LIVE-1.pdf").write_bytes(data)

    def test_2_command_png_card(self):
        target = OUT / "command-card-1200x630.png"
        ctx = OUT / "card-context.json"
        ctx.write_text('{"title": "Invoice LIVE-2", "subtitle": "Zoë Łukasiewicz"}', encoding="utf-8")
        out = io.StringIO()
        spend("command png")
        call_command("thirds_render", "demo/card.html", str(target), "--context", str(ctx), "--width", "1200", "--height", "630",
                     "--reference", "django testapp command card", stdout=out)
        self.assertIn("image_", out.getvalue())
        data = target.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", data[16:24]), (1200, 630))

    def test_3_inline_template_with_data_pdf(self):
        spend("inline template pdf")
        result = render_html("<h1>Hello {{ name }}</h1><p>{{ note }}</p>", "pdf",
                             data={"name": "Zoë", "note": "<b>escaped</b>"},
                             pdf={"format": "A4"}, reference="django testapp inline template")
        self.assertTrue(result.content.startswith(b"%PDF-"))
        self.assertRegex(result.job_id, r"^pdf_[0-9a-f]{32}$")
        self.assertEqual(result.job["status"], "succeeded")
        self.assertNotIn("download", result.job)
        (OUT / "inline-template.pdf").write_bytes(result.content)

    def test_4_unknown_template_is_free(self):
        with self.assertRaises(ThirdsError) as cm:
            ThirdsClient().pdf(template_id="tpl_" + "0" * 32, data={})
        self.assertEqual(cm.exception.code, "template_not_found")

    def test_5_wrong_key_is_refused(self):
        fake = "thirds_" + "x" * 70
        with self.assertRaises(ThirdsError) as cm:
            ThirdsClient(api_key=fake).pdf("<p>x</p>")
        self.assertEqual(cm.exception.status, 401)
        self.assertNotIn(fake, str(cm.exception))


def tearDownModule():
    shutil.rmtree(MEDIA, ignore_errors=True)
