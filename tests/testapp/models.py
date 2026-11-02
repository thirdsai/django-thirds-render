from django.db import models


class Invoice(models.Model):
    number = models.CharField(max_length=20)
    customer = models.CharField(max_length=100)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    pdf = models.FileField(upload_to="invoices/", blank=True)
    card = models.FileField(upload_to="cards/", blank=True)

    def __str__(self):
        return self.number
