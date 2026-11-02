from django.shortcuts import get_object_or_404

from thirds_render import file_response, render_template

from .models import Invoice


def invoice_pdf(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    result = render_template("demo/invoice.html", {"object": invoice}, request=request, pdf={"format": "A4"})
    return file_response(result, f"invoice-{invoice.number}.pdf", as_attachment=False)
