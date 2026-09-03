from django.test import SimpleTestCase

from apps.agents.views.bio_generator import _extract_bio, _read_message_text


class ExtractBioTests(SimpleTestCase):
    def test_standard_json(self):
        raw = (
            '{"bio": "I am a licensed insurance advisor with over 8 years of experience helping '
            'families in Ahmedabad secure health, life, and motor coverage with personalized guidance."}'
        )
        bio = _extract_bio(raw)
        self.assertTrue(bio.startswith("I am a licensed"))
        self.assertLessEqual(len(bio), 500)

    def test_capitalized_json_key(self):
        raw = (
            '{"Bio": "I help clients across Mumbai with health and life insurance, claim assistance, '
            'and tailored financial protection plans for families and professionals."}'
        )
        bio = _extract_bio(raw)
        self.assertIn("Mumbai", bio)
        self.assertNotIn("{", bio)

    def test_alternate_json_key(self):
        raw = (
            '{"professional_bio": "I provide portfolio and insurance guidance in Pune with a focus on '
            'health, life, and motor policies for local families and business owners."}'
        )
        bio = _extract_bio(raw)
        self.assertIn("Pune", bio)

    def test_plain_text(self):
        raw = (
            "I am a professional insurance advisor serving clients across Gujarat with tailored "
            "health and life insurance solutions and dedicated claim support."
        )
        bio = _extract_bio(raw)
        self.assertEqual(bio, raw)

    def test_empty_json_bio(self):
        self.assertEqual(_extract_bio('{"bio": ""}'), "")


class ReadMessageTextTests(SimpleTestCase):
    def test_reasoning_only_message(self):
        class Message:
            content = ""
            reasoning = (
                '{"bio": "I support families in Delhi with health and life insurance advice, '
                'clear policy comparisons, and reliable claim assistance every step of the way."}'
            )

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]

        raw = _read_message_text(Response())
        self.assertIn("Delhi", raw)
        bio = _extract_bio(raw)
        self.assertIn("Delhi", bio)
