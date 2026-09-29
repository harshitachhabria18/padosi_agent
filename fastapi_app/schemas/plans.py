from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class PlanFeatureItem(BaseModel):
    key: str
    label: str
    is_enabled: bool


class PlanPricingDetails(BaseModel):
    actual_price: float
    discounted_price: float
    agent_discount_pct: int
    base_price_exclusive_gst: float
    gst_rate_percent: float = 18.0
    gst_amount: float
    final_price_inclusive_gst: float
    formatted_final_price: str


class PlanItemSchema(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str] = ""
    color_theme: str = "starter-theme"
    badge_text: Optional[str] = None
    sort_order: int = 0
    is_current_plan: bool = False
    pricing: PlanPricingDetails
    features: List[PlanFeatureItem] = []


class AgentCurrentPlanInfo(BaseModel):
    plan_type: Optional[str] = None
    plan_name: Optional[str] = None
    status: str = "inactive"
    is_active: bool = False
    is_on_trial: bool = False
    trial_days_left: Optional[int] = None
    trial_ends_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class UpgradeDiscountInfo(BaseModel):
    applicable_discount_pct: int = 0
    trial_discount_pct: int = 0
    agent_specific_discount_pct: int = 0
    referral_discount_pct: int = 0
    referral_reward_type: Optional[str] = None
    offer_message: Optional[str] = None


class PlanUpgradeHandoffRequest(BaseModel):
    plan_slug: str


class PlanUpgradeHandoffResponse(BaseModel):
    success: bool = True
    url: str
    expires_in: int
    plan_slug: str


class PlansListResponse(BaseModel):
    success: bool = True
    agent_current_plan: Optional[AgentCurrentPlanInfo] = None
    upgrade_discount: Optional[UpgradeDiscountInfo] = None
    plans: List[PlanItemSchema] = []
