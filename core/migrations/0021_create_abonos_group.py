from django.db import migrations


def crear_grupo_abonos(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="abonos")


def eliminar_grupo_abonos(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="abonos").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_add_limitevendedor"),
    ]

    operations = [
        migrations.RunPython(crear_grupo_abonos, eliminar_grupo_abonos),
    ]
