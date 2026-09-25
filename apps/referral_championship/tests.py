from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone
from apps.agents.models import Agent, AgentSubscription
from apps.referral_championship.models import (
    ChampionshipCampaign,
    ChampionshipParticipant,
    ChampionshipReferral,
    ChampionshipRewardSlab,
    ChampionshipRewardClaim,
)
from apps.referral_championship.services.attribution_service import (
    get_or_create_participant,
    bind_referral_session,
    validate_referral_integrity,
)
from apps.referral_championship.services.qualification_service import (
    process_championship_qualification,
    revert_championship_qualification,
)
from apps.referral_championship.services.reward_engine import (
    evaluate_participant_rewards,
    get_participant_roadmap,
)
from apps.referral_championship.services.leaderboard_service import (
    refresh_leaderboard_cache,
    get_leaderboard_data,
)


class ReferralChampionshipTestCase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.campaign = ChampionshipCampaign.get_current()

        # Create Agent 1 (Referrer)
        self.user1 = User.objects.create_user(username='agent1@example.com', email='agent1@example.com', password='pass')
        self.agent1 = Agent.objects.create(
            user=self.user1,
            fullname='Parth Patel',
            email='agent1@example.com',
            mobile='9876543210',
            agent_pincode='380015',
            plan_type='professional',
            status='active'
        )

        # Create Agent 2 (Candidate)
        self.user2 = User.objects.create_user(username='agent2@example.com', email='agent2@example.com', password='pass')
        self.agent2 = Agent.objects.create(
            user=self.user2,
            fullname='Rahul Sharma',
            email='agent2@example.com',
            mobile='9123456780',
            agent_pincode='400001',
            plan_type='basic',
            status='active'
        )

    def test_participant_creation_and_code_format(self):
        participant = get_or_create_participant(self.agent1, self.campaign)
        self.assertIsNotNone(participant)
        self.assertTrue(participant.referral_id.startswith('PA-'))
        self.assertEqual(len(participant.referral_id), 9)

    def test_self_referral_detection(self):
        participant = get_or_create_participant(self.agent1, self.campaign)
        # Attempt self-referral
        is_valid, reason = validate_referral_integrity(participant, self.agent1)
        self.assertFalse(is_valid)
        self.assertIn("Self-referral", reason)

    def test_valid_attribution_and_qualification(self):
        referrer_p = get_or_create_participant(self.agent1, self.campaign)
        self.agent2.referred_by_code = referrer_p.referral_id
        self.agent2.save()

        sub = AgentSubscription.objects.create(
            agent=self.agent2,
            selected_plan="Starter's Plan",
            payment_status='completed',
            status='active',
            registration_amount=999.00
        )

        success = process_championship_qualification(self.agent2, sub)
        self.assertTrue(success)

        referrer_p.refresh_from_db()
        self.assertEqual(referrer_p.qualifying_referrals_count, 1)

    def test_revert_qualification_on_refund(self):
        referrer_p = get_or_create_participant(self.agent1, self.campaign)
        self.agent2.referred_by_code = referrer_p.referral_id
        self.agent2.save()

        sub = AgentSubscription.objects.create(
            agent=self.agent2,
            selected_plan="Starter's Plan",
            payment_status='completed',
            status='active',
            registration_amount=999.00
        )
        process_championship_qualification(self.agent2, sub)

        referrer_p.refresh_from_db()
        self.assertEqual(referrer_p.qualifying_referrals_count, 1)

        # Refund happens
        revert_championship_qualification(self.agent2, reason="refund")
        referrer_p.refresh_from_db()
        self.assertEqual(referrer_p.qualifying_referrals_count, 0)

    def test_reward_milestones(self):
        referrer_p = get_or_create_participant(self.agent1, self.campaign)
        referrer_p.qualifying_referrals_count = 5
        referrer_p.save()

        unlocked = evaluate_participant_rewards(referrer_p)
        self.assertTrue(len(unlocked) >= 1)

        roadmap = get_participant_roadmap(referrer_p)
        first_slab = roadmap['roadmap'][0]
        self.assertEqual(first_slab['threshold'], 5)
        self.assertTrue(first_slab['is_reached'])
