from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional

from fastapi_app.database import get_db
from fastapi_app.dependencies.auth import get_current_agent, get_optional_agent
from fastapi_app.models.agent import Agent
from fastapi_app.schemas.plans import (
    PlanUpgradeHandoffRequest,
    PlanUpgradeHandoffResponse,
    PlansListResponse,
)
from fastapi_app.services.plan_service import PlanService
from fastapi_app.services.plan_upgrade_handoff import issue_plan_upgrade_handoff

router = APIRouter(
    prefix="/v1/agents",
    tags=["Subscription Plans"]
)


@router.get("/plans", response_model=PlansListResponse)
@router.get("/plans/", response_model=PlansListResponse, include_in_schema=False)
def get_plans_list(
    current_agent: Optional[Agent] = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """
    List all active subscription plans (Starter, Professional, Exclusive).

    - Returns all live plans from the database.
    - Provides price breakdown: Actual Price vs Discounted Price + 18% GST (base, gst_amount, final).
    - Features / Unlocked benefits list per plan.
    - Highlights current logged-in agent plan (is_current_plan: true/false).
    - Shows applicable special upgrade discount (Trial discount / Referral discount / Agent reward).
    """
    service = PlanService(db)
    return service.get_plans_list(agent=current_agent)


@router.post("/plan-upgrade/handoff", response_model=PlanUpgradeHandoffResponse)
def create_plan_upgrade_handoff(
    body: PlanUpgradeHandoffRequest,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """
    One-time website URL for the logged-in agent.

    The Android app opens `url` in a Chrome Custom Tab. The website logs that
    agent in and opens the upgrade payment for `plan_slug`. The link expires
    in 3 minutes and works once. The agent is taken from the bearer token.
    """
    return issue_plan_upgrade_handoff(db, current_agent, body.plan_slug)
