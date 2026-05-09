# Generated manually 2026-05-07

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_abonado_dias_semana"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LimiteVendedor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "limite_diario",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="Límite diario",
                        help_text="Tope de venta acumulada en el día (suma de montos × loterías). 0 = sin límite.",
                    ),
                ),
                ("activo", models.BooleanField(default=True, verbose_name="Activo")),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                (
                    "usuario",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="limite_vendedor",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuario",
                    ),
                ),
            ],
            options={
                "verbose_name": "Límite de vendedor",
                "verbose_name_plural": "Límites de vendedores",
            },
        ),
    ]
