"""Mocked suite: everything runs against tests/mockapi.py on 127.0.0.1. No credits."""

import io
import json
import os
import re
import shutil
import struct
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from thirds_render import ThirdsClient, ThirdsError, file_response, render_html, render_saved_template, render_template, save_to_field
from thirds_render.client import build_body
from thirds_render.shortcuts import safe_filename

from .mockapi import MOCK_KEY, MockAPI
from .testapp.models import Invoice

API = MockAPI().__enter__()


def tearDownModule():
    API.__exit__(None, None, None)


def png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def mocked(**extra):
    return override_settings(THIRDS_API_KEY=MOCK_KEY,
                             THIRDS_RENDER={"BASE_URL": API.url, "POLL_INTERVAL": 0.01, "DEADLINE": 5, **extra})


class Base(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp(prefix="thirds-media-")
        self.addCleanup(shutil.rmtree, media, True)
        ctx = self.settings(MEDIA_ROOT=media)
        ctx.enable()
        self.addCleanup(ctx.disable)
        API.requests.clear()
        API.bodies.clear()

    def last_body(self):
        return API.bodies[-1]["body"]

    def api_calls(self):
        return [r for r in API.requests if r["path"].startswith("/v1/")]


@mocked()
class ClientTests(Base):
    def test_missing_key_sends_nothing(self):
        with override_settings(THIRDS_API_KEY=None), mock.patch.dict(os.environ, {}, clear=True):
            client = ThirdsClient()
            self.assertFalse(client.has_key)
            with self.assertRaises(ThirdsError) as cm:
                client.pdf("<p>hi</p>")
        self.assertEqual(cm.exception.code, "missing_key")
        self.assertEqual(API.requests, [])

    def test_key_falls_back_to_environment(self):
        with override_settings(THIRDS_API_KEY=None), mock.patch.dict(os.environ, {"THIRDS_API_KEY": MOCK_KEY}):
            self.assertTrue(ThirdsClient().has_key)
            self.assertTrue(ThirdsClient().pdf("<p>hi</p>").content.startswith(b"%PDF"))

    def test_repr_hides_key(self):
        self.assertNotIn(MOCK_KEY, repr(ThirdsClient()))
        self.assertIn("key=set", repr(ThirdsClient()))

    def test_pdf_raw_html(self):
        result = ThirdsClient().pdf("<h1>Hello</h1>", pdf={"format": "A4"}, reference="unit pdf")
        self.assertTrue(result.content.startswith(b"%PDF"))
        self.assertEqual(result.media_type, "application/pdf")
        self.assertEqual(result.extension, "pdf")
        self.assertRegex(result.job_id, r"^pdf_[0-9a-f]{32}$")
        self.assertNotIn("download", result.job)
        self.assertEqual(self.last_body(), {"html": "<h1>Hello</h1>", "pdf": {"format": "A4"}, "reference": "unit pdf"})
        post, get, download = API.requests
        self.assertEqual((post["method"], post["path"], post["auth"]), ("POST", "/v1/pdf", "ok"))
        self.assertTrue(post["idempotency_key"].startswith("django-"))
        self.assertTrue(post["user_agent"].startswith("django-thirds-render/"))
        self.assertEqual((get["method"], get["auth"]), ("GET", "ok"))
        self.assertEqual(download["path"], "/v1/downloads/<signed>")
        self.assertEqual(download["auth"], "none", "the signed download must not carry the key")

    def test_signed_link_not_kept(self):
        result = ThirdsClient().pdf("<p>x</p>")
        self.assertNotIn("/v1/downloads/", json.dumps(result.job))
        self.assertNotIn("/v1/downloads/", repr(result))

    def test_png_size(self):
        result = ThirdsClient().image("<h1>Card</h1>", width=1200, height=630)
        self.assertEqual(png_size(result.content), (1200, 630))
        self.assertEqual(result.media_type, "image/png")
        self.assertEqual(self.last_body()["image"], {"format": "png", "width": 1200, "height": 630})

    def test_inline_template_body(self):
        ThirdsClient().pdf("<h1>{{ name }}</h1>", data={"name": "Zoë"})
        self.assertEqual(self.last_body(), {"html": "<h1>{{ name }}</h1>", "data": {"name": "Zoë"}})

    def test_saved_template_body(self):
        ThirdsClient().image(template_id="tpl_" + "a" * 32, data={"title": "T"}, version=3)
        body = self.last_body()
        self.assertEqual((body["template_id"], body["data"], body["version"]), ("tpl_" + "a" * 32, {"title": "T"}, 3))
        self.assertNotIn("html", body)

    def test_exactly_one_input(self):
        with self.assertRaises(ValueError):
            build_body("<p></p>", "tpl_x", None, None, {})
        with self.assertRaises(ValueError):
            build_body(None, None, None, None, {})

    def test_bad_kind(self):
        with self.assertRaises(ValueError):
            ThirdsClient().render("gif", {"html": "x"})

    def test_failed_job(self):
        with self.assertRaises(ThirdsError) as cm:
            ThirdsClient().pdf("<p>{{ x }}</p>", data={"x": "MOCKFAIL"})
        self.assertEqual(cm.exception.code, "render_failed")
        self.assertRegex(cm.exception.job_id, r"^pdf_")

    def test_wrong_key(self):
        client = ThirdsClient(api_key="wrong-key-value-123")
        with self.assertRaises(ThirdsError) as cm:
            client.pdf("<p>x</p>")
        self.assertEqual((cm.exception.status, cm.exception.code), (401, "unauthorized"))
        self.assertNotIn("wrong-key-value-123", str(cm.exception))
        self.assertNotIn("wrong-key-value-123", repr(cm.exception))

    def test_template_not_found(self):
        with self.assertRaises(ThirdsError) as cm:
            ThirdsClient().pdf(template_id="tpl_" + "0" * 32, data={})
        self.assertEqual((cm.exception.status, cm.exception.code), (404, "template_not_found"))

    def test_timeout(self):
        client = ThirdsClient(deadline=0.2)
        with self.assertRaises(ThirdsError) as cm:
            client.pdf("<p>x</p>", reference="MOCKSLOW")
        self.assertEqual(cm.exception.code, "timeout")

    def test_network_error(self):
        client = ThirdsClient(base_url="http://127.0.0.1:9")
        with self.assertRaises(ThirdsError) as cm:
            client.pdf("<p>x</p>")
        self.assertEqual(cm.exception.code, "network")

    def test_own_idempotency_key(self):
        a = ThirdsClient().pdf("<p>same</p>", idempotency_key="order-42")
        b = ThirdsClient().pdf("<p>same</p>", idempotency_key="order-42")
        self.assertEqual(a.job_id, b.job_id)
        self.assertEqual([r["idempotency_key"] for r in API.requests if r["method"] == "POST"], ["order-42", "order-42"])

    def test_outside_django_settings(self):
        client = ThirdsClient(api_key=MOCK_KEY, base_url=API.url, timeout=10, deadline=5, poll_interval=0.01)
        self.assertTrue(client.pdf("<p>x</p>").content.startswith(b"%PDF"))


@mocked()
class ShortcutTests(Base):
    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(number="INV-1", customer="Zoë Łukasiewicz", total="1234.50")

    def test_render_template_inlines_static(self):
        result = render_template("demo/invoice.html", {"object": self.invoice})
        self.assertTrue(result.content.startswith(b"%PDF"))
        html = self.last_body()["html"]
        self.assertNotIn("/static/", html)
        self.assertIn("<style>body{font-family:Arial", html)
        self.assertIn('src="data:image/png;base64,', html)
        self.assertIn("Zoë Łukasiewicz", html)

    def test_inline_static_off(self):
        render_template("demo/invoice.html", {"object": self.invoice}, inline_static=False)
        self.assertIn('href="/static/demo/invoice.css"', self.last_body()["html"])

    def test_unknown_static_left_alone(self):
        render_html('<img src="https://example.com/a.png"><img src="/static/missing.png">')
        html = self.last_body()["html"]
        self.assertIn('src="https://example.com/a.png"', html)
        self.assertIn('src="/static/missing.png"', html)

    def test_render_html_png_with_data(self):
        result = render_html("<h1>{{ t }}</h1>", "png", data={"t": "x"}, width=800, height=400)
        self.assertEqual(png_size(result.content), (800, 400))
        self.assertEqual(self.last_body()["data"], {"t": "x"})

    def test_render_saved_template_pdf(self):
        render_saved_template("tpl_" + "b" * 32, {"n": 1}, pdf={"format": "Letter"})
        self.assertEqual(self.last_body()["pdf"], {"format": "Letter"})

    def test_bad_kind(self):
        with self.assertRaises(ValueError):
            render_html("<p></p>", "gif")
        self.assertEqual(API.requests, [])

    def test_save_to_field(self):
        result = render_template("demo/invoice.html", {"object": self.invoice})
        name = save_to_field(self.invoice, "pdf", result, filename="invoice INV-1")
        self.invoice.refresh_from_db()
        self.assertEqual(name, "invoices/invoice_INV-1.pdf")
        self.assertEqual(self.invoice.pdf.name, name)
        with self.invoice.pdf.open("rb") as f:
            self.assertTrue(f.read().startswith(b"%PDF"))

    def test_save_to_field_default_name_and_no_save(self):
        result = render_html("<p>x</p>", "png", width=320, height=200)
        save_to_field(self.invoice, "card", result, save=False)
        self.assertEqual(self.invoice.card.name, "cards/invoice-%d.png" % self.invoice.pk)
        self.assertEqual(Invoice.objects.get(pk=self.invoice.pk).card.name, "")

    def test_safe_filename(self):
        self.assertEqual(safe_filename("Invoice #12/ö..pdf"), "Invoice -12-.pdf")
        self.assertEqual(safe_filename("///"), "render")

    def test_file_response(self):
        result = render_html("<p>x</p>")
        response = file_response(result, "inv-1")
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn('attachment; filename="inv-1.pdf"', response["Content-Disposition"])
        self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF"))

    def test_view(self):
        response = self.client.get(f"/invoice/{self.invoice.pk}.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response["Content-Disposition"].startswith("inline"))


@mocked()
class AdminActionTests(Base):
    def setUp(self):
        super().setUp()
        self.a = Invoice.objects.create(number="INV-7", customer="Ada", total="10.00")
        self.b = Invoice.objects.create(number="INV-8", customer="Grace", total="20.00")
        self.admin = User.objects.create_superuser("admin", "a@example.test", "pw")

    def run_action(self, action, ids, user=None):
        self.client.force_login(user or self.admin)
        return self.client.post("/admin/testapp/invoice/", {"action": action, "_selected_action": ids}, follow=True)

    def test_pdf_action(self):
        response = self.run_action("thirds_render_pdf", [self.a.pk, self.b.pk])
        self.assertContains(response, "Rendered 2 files.")
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual(self.a.pdf.name, "invoices/invoice-INV-7.pdf")
        self.assertEqual(self.b.pdf.name, "invoices/invoice-INV-8.pdf")
        refs = sorted(b["body"]["reference"] for b in API.bodies)
        self.assertEqual(refs, [f"django testapp.invoice {self.a.pk}", f"django testapp.invoice {self.b.pk}"])
        self.assertTrue(all(b["body"]["pdf"] == {"format": "A4"} for b in API.bodies))

    def test_png_action_with_context(self):
        self.run_action("thirds_render_card", [self.a.pk])
        self.a.refresh_from_db()
        with self.a.card.open("rb") as f:
            self.assertEqual(png_size(f.read()), (1200, 630))
        self.assertIn("<h1>Invoice INV-7</h1>", self.last_body()["html"])

    def test_action_error_is_reported(self):
        with override_settings(THIRDS_API_KEY="wrong"):
            response = self.run_action("thirds_render_pdf", [self.a.pk])
        self.assertContains(response, "INV-7: thirds.ai answered 401 unauthorized")
        self.a.refresh_from_db()
        self.assertEqual(self.a.pdf.name, "")

    def test_one_failure_does_not_stop_the_rest(self):
        from thirds_render import admin as tr_admin
        real = tr_admin.render_template

        def flaky(name, ctx, **kw):
            if ctx["object"].number == "INV-7":
                raise ThirdsError("thirds.ai answered 422 render_failed: boom", 422, "render_failed")
            return real(name, ctx, **kw)

        with mock.patch.object(tr_admin, "render_template", flaky):
            response = self.run_action("thirds_render_pdf", [self.a.pk, self.b.pk])
        self.assertContains(response, "Rendered 1 file.")
        self.assertContains(response, "INV-7: thirds.ai answered 422 render_failed")
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual((self.a.pdf.name, self.b.pdf.name), ("", "invoices/invoice-INV-8.pdf"))

    def test_view_only_user_cannot_render(self):
        user = User.objects.create_user("viewer", password="pw", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename="view_invoice"))
        response = self.run_action("thirds_render_pdf", [self.a.pk], user=user)
        self.assertEqual(self.api_calls(), [])
        self.a.refresh_from_db()
        self.assertEqual(self.a.pdf.name, "")
        self.assertNotContains(response, "Rendered")

    def test_action_listed(self):
        self.client.force_login(self.admin)
        response = self.client.get("/admin/testapp/invoice/")
        self.assertContains(response, "Render PDF with thirds.ai")
        self.assertContains(response, "Render PNG with thirds.ai")


@mocked()
class CommandTests(Base):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def call(self, *args):
        out = io.StringIO()
        call_command("thirds_render", *args, stdout=out)
        return out.getvalue()

    def test_check_sends_nothing(self):
        out = self.call("--check")
        self.assertIn("API key: set", out)
        self.assertNotIn(MOCK_KEY, out)
        self.assertEqual(API.requests, [])

    def test_pdf(self):
        ctx = self.tmp / "ctx.json"
        ctx.write_text(json.dumps({"object": {"number": "INV-9", "customer": "Lin", "total": "5.00"}}))
        out = self.call("demo/invoice.html", str(self.tmp / "out" / "inv.pdf"), "--context", str(ctx), "--page", "A4")
        self.assertIn("Wrote", out)
        self.assertTrue((self.tmp / "out" / "inv.pdf").read_bytes().startswith(b"%PDF"))
        self.assertIn("Invoice INV-9", self.last_body()["html"])
        self.assertEqual(self.last_body()["pdf"], {"format": "A4"})

    def test_png(self):
        self.call("demo/card.html", str(self.tmp / "card.png"), "--width", "1200", "--height", "630", "--reference", "cli card")
        self.assertEqual(png_size((self.tmp / "card.png").read_bytes()), (1200, 630))
        self.assertEqual(self.last_body()["reference"], "cli card")
        self.assertIn("<h1>django-thirds-render</h1>", self.last_body()["html"])

    def test_saved_template(self):
        data = self.tmp / "data.json"
        data.write_text('{"title": "Hi"}')
        self.call("--saved-template", "tpl_" + "c" * 32, str(self.tmp / "t.png"), "--data", str(data), "--template-version", "2")
        body = self.last_body()
        self.assertEqual((body["template_id"], body["data"], body["version"]), ("tpl_" + "c" * 32, {"title": "Hi"}, 2))

    def test_bad_extension(self):
        with self.assertRaises(CommandError):
            self.call("demo/card.html", str(self.tmp / "card.gif"))
        self.assertEqual(API.requests, [])

    def test_missing_key(self):
        with override_settings(THIRDS_API_KEY=None), mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CommandError) as cm:
                self.call("demo/card.html", str(self.tmp / "card.png"))
        self.assertIn("Nothing was sent", str(cm.exception))
        self.assertEqual(API.requests, [])

    def test_api_error_becomes_command_error(self):
        with self.assertRaises(CommandError) as cm:
            self.call("--saved-template", "tpl_" + "0" * 32, str(self.tmp / "x.pdf"))
        self.assertIn("template_not_found", str(cm.exception))


@mocked()
class SchemaTests(Base):
    def test_every_mode_matches_public_schema(self):
        if not API.validate:
            self.skipTest("set THIRDS_OPENAPI_SPEC and install jsonschema to check bodies against the OpenAPI file")
        before = API.schema_checked
        client = ThirdsClient()
        client.pdf("<p>x</p>", pdf={"format": "A4", "margins": {"top": "10mm"}}, filename="a", reference="r")
        client.pdf("<p>{{ x }}</p>", data={"x": 1})
        client.pdf(template_id="tpl_" + "d" * 32, data={}, version=1)
        client.image("<p>x</p>", width=1200, height=630)
        client.image("<p>{{ x }}</p>", data={"x": 1}, format="jpeg", width=320, height=200)
        client.image(template_id="tpl_" + "d" * 32, data={"x": 1})
        self.assertEqual(API.schema_checked - before, 6)
        self.assertFalse([r for r in API.requests if r.get("schema")])

    def test_schema_rejects_bad_body(self):
        if not API.validate:
            self.skipTest("no validator")
        with self.assertRaises(ThirdsError) as cm:
            ThirdsClient().image("<p>x</p>", width=10, height=10)
        self.assertEqual(cm.exception.code, "invalid_request")
