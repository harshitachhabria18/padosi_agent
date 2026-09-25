import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session

from fastapi_app.models.agent import Agent
from fastapi_app.models.subscription_plan import SubscriptionPlan
from fastapi_app.models.agent_subscription import AgentSubscription
from fastapi_app.models.site_setting import SiteSetting
from fastapi_app.models.referral_code import ReferralCode
from fastapi_app.schemas.plans import (
    PlanFeatureItem,
    PlanPricingDetails,
    PlanItemSchema,
    AgentCurrentPlanInfo,
    UpgradeDiscountInfo,
    PlansListResponse,
)

logger = logging.getLogger(__name__)

# Canonical feature mapping for plans
PLAN_FEATURE_DEFINITIONS = [
    ("show_profile_section", "Public Profile Customization"),
    ("is_listed_in_directory", "Listed in Find Agents Directory"),
    ("show_performance_stats", "Performance Overview & Analytics"),
    ("show_sales_insights", "Sales Insights & Recommendations"),
    ("show_new_business_leads", "New Business Lead Enquiries"),
    ("show_recent_leads", "Lead Management & Follow-ups"),
    ("show_agent_certificate", "Verified IRDAI / AMFI Badge"),
    ("show_career_timeline", "Career Timeline & Milestones"),
    ("show_professional_bio", "Professional Bio & AI Bio Generator"),
    ("show_portfolio", "Insurance Products Portfolio"),
    ("show_claim_support", "Claims Support Showcase"),
    ("show_companies", "Partner Insurance Companies Display"),
    ("show_achievement", "Gallery & Achievement Photos"),
    ("show_review_management", "Customer Reviews & Ratings"),
    ("show_rank_boost_tips", "Profile Rank Boost Tips"),
    ("premium_priority_support", "Priority Support & Assistance"),
]

SLUG_NORMALISE = {
    'basic': 'starter',
    'starter': 'starter',
    'standard': 'starter',
    'starters_plan': 'starter',
    'starters-plan': 'starter',
    'free trial': 'free_trial',
    'free_trial': 'free_trial',
    'professional': 'professional',
    'professionals_plan': 'professional',
    'professionals-plan': 'professional',
    'pro': 'professional',
    'exclusive': 'exclusive',
    'exclusive_partner': 'exclusive',
    'exclusive_partner_plan': 'exclusive',
    'elite': 'starter',
}


def normalize_plan_slug(plan_type: Optional[str]) -> str:
    if not plan_type:
        return ""
    pt = str(plan_type).strip().lower().replace(" ", "_")
    return SLUG_NORMALISE.get(pt, pt)


class PlanService:
    def __init__(self, db: Session):
        self.db = db

    def get_plans_list(self, agent: Optional[Agent] = None) -> PlansListResponse:
        """
        Fetch all active subscription plans with full GST breakdown,
        feature entitlements, current agent subscription status,
        and applicable special upgrade discount.
        """
        # 1. Fetch active plans from database
        db_plans = self.db.query(SubscriptionPlan).filter(
            SubscriptionPlan.is_active == True
        ).order_by(SubscriptionPlan.sort_order, SubscriptionPlan.actual_price).all()

        # Fallback default plans if database table is not yet seeded
        if not db_plans:
            plans_to_display = self._get_fallback_plans()
        else:
            plans_to_display = db_plans

        # 2. Compute Agent Subscription Info & Discount
        agent_current_plan = None
        upgrade_discount = None
        applicable_discount_pct = 0
        agent_current_slug = ""
        is_pro_1rs = False

        if agent:
            agent_current_slug = normalize_plan_slug(agent.plan_type)
            agent_current_plan = self._resolve_current_agent_plan(agent)
            upgrade_discount, applicable_discount_pct, is_pro_1rs = self._resolve_upgrade_discount(agent)

        # 3. Construct Plan Items with Pricing & Feature List
        plan_items: List[PlanItemSchema] = []
        for plan in plans_to_display:
            plan_slug = normalize_plan_slug(getattr(plan, 'slug', '') or getattr(plan, 'name', ''))
            is_current = bool(agent and agent_current_slug and plan_slug == agent_current_slug)

            # Pricing Calculations with 18% GST
            actual_price = float(getattr(plan, 'actual_price', 0.0) or 0.0)
            base_discounted = float(getattr(plan, 'discounted_price', 0.0) or actual_price)

            # Check if special agent upgrade discount applies
            plan_discount_pct = 0
            if agent and not is_current and applicable_discount_pct > 0:
                if is_pro_1rs and plan_slug == "professional":
                    final_incl_gst = 1.0
                    plan_discount_pct = 99
                else:
                    final_incl_gst = round(base_discounted * (100 - applicable_discount_pct) / 100)
                    plan_discount_pct = applicable_discount_pct
            else:
                final_incl_gst = base_discounted

            # GST 18% decomposition (inclusive pricing standard)
            base_excl_gst = round(final_incl_gst / 1.18, 2)
            gst_amount = round(final_incl_gst - base_excl_gst, 2)
            formatted_price = f"₹{int(final_incl_gst):,}"

            pricing_details = PlanPricingDetails(
                actual_price=actual_price,
                discounted_price=base_discounted,
                agent_discount_pct=plan_discount_pct,
                base_price_exclusive_gst=base_excl_gst,
                gst_rate_percent=18.0,
                gst_amount=gst_amount,
                final_price_inclusive_gst=final_incl_gst,
                formatted_final_price=formatted_price,
            )

            # Feature items list
            features = self._extract_plan_features(plan)

            plan_items.append(
                PlanItemSchema(
                    id=getattr(plan, 'id', 0),
                    name=getattr(plan, 'name', 'Plan'),
                    slug=plan_slug,
                    description=getattr(plan, 'description', '') or "",
                    color_theme=getattr(plan, 'color_theme', 'starter-theme') or "starter-theme",
                    badge_text=getattr(plan, 'badge_text', None),
                    sort_order=getattr(plan, 'sort_order', 0) or 0,
                    is_current_plan=is_current,
                    pricing=pricing_details,
                    features=features,
                )
            )

        return PlansListResponse(
            success=True,
            agent_current_plan=agent_current_plan,
            upgrade_discount=upgrade_discount,
            plans=plan_items,
        )

    def _resolve_current_agent_plan(self, agent: Agent) -> AgentCurrentPlanInfo:
        """Resolve agent's current active plan status, trial state, and expiry."""
        sub = self.db.query(AgentSubscription).filter(
            AgentSubscription.agent_id == agent.id,
            AgentSubscription.status == "active"
        ).order_by(AgentSubscription.created_at.desc()).first()

        plan_name = getattr(sub, 'selected_plan', None) or agent.plan_type or "Free Trial"
        status = getattr(sub, 'status', None) or agent.status or "active"
        expires_at = getattr(sub, 'expires_at', None)

        now = datetime.utcnow()
        is_on_trial = bool(
            agent.plan_type == "free_trial"
            and agent.trial_ends_at is not None
            and agent.trial_ends_at > now
        )

        trial_days_left = None
        if is_on_trial and agent.trial_ends_at:
            trial_days_left = max(0, (agent.trial_ends_at - now).days)

        return AgentCurrentPlanInfo(
            plan_type=agent.plan_type,
            plan_name=plan_name.title() if plan_name else "Free Trial",
            status=status,
            is_active=bool(status in ["active", "approved"]),
            is_on_trial=is_on_trial,
            trial_days_left=trial_days_left,
            trial_ends_at=agent.trial_ends_at,
            expires_at=expires_at,
        )

    def _resolve_upgrade_discount(self, agent: Agent) -> tuple[UpgradeDiscountInfo, int, bool]:
        """Compute special upgrade discount available for the agent."""
        # 1. Admin default trial upgrade discount
        admin_setting = self.db.query(SiteSetting).filter(SiteSetting.key == "trial_upgrade_discount").first()
        admin_default = 20
        if admin_setting and admin_setting.value:
            try:
                admin_default = int(admin_setting.value)
            except Exception:
                pass

        # 2. Agent-specific discount
        agent_specific = int(agent.upgrade_discount_percent or 0)

        # 3. Referral tier discount
        referral_discount = 0
        ref_code = self.db.query(ReferralCode).filter(ReferralCode.agent_id == agent.id).first()
        if ref_code:
            try:
                tier = ref_code.current_tier()
                if tier and isinstance(tier, dict):
                    referral_discount = int(tier.get("discount", 0) or 0)
            except Exception:
                pass

        # Maximum available discount
        applicable_discount = max(admin_default, agent_specific, referral_discount)

        is_pro_1rs = getattr(agent, "referral_reward_type", None) == "pro_plan_1rs"
        offer_msg = None
        if is_pro_1rs:
            offer_msg = "Special Reward: Professional's Plan unlocked for ₹1 only!"
        elif applicable_discount > 0:
            offer_msg = f"Special {applicable_discount}% discount applied on plan upgrades!"

        discount_info = UpgradeDiscountInfo(
            applicable_discount_pct=99 if is_pro_1rs else applicable_discount,
            trial_discount_pct=admin_default,
            agent_specific_discount_pct=agent_specific,
            referral_discount_pct=referral_discount,
            referral_reward_type=agent.referral_reward_type,
            offer_message=offer_msg,
        )

        return discount_info, applicable_discount, is_pro_1rs

    def _extract_plan_features(self, plan: Any) -> List[PlanFeatureItem]:
        """Extract all feature toggles with human-readable labels."""
        features = []
        for attr, label in PLAN_FEATURE_DEFINITIONS:
            is_enabled = bool(getattr(plan, attr, True))
            features.append(
                PlanFeatureItem(
                    key=attr,
                    label=label,
                    is_enabled=is_enabled,
                )
            )
        return features

    def _get_fallback_plans(self) -> List[Any]:
        """In-memory fallback plans if database table has not been populated."""
        class MockPlan:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        return [
            MockPlan(
                id=1,
                name="Starter's Plan",
                slug="starter",
                description="Essential digital presence and local verification for insurance advisors.",
                color_theme="starter-theme",
                badge_text="Most Popular",
                sort_order=1,
                actual_price=2359.00,
                discounted_price=999.00,
                show_profile_section=True,
                is_listed_in_directory=True,
                show_performance_stats=True,
                show_sales_insights=True,
                show_new_business_leads=True,
                show_recent_leads=True,
                show_agent_certificate=True,
                show_career_timeline=True,
                show_professional_bio=True,
                show_portfolio=True,
                show_claim_support=True,
                show_companies=True,
                show_achievement=True,
                show_review_management=True,
                show_rank_boost_tips=True,
                premium_priority_support=False,
            ),
            MockPlan(
                id=2,
                name="Professional's Plan",
                slug="professional",
                description="Advanced visibility, top rank priority, SEO, and full client lead management.",
                color_theme="pro-theme",
                badge_text="Recommended",
                sort_order=2,
                actual_price=8258.00,
                discounted_price=4999.00,
                show_profile_section=True,
                is_listed_in_directory=True,
                show_performance_stats=True,
                show_sales_insights=True,
                show_new_business_leads=True,
                show_recent_leads=True,
                show_agent_certificate=True,
                show_career_timeline=True,
                show_professional_bio=True,
                show_portfolio=True,
                show_claim_support=True,
                show_companies=True,
                show_achievement=True,
                show_review_management=True,
                show_rank_boost_tips=True,
                premium_priority_support=True,
            ),
            MockPlan(
                id=3,
                name="Exclusive Partner Plan",
                slug="exclusive",
                description="Maximum city-wide visibility, exclusive client leads, and direct priority manager.",
                color_theme="exclusive-theme",
                badge_text="VIP Partner",
                sort_order=3,
                actual_price=14999.00,
                discounted_price=9999.00,
                show_profile_section=True,
                is_listed_in_directory=True,
                show_performance_stats=True,
                show_sales_insights=True,
                show_new_business_leads=True,
                show_recent_leads=True,
                show_agent_certificate=True,
                show_career_timeline=True,
                show_professional_bio=True,
                show_portfolio=True,
                show_claim_support=True,
                show_companies=True,
                show_achievement=True,
                show_review_management=True,
                show_rank_boost_tips=True,
                premium_priority_support=True,
            ),
        ]
