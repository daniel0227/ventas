from django.db import migrations, models


def migrar_combi_a_booleano(apps, schema_editor):
    """
    Convierte el campo combi (IntegerField) a es_combinado (BooleanField).
    Si combi tenía algún valor distinto de None/0, se considera combinado=True.
    """
    Venta = apps.get_model('core', 'Venta')
    Venta.objects.filter(combi__isnull=False).update(es_combinado=True)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_premio_venta_descargue'),
    ]

    operations = [
        # 1. Agregar el nuevo campo booleano con default False
        migrations.AddField(
            model_name='venta',
            name='es_combinado',
            field=models.BooleanField(default=False),
        ),
        # 2. Migrar datos: combi no nulo → es_combinado = True
        migrations.RunPython(
            migrar_combi_a_booleano,
            reverse_code=migrations.RunPython.noop,
        ),
        # 3. Eliminar el campo antiguo
        migrations.RemoveField(
            model_name='venta',
            name='combi',
        ),
    ]
