from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from fastapi_app.database import Base
from sqlalchemy.sql import func

class AgentCareerTimeline(Base):
    __tablename__ = "agent_career_timelines"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(255), nullable=False)
    event_text = Column(Text, nullable=False)
    month = Column(String(50), default="")
    year = Column(String(4), nullable=False)
    suggestion_key = Column(String(50), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    agent = relationship("Agent", back_populates="career_timelines")
