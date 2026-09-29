from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from fastapi_app.database import Base


class PlanUpgradeHandoff(Base):
    """One-time token that logs an app user into the website upgrade checkout."""

    __tablename__ = "plan_upgrade_handoffs"

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_slug = Column(String(32), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False)
