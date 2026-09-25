from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from fastapi_app.database import Base

class ReferralCode(Base):
    __tablename__ = "referral_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(191), nullable=False, unique=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    clicks = Column(Integer, default=0)
    total_referrals = Column(Integer, default=0)
    reward_claimed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def current_tier(self) -> dict:
        # Replicates PHP tier logic:
        # Tier 1: 1 referral -> 10% discount
        # Tier 2: 3 referrals -> 20% discount
        # Tier 3: 5 referrals -> Pro plan for 1 Rupee
        ref_count = self.total_referrals
        if ref_count >= 5:
            return {"tier": 3, "discount": 100, "label": "Tier 3: Professional's Plan for 1 Rupee"}
        elif ref_count >= 3:
            return {"tier": 2, "discount": 20, "label": "Tier 2: 20% Discount"}
        elif ref_count >= 1:
            return {"tier": 1, "discount": 10, "label": "Tier 1: 10% Discount"}
        return {"tier": 0, "discount": 0, "label": "No referrals yet"}

    def next_tier(self) -> dict:
        ref_count = self.total_referrals
        if ref_count < 1:
            return {"tier": 1, "min": 1, "discount": 10, "label": "Tier 1"}
        elif ref_count < 3:
            return {"tier": 2, "min": 3, "discount": 20, "label": "Tier 2"}
        elif ref_count < 5:
            return {"tier": 3, "min": 5, "discount": 100, "label": "Tier 3"}
        return None
