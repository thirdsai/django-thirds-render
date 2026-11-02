(Disclosure: I'm connected to thirds.ai.)
Drafted with AI help.

# django-thirds-render

A small Django app that renders HTML, Django templates or saved [thirds.ai](https://thirds.ai/?utm_source=github&utm_medium=listing&utm_campaign=own-content&utm_content=django-render) templates to PDF or PNG through the thirds.ai API. It gives you:

* a Python client with no dependencies beyond Django (standard library HTTP),
* `render_template`, `render_html` and `render_saved_template` helpers,
* `file_response` for views and `save_to_field` for a `FileField`,
* an admin action factory that renders selected objects into a `FileField`,
* a `thirds_render` management command.

Tested with Django 5.2 (LTS) on Python 3.10 to 3.13 and Django 6.1 on Python 3.12 and 3.13. See "What was tested" below.

## Install

Requires Python 3.10 or newer and Django 5.2 or 6.1 (Django 6.1 itself needs Python 3.12 or newer). The package is not on PyPI; install it from the v0.1.0 tag of the repository:

```
pip install "git+https://github.com/thirdsai/django-thirds-render@v0.1.0"
```

Add the app:

```python
INSTALLED_APPS = [
    # ...
    "thirds_render",
]
```

## Settings

```python
import os

THIRDS_API_KEY = os.environ.get("THIRDS_API_KEY")  # read it from the environment

THIRDS_RENDER = {             # all optional
    "BASE_URL": "https://thirds.ai",
    "TIMEOUT": 60,            # seconds per HTTP request
    "DEADLINE": 120,          # seconds to wait for one render
    "POLL_INTERVAL": 1.0,     # seconds between status checks
}
```

If `THIRDS_API_KEY` is missing from settings, the app reads the `THIRDS_API_KEY` environment variable. Keep the key out of settings files and version control. With no key, nothing is sent and the helpers raise `ThirdsError` with code `missing_key`.

## Use it in a view

```python
from thirds_render import file_response, render_template

def invoice_pdf(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    result = render_template("invoices/invoice.html", {"object": invoice}, request=request,
                             pdf={"format": "A4"}, reference=f"invoice {invoice.pk}")
    return file_response(result, f"invoice-{invoice.number}", as_attachment=False)
```

For an image, pass the kind and size:

```python
result = render_template("cards/og.html", {"title": "Hello"}, kind="png", width=1200, height=630)
```

`kind` is one of `pdf`, `png`, `jpeg` or `webp`. Extra keyword arguments go into the request body as documented in the thirds.ai API, for example `pdf={...}`, `filename`, `reference`, `wait` or `javascript`.

### Static files

The renderer runs on thirds.ai, so it cannot load `/static/...` from your server. By default the helpers inline local static files: `<link rel="stylesheet" href="{% static ... %}">` becomes a `<style>` block, and `<img src>` and `<script src>` pointing at `STATIC_URL` become data URIs, found through the staticfiles finders. Absolute `https://` URLs are left as they are. Turn this off with `inline_static=False`.

### Raw HTML, with or without data

```python
from thirds_render import render_html

render_html("<h1>Hello</h1>")                                    # raw HTML
render_html("<h1>Hello {{ name }}</h1>", data={"name": "Zoë"})   # thirds.ai fills and escapes the data
```

With `data`, the template syntax is filled in by thirds.ai, not by Django.

### Saved templates

```python
from thirds_render import render_saved_template

render_saved_template("tpl_...", {"title": "Hello"}, kind="png", version=3)
```

## Save to a model field

```python
from thirds_render import render_template, save_to_field

result = render_template("invoices/invoice.html", {"object": invoice})
save_to_field(invoice, "pdf", result, filename=f"invoice-{invoice.number}")
```

The stored name goes through the field's `upload_to` and storage, so the usual storage rules apply (for example spaces become underscores on the default storage).

## Admin action

```python
from django.contrib import admin
from thirds_render.admin import render_action

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    actions = [
        render_action("pdf", "invoices/invoice.html", pdf={"format": "A4"},
                      filename=lambda o: f"invoice-{o.number}"),
        render_action("card", "cards/invoice.html", "png", width=1200, height=630,
                      context=lambda o: {"title": f"Invoice {o.number}"}),
    ]
```

Each selected object is rendered with `{"object": obj}` (or your `context` callable) and saved into the named `FileField`. The action needs the change permission. Errors are shown per object in the admin messages and do not stop the other objects. Each request carries a reference such as `django invoices.invoice 12`, so you can find it in your thirds.ai history.

The action renders one object at a time inside the request. For large selections, use a task queue (not included).

## Management command

```
python manage.py thirds_render --check
python manage.py thirds_render invoices/invoice.html out/invoice.pdf --context ctx.json --page A4
python manage.py thirds_render cards/og.html out/card.png --context ctx.json --width 1200 --height 630
python manage.py thirds_render --saved-template tpl_... out/card.png --data data.json --template-version 2
```

The output extension (`.pdf`, `.png`, `.jpg`, `.webp`) sets the kind. `--check` reports whether a key is set and sends nothing.

## Client

```python
from thirds_render import ThirdsClient, ThirdsError

client = ThirdsClient()  # or ThirdsClient(api_key=..., base_url=..., deadline=...)
try:
    result = client.pdf("<h1>Hi</h1>", pdf={"format": "Letter"}, idempotency_key="order-42")
except ThirdsError as e:
    print(e.status, e.code, e.job_id)
```

`result.content` holds the bytes, `result.media_type` the type and `result.job_id` the job id. The client sends an `Idempotency-Key` on every request (your own, or a random one), polls the job until it finishes or the deadline passes, then downloads the file from the signed link without the API key. The signed link is not kept on the result.

## What is sent to thirds.ai

This app calls an external service. When you render, it sends the HTML (with inlined static files) or the saved template id, the data you pass, and the render options to `https://thirds.ai` with your API key. Nothing is sent at import time, on startup, by `--check`, or when no key is set. See the [terms](https://thirds.ai/terms) and the [privacy policy](https://thirds.ai/privacy).

## When a local renderer fits better

If documents must never leave your servers, if you need to render offline, or if the HTML depends on resources only reachable inside your network, a renderer you run yourself is the better choice.

## What was tested

Version 0.1.0, 2 November 2026:

* Mocked suite, 43 tests, passing on Django 5.2.18 with Python 3.10, 3.11, 3.12 and 3.13, and on Django 6.1.2 with Python 3.12 and 3.13. Request bodies are checked against the public thirds.ai OpenAPI schema. The mocked suite was run locally on Python 3.10 to 3.13 with Django 5.2 and 6.1.
* Live suite against thirds.ai on Django 6.1.2 and Python 3.13: an admin action PDF saved into a `FileField`, a 1200x630 PNG card with its title and subtitle from the management command, a PDF from HTML with data, plus an unknown saved template and a wrong key (both refused, as expected). The two refusal checks also passed on Django 5.2.18.

Not tested yet: remote storages such as S3, async views, task queues.

## Run the tests

```
pip install -e ".[test]"
python runtests.py                       # mocked, no network, no key needed
THIRDS_LIVE=1 python runtests.py tests.test_live   # live, uses THIRDS_API_KEY, up to 3 renders
```

## License

MIT. Copyright (c) 2026 thirds.ai.
