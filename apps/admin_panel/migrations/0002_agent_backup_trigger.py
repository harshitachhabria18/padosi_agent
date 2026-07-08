from django.db import migrations


CREATE_TRIGGER_SQL = """
CREATE TRIGGER trg_agents_backup_before_delete
BEFORE DELETE ON agents
FOR EACH ROW
BEGIN
    INSERT INTO agent_backup (
        id,
        user_id,
        event_id,
        distributor_id,
        fullname,
        email,
        google_id,
        email_verified_at,
        mobile,
        registration_step,
        agent_pincode,
        latitude,
        longitude,
        plan_type,
        trial_ends_at,
        upgrade_discount_percent,
        referred_by_code,
        referral_reward_type,
        referral_reward_claimed,
        status,
        is_approved,
        approved_at,
        badge,
        admin_notes,
        registration_draft,
        user_types,
        insurance_companies,
        experience_range,
        client_base,
        achievement_photo_limit,
        profession,
        created_at,
        updated_at
    ) VALUES (
        OLD.id,
        OLD.user_id,
        OLD.event_id,
        OLD.distributor_id,
        OLD.fullname,
        OLD.email,
        OLD.google_id,
        OLD.email_verified_at,
        OLD.mobile,
        OLD.registration_step,
        OLD.agent_pincode,
        OLD.latitude,
        OLD.longitude,
        OLD.plan_type,
        OLD.trial_ends_at,
        OLD.upgrade_discount_percent,
        OLD.referred_by_code,
        OLD.referral_reward_type,
        OLD.referral_reward_claimed,
        OLD.status,
        OLD.is_approved,
        OLD.approved_at,
        OLD.badge,
        OLD.admin_notes,
        OLD.registration_draft,
        OLD.user_types,
        OLD.insurance_companies,
        OLD.experience_range,
        OLD.client_base,
        OLD.achievement_photo_limit,
        OLD.profession,
        OLD.created_at,
        OLD.updated_at
    );
END
"""

DROP_TRIGGER_SQL = "DROP TRIGGER IF EXISTS trg_agents_backup_before_delete;"


def create_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == 'mysql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(CREATE_TRIGGER_SQL)

def drop_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == 'mysql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(DROP_TRIGGER_SQL)


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_trigger, reverse_code=drop_trigger),
    ]
