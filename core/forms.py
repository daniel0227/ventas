# core/forms.py

from django import forms
from django.forms import modelformset_factory
from django.forms import formset_factory
from .models import Venta, Loteria

# Formulario principal para registrar una venta
class VentaForm(forms.ModelForm):
    class Meta:
        model = Venta
        fields = ['loterias', 'monto']  # Loterías y monto son los campos relevantes

# Formulario para ingresar los números
class VentaForm(forms.ModelForm):
    class Meta:
        model = Venta
        fields = ['loterias', 'numero', 'monto']
        widgets = {
            'loterias': forms.CheckboxSelectMultiple(),
        }