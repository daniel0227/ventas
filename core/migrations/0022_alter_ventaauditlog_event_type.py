from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_create_abonos_group'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ventaauditlog',
            name='event_type',
            field=models.CharField(
                choices=[
                    ('sale.create_attempt', 'Sale Create Attempt'),
                    ('sale.create_success', 'Sale Create Success'),
                    ('sale.create_rejected', 'Sale Create Rejected'),
                    ('sale.create_rejected_closed_lottery', 'Sale Create Rejected Closed Lottery'),
                    ('sale.update_allowed', 'Sale Update Allowed'),
                    ('sale.update_blocked', 'Sale Update Blocked'),
                    ('sale.delete_blocked', 'Sale Delete Blocked'),
                    ('sale.lotteries_change_allowed', 'Sale Lotteries Change Allowed'),
                    ('sale.lotteries_change_blocked', 'Sale Lotteries Change Blocked'),
                    ('sale.user_limit_exceeded', 'Sale User Daily Limit Exceeded'),
                ],
                db_index=True,
                max_length=64,
            ),
        ),
    ]
