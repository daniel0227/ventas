# Generated by Django 5.1.2 on 2025-06-20 01:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_alter_venta_fecha_venta_alter_venta_numero'),
    ]

    operations = [
        migrations.AddField(
            model_name='loteria',
            name='slug',
            field=models.SlugField(blank=True, help_text='Coincide con el slug de la API', null=True, unique=True),
        ),
    ]
