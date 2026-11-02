from django.contrib import admin
from django.urls import path

from tests.testapp import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("invoice/<int:pk>.pdf", views.invoice_pdf),
]
