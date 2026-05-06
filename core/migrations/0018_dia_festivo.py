from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0017_add_resultado_audit_log'),
    ]

    operations = [
        migrations.CreateModel(
            name='DiaFestivo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField(unique=True, verbose_name='Fecha')),
                ('descripcion', models.CharField(blank=True, max_length=200, verbose_name='Descripción')),
            ],
            options={
                'verbose_name': 'Día Festivo',
                'verbose_name_plural': 'Días Festivos',
                'ordering': ['fecha'],
            },
        ),
    ]
