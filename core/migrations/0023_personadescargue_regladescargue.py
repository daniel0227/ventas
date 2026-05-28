import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_alter_ventaauditlog_event_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='PersonaDescargue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100, unique=True)),
                ('telefono', models.CharField(blank=True, max_length=30)),
                ('orden', models.PositiveSmallIntegerField(
                    help_text='Orden de cascada. 1 = primera en absorber.',
                    unique=True,
                )),
                ('recibe_restante', models.BooleanField(
                    default=False,
                    help_text='Si esta activo, absorbe TODO el saldo que sobre tras la cascada (independiente de sus reglas).',
                )),
                ('activo', models.BooleanField(db_index=True, default=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Persona de descargue',
                'verbose_name_plural': 'Personas de descargue',
                'ordering': ('orden',),
            },
        ),
        migrations.CreateModel(
            name='ReglaDescargue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cifras', models.PositiveSmallIntegerField(
                    help_text='Cantidad de cifras del numero (ej. 3 o 4).',
                )),
                ('monto_maximo', models.PositiveIntegerField(
                    help_text='Maximo que absorbe por cada numero de esa cantidad de cifras.',
                )),
                ('persona', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='reglas',
                    to='core.personadescargue',
                )),
            ],
            options={
                'verbose_name': 'Regla de descargue',
                'verbose_name_plural': 'Reglas de descargue',
                'ordering': ('cifras',),
                'constraints': [
                    models.UniqueConstraint(
                        fields=('persona', 'cifras'),
                        name='uniq_regla_por_persona_cifras',
                    ),
                ],
            },
        ),
    ]
