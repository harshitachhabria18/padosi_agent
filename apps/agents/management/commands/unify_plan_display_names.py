"""Rewrite legacy paid plan labels to Starter's Plan / Professional's Plan."""
from django.core.management.base import BaseCommand

from apps.agents.models import AgentSubscription, Invoice
from apps.agents.services.feature_unlock import PLAN_LABELS, paid_plan_label
from apps.home.models import SiteSetting


class Command(BaseCommand):
    help = 'Normalize starter/professional display names in settings and subscriptions'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry = options['dry_run']
        n = 0

        pricing = SiteSetting.get_value('pricing_config')
        if isinstance(pricing, dict):
            changed = False
            for key, label in (('starter', PLAN_LABELS['starter']), ('professional', PLAN_LABELS['professional'])):
                block = pricing.get(key)
                if isinstance(block, dict) and block.get('name') != label:
                    block['name'] = label
                    changed = True
            if changed and not dry:
                SiteSetting.set_value('pricing_config', pricing, 'pricing')
            n += int(changed)

        try:
            from apps.referral_championship.models import ChampionshipCampaign
            for camp in ChampionshipCampaign.objects.all():
                cfg = camp.pricing_config or {}
                touched = False
                for json_key, label in (('digital', PLAN_LABELS['starter']), ('professional', PLAN_LABELS['professional'])):
                    row = cfg.get(json_key)
                    if isinstance(row, dict) and row.get('name') != label:
                        row['name'] = label
                        touched = True
                if touched:
                    n += 1
                    if not dry:
                        camp.pricing_config = cfg
                        camp.save(update_fields=['pricing_config'])
        except Exception:
            pass

        for model, field in ((AgentSubscription, 'selected_plan'), (Invoice, 'plan_name')):
            for row in model.objects.exclude(**{f'{field}__isnull': True}).exclude(**{field: ''}):
                old = getattr(row, field)
                new = paid_plan_label(old)
                if new != old and new in (PLAN_LABELS['starter'], PLAN_LABELS['professional']):
                    n += 1
                    if not dry:
                        setattr(row, field, new)
                        row.save(update_fields=[field])

        self.stdout.write(self.style.SUCCESS(f"{'Dry run: ' if dry else ''}{n} update(s)."))
