from django.core.management.base import BaseCommand

from apps.event_referral.models import EventReferralParticipant
from apps.event_referral.services.participant_service import evaluate_participant


class Command(BaseCommand):
    help = 'Block event referral participants whose deadline passed without enough paid referrals.'

    def handle(self, *args, **options):
        qs = EventReferralParticipant.objects.filter(status=EventReferralParticipant.STATUS_ACTIVE)
        blocked = 0
        won = 0
        for participant in qs.iterator():
            before = participant.status
            evaluate_participant(participant, block_on_expire=True)
            participant.refresh_from_db()
            if participant.status == EventReferralParticipant.STATUS_BLOCKED and before != participant.status:
                blocked += 1
            elif participant.status == EventReferralParticipant.STATUS_WON and before != participant.status:
                won += 1
        self.stdout.write(self.style.SUCCESS(f'Done. Won: {won}, blocked: {blocked}.'))
