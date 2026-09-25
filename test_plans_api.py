import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["CLOUDINARY_CLOUD_NAME"] = "test"
os.environ["CLOUDINARY_API_KEY"] = "test"
os.environ["CLOUDINARY_API_SECRET"] = "test"

from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi_app.database import Base, get_db
from fastapi_app.main import app
import fastapi_app.models
from fastapi_app.models.agent import Agent
from fastapi_app.models.user import User
from fastapi_app.models.subscription_plan import SubscriptionPlan
from fastapi_app.models.site_setting import SiteSetting
from fastapi_app.models.referral_code import ReferralCode
from fastapi_app.dependencies.auth import get_optional_agent
from fastapi_app.utils.auth import create_access_token

# Setup in-memory SQLite engine
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app, raise_server_exceptions=True)

def test_plans_endpoint():
    db = TestingSessionLocal()

    # 1. Seed Subscription Plans
    starter = SubscriptionPlan(
        name="Starter",
        slug="starter",
        description="Ideal for new agents starting digital presence",
        color_theme="starter-theme",
        badge_text="Most Popular for Beginners",
        sort_order=1,
        actual_price=1180.0,
        discounted_price=799.0,
        show_profile_section=True,
        is_listed_in_directory=True,
        show_performance_stats=True,
        show_sales_insights=False,
        show_new_business_leads=True,
        show_recent_leads=True,
        is_active=True
    )
    pro = SubscriptionPlan(
        name="Professional",
        slug="professional",
        description="For ambitious advisors wanting full visibility & direct leads",
        color_theme="pro-theme",
        badge_text="Best Value",
        sort_order=2,
        actual_price=2360.0,
        discounted_price=1499.0,
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
        is_active=True
    )
    exclusive = SubscriptionPlan(
        name="Exclusive Partner",
        slug="exclusive",
        description="Top-tier advisor package with exclusive territory visibility",
        color_theme="exclusive-theme",
        badge_text="VIP Club",
        sort_order=3,
        actual_price=5900.0,
        discounted_price=3999.0,
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
        is_active=True
    )
    db.add_all([starter, pro, exclusive])

    # Seed SiteSetting for default trial discount
    trial_setting = SiteSetting(
        key="trial_upgrade_discount",
        value="25",
        group="pricing"
    )
    db.add(trial_setting)

    # Seed an Agent on Trial
    user = User(
        fullname="Trial Advisor",
        email="trial@example.com",
        password="fake",
        role="agent",
        status="active"
    )
    db.add(user)
    db.flush()

    trial_agent = Agent(
        user_id=user.id,
        fullname="Trial Advisor",
        email=user.email,
        mobile="9876543210",
        agent_pincode="380001",
        status="active",
        plan_type="free_trial",
        trial_ends_at=datetime.utcnow() + timedelta(days=5),
        upgrade_discount_percent=30 # higher than default 25%
    )
    db.add(trial_agent)

    # Seed an Agent on Professional's Plan
    user_pro = User(
        fullname="Pro Advisor",
        email="pro@example.com",
        password="fake",
        role="agent",
        status="active"
    )
    db.add(user_pro)
    db.flush()

    pro_agent = Agent(
        user_id=user_pro.id,
        fullname="Pro Advisor",
        email=user_pro.email,
        mobile="9876543211",
        agent_pincode="380002",
        status="active",
        plan_type="professional",
    )
    db.add(pro_agent)

    db.commit()

    print("\n================== TEST 1: Unauthenticated Guest ==================")
    resp = client.get("/v1/agents/plans")
    assert resp.status_code == 200, f"Failed: {resp.text}"
    body = resp.json()
    assert body["success"] is True
    assert len(body["plans"]) == 3
    assert body["agent_current_plan"] is None
    assert body["upgrade_discount"] is None

    # Check GST calculations for Starter's Plan
    starter_plan = next(p for p in body["plans"] if p["slug"] == "starter")
    p_info = starter_plan["pricing"]
    print(f"Starter Pricing: Actual={p_info['actual_price']}, Disc={p_info['discounted_price']}, BaseExclGST={p_info['base_price_exclusive_gst']}, GST={p_info['gst_amount']}, Final={p_info['final_price_inclusive_gst']}")
    assert starter_plan["is_current_plan"] is False
    assert round(p_info["base_price_exclusive_gst"] + p_info["gst_amount"], 2) == round(p_info["final_price_inclusive_gst"], 2)
    assert p_info["final_price_inclusive_gst"] == 799.0
    print("[PASS] Test 1 passed!")

    print("\n================== TEST 2: Authenticated Trial Agent ==================")
    from fastapi_app.models.user_token import UserToken
    jti_trial = "trial-agent-jti-12345"
    db.add(UserToken(
        jti=jti_trial,
        user_id=user.id,
        is_revoked=False,
        expires_at=datetime.utcnow() + timedelta(days=1)
    ))
    db.commit()

    token = create_access_token(data={"sub": trial_agent.email, "role": "agent", "user_id": user.id, "jti": jti_trial})
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/v1/agents/plans", headers=headers)
    assert resp.status_code == 200, f"Failed: {resp.text}"
    body = resp.json()

    print("Agent Current Plan:", body["agent_current_plan"])
    assert body["agent_current_plan"]["is_on_trial"] is True
    assert body["agent_current_plan"]["trial_days_left"] >= 4

    print("Upgrade Discount:", body["upgrade_discount"])
    # Agent has 30% discount set
    assert body["upgrade_discount"]["applicable_discount_pct"] == 30
    assert "30%" in body["upgrade_discount"]["offer_message"]

    # Verify that plan prices reflect the 30% upgrade discount
    # Professional was 1499.0 discounted price. With 30% off: round(1499 * 0.70) = 1049.0
    pro_plan = next(p for p in body["plans"] if p["slug"] == "professional")
    print(f"Professional's Plan for Trial Agent: Final Incl GST = Rs. {pro_plan['pricing']['final_price_inclusive_gst']}, Agent Disc Pct = {pro_plan['pricing']['agent_discount_pct']}%")
    assert pro_plan["pricing"]["agent_discount_pct"] == 30
    assert pro_plan["pricing"]["final_price_inclusive_gst"] == 1049.0
    assert round(pro_plan["pricing"]["base_price_exclusive_gst"] + pro_plan["pricing"]["gst_amount"], 2) == 1049.0
    print("[PASS] Test 2 passed!")

    print("\n================== TEST 3: Authenticated Pro Plan Agent ==================")
    jti_pro = "pro-agent-jti-67890"
    db.add(UserToken(
        jti=jti_pro,
        user_id=user_pro.id,
        is_revoked=False,
        expires_at=datetime.utcnow() + timedelta(days=1)
    ))
    db.commit()

    token_pro = create_access_token(data={"sub": pro_agent.email, "role": "agent", "user_id": user_pro.id, "jti": jti_pro})
    headers_pro = {"Authorization": f"Bearer {token_pro}"}

    resp = client.get("/v1/agents/plans", headers=headers_pro)
    assert resp.status_code == 200, f"Failed: {resp.text}"
    body = resp.json()

    pro_plan_item = next(p for p in body["plans"] if p["slug"] == "professional")
    starter_plan_item = next(p for p in body["plans"] if p["slug"] == "starter")

    print(f"Professional is_current_plan: {pro_plan_item['is_current_plan']}")
    print(f"Starter is_current_plan: {starter_plan_item['is_current_plan']}")
    assert pro_plan_item["is_current_plan"] is True
    assert starter_plan_item["is_current_plan"] is False
    print("[PASS] Test 3 passed!")

    print("\n================== TEST 4: Referral Reward Pro 1 Rs ==================")
    # Update trial agent with referral_reward_type = 'pro_plan_1rs'
    trial_agent.referral_reward_type = "pro_plan_1rs"
    db.commit()

    resp = client.get("/v1/agents/plans", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    pro_plan_reward = next(p for p in body["plans"] if p["slug"] == "professional")
    print(f"Pro Plan under Referral Reward: Final Incl GST = Rs. {pro_plan_reward['pricing']['final_price_inclusive_gst']}")
    assert pro_plan_reward["pricing"]["final_price_inclusive_gst"] == 1.0
    print("[PASS] Test 4 passed!")

    db.close()
    print("\n>>> ALL TESTS COMPLETED SUCCESSFULLY! <<<")

if __name__ == "__main__":
    test_plans_endpoint()
