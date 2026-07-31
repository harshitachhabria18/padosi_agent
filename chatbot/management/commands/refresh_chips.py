from django.core.management.base import BaseCommand
from django.core.cache import cache
from chatbot.llm_client import generate_suggestion_chips

class Command(BaseCommand):
    help = 'Fetches new suggestion chips from Groq API and caches them'

    def handle(self, *args, **options):
        self.stdout.write('Generating new suggestion chips...')
        chips = generate_suggestion_chips()
        if chips:
            cache.set("suggestion_chips", chips, timeout=46800) # 13 hours
            self.stdout.write(self.style.SUCCESS(f'Successfully generated and cached chips: {chips}'))
        else:
            self.stdout.write(self.style.ERROR('Failed to generate suggestion chips'))
