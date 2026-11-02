"""An admin action that renders each selected object and saves the file on it.

    from thirds_render.admin import render_action

    @admin.register(Invoice)
    class InvoiceAdmin(admin.ModelAdmin):
        actions = [render_action("pdf_file", "invoices/invoice.html")]
"""

from django.contrib import messages
from django.utils.translation import gettext_lazy as _, ngettext

from .client import ThirdsError
from .shortcuts import render_template, save_to_field


def render_action(field_name, template_name, kind="pdf", *, context=None, filename=None, description=None,
                  **options):
    """Build an admin action.

    field_name     FileField or ImageField on the model that receives the file.
    template_name  Django template rendered with {"object": obj} or with context(obj).
    kind           "pdf", "png", "jpeg" or "webp".
    filename       Optional callable obj -> name without extension.
    options        Passed to the API, for example pdf={"format": "A4"} or width=1200, height=630.
    """

    def action(modeladmin, request, queryset):
        done, failed = 0, []
        for obj in queryset:
            ctx = context(obj) if context else {"object": obj}
            name = filename(obj) if filename else f"{obj._meta.model_name}-{obj.pk}"
            opts = {"reference": f"django {obj._meta.label_lower} {obj.pk}"[:200], **options}
            try:
                result = render_template(template_name, ctx, request=request, kind=kind, **opts)
            except ThirdsError as e:
                failed.append(f"{obj}: {e}")
                continue
            save_to_field(obj, field_name, result, filename=name)
            done += 1
        if done:
            modeladmin.message_user(request, ngettext("Rendered %d file.", "Rendered %d files.", done) % done,
                                    messages.SUCCESS)
        for line in failed:
            modeladmin.message_user(request, line, messages.ERROR)

    action.__name__ = f"thirds_render_{field_name}"
    action.short_description = description or _("Render %(kind)s with thirds.ai") % {"kind": kind.upper()}
    action.allowed_permissions = ("change",)
    return action
