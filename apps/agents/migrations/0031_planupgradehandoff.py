from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0030_alter_agentcardimpression_agent'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlanUpgradeHandoff',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token_hash', models.CharField(max_length=64, unique=True)),
                ('plan_slug', models.CharField(max_length=32)),
                ('expires_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='plan_upgrade_handoffs', to='agents.agent')),
            ],
            options={
                'db_table': 'plan_upgrade_handoffs',
            },
        ),
    ]
