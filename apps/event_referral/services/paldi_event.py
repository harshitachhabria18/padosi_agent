from datetime import date

from apps.agents.models import Event
from apps.event_referral.constants import PALDI_EVENT_NAME


def get_or_create_paldi_event():
    """Ensure the admin `events` row used for event_id filters exists."""
    event, _ = Event.objects.get_or_create(
        name=PALDI_EVENT_NAME,
        defaults={
            'description': 'Paldi referral challenge — agents register without payment and refer paying agents.',
            'event_date': date.today(),
        },
    )
    return event


def assign_paldi_event_to_agent(agent):
    if not agent:
        return
    event = get_or_create_paldi_event()
    if agent.event_id != event.id:
        agent.event_id = event.id
        agent.save(update_fields=['event_id', 'updated_at'])
