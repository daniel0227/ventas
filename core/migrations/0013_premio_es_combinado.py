from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_venta_es_combinado'),
    ]

    operations = [
        migrations.AddField(
            model_name='premio',
            name='es_combinado',
            field=models.BooleanField(default=False),
        ),
    ]
