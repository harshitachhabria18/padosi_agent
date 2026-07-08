from django.db import migrations, models

def run_schema_changes(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == 'mysql':
        # Modify role enum
        schema_editor.execute("ALTER TABLE users MODIFY COLUMN role ENUM('admin', 'agent', 'client', 'distributor', 'insurance') NOT NULL DEFAULT 'client';")
        # Add columns and constraints
        schema_editor.execute("ALTER TABLE agents ADD COLUMN insurance_id bigint unsigned DEFAULT NULL AFTER distributor_id, ADD CONSTRAINT fk_agents_insurance_id FOREIGN KEY (insurance_id) REFERENCES users(id) ON DELETE SET NULL;")
        schema_editor.execute("ALTER TABLE users ADD COLUMN insurance_parent_id bigint unsigned DEFAULT NULL AFTER email_verified_at, ADD COLUMN insurance_sub_role varchar(50) DEFAULT NULL AFTER insurance_parent_id, ADD CONSTRAINT fk_users_insurance_parent_id FOREIGN KEY (insurance_parent_id) REFERENCES users(id) ON DELETE SET NULL;")
    elif vendor == 'sqlite':
        # SQLite raw alter statements for test compatibility
        schema_editor.execute("ALTER TABLE agents ADD COLUMN insurance_id INTEGER DEFAULT NULL;")
        schema_editor.execute("ALTER TABLE users ADD COLUMN insurance_parent_id INTEGER DEFAULT NULL;")
        schema_editor.execute("ALTER TABLE users ADD COLUMN insurance_sub_role VARCHAR(50) DEFAULT NULL;")

def reverse_schema_changes(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == 'mysql':
        schema_editor.execute("ALTER TABLE users MODIFY COLUMN role ENUM('admin', 'agent', 'client', 'distributor') NOT NULL DEFAULT 'client';")
        schema_editor.execute("ALTER TABLE agents DROP FOREIGN KEY fk_agents_insurance_id, DROP COLUMN insurance_id;")
        schema_editor.execute("ALTER TABLE users DROP FOREIGN KEY fk_users_insurance_parent_id, DROP COLUMN insurance_parent_id, DROP COLUMN insurance_sub_role;")

class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0005_usersession_usersessiondata'),
    ]

    operations = [
        migrations.RunPython(run_schema_changes, reverse_schema_changes),
        
        migrations.CreateModel(
            name='QrFile',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('unique_code', models.CharField(max_length=255, unique=True)),
                ('filename', models.CharField(max_length=255)),
                ('original_name', models.CharField(max_length=255)),
                ('file_path', models.CharField(max_length=255)),
                ('file_type', models.CharField(max_length=50)),
                ('file_size', models.BigIntegerField()),
                ('download_count', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'qr_files',
            },
        ),
        migrations.CreateModel(
            name='AgentApprovalRequest',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('insurance_id', models.BigIntegerField()),
                ('agent_id', models.BigIntegerField()),
                ('action', models.CharField(max_length=50)),
                ('status', models.CharField(max_length=50, default='pending')),
                ('reason', models.TextField(null=True, blank=True)),
                ('admin_note', models.TextField(null=True, blank=True)),
                ('processed_by', models.BigIntegerField(null=True, blank=True)),
                ('processed_at', models.DateTimeField(null=True, blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'agent_approval_requests',
            },
        ),
    ]
