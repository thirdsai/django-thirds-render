from django.contrib import admin

from thirds_render.admin import render_action

from .models import Invoice


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    actions = [
        render_action("pdf", "demo/invoice.html", pdf={"format": "A4"}, filename=lambda o: f"invoice-{o.number}"),
        render_action("card", "demo/card.html", "png", width=1200, height=630,
                      context=lambda o: {"title": f"Invoice {o.number}", "subtitle": o.customer}),
    ]
