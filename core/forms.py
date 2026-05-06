# core/forms.py

from django import forms
from django.forms import inlineformset_factory
from .models import Venta, Loteria, Abonado, JugadaAbonado


# Formulario principal para registrar una venta
class VentaForm(forms.ModelForm):
    class Meta:
        model = Venta
        fields = ['loterias', 'numero', 'monto']
        widgets = {
            'loterias': forms.CheckboxSelectMultiple(),
        }


class AbonadoForm(forms.ModelForm):
    class Meta:
        model = Abonado
        fields = ["nombre", "telefono"]
        widgets = {
            "nombre": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej: Daniel tienda",
                "maxlength": 100,
                "autocomplete": "off",
            }),
            "telefono": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Opcional",
                "maxlength": 30,
                "inputmode": "tel",
            }),
        }

    def __init__(self, *args, vendedor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.vendedor = vendedor

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip()
        if not nombre:
            raise forms.ValidationError("El nombre es obligatorio.")
        if self.vendedor is not None:
            qs = Abonado.objects.filter(vendedor=self.vendedor, nombre__iexact=nombre)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("Ya tienes un abonado con ese nombre.")
        return nombre


class JugadaAbonadoForm(forms.ModelForm):
    class Meta:
        model = JugadaAbonado
        fields = ["numero", "monto", "es_combinado", "orden"]
        widgets = {
            "numero": forms.TextInput(attrs={
                "class": "form-control ventas-input",
                "inputmode": "numeric",
                "pattern": "[0-9]{1,4}",
                "maxlength": 4,
            }),
            "monto": forms.NumberInput(attrs={
                "class": "form-control ventas-input",
                "inputmode": "decimal",
                "min": 0,
                "step": "any",
            }),
            "orden": forms.HiddenInput(),
        }

    def clean_numero(self):
        numero = (self.cleaned_data.get("numero") or "").strip()
        if numero and not numero.isdigit():
            raise forms.ValidationError("El numero debe ser numerico.")
        if numero and not (1 <= len(numero) <= 4):
            raise forms.ValidationError("El numero debe tener entre 1 y 4 cifras.")
        return numero


JugadaAbonadoFormSet = inlineformset_factory(
    Abonado,
    JugadaAbonado,
    form=JugadaAbonadoForm,
    extra=0,
    can_delete=True,
    min_num=0,
    validate_min=False,
)