# Generated by Django 5.1.2 on 2024-11-11 20:19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_remove_venta_loteria_venta_loterias_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='venta',
            name='fecha_venta',
            field=models.DateTimeField(auto_now_add=True),
        ),
    ]
