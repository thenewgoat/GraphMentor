"""Course model with ingestion status and learning parameters."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Float, Integer, DateTime, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.postgres import Base


class Course(Base):
    __tablename__ = "courses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    mastery_threshold = Column(Float, nullable=False, default=75.0)
    time_decay_lambda = Column(Float, nullable=False, default=0.1)
    max_follow_ups_per_session = Column(Integer, nullable=False, default=5)
    topic_radius = Column(Integer, nullable=False, default=2)
    ingestion_status = Column(String(20), nullable=False, default="pending")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    nodes = relationship("Node", back_populates="course", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="course", cascade="all, delete-orphan")
    students = relationship(
        "Student", back_populates="course", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "ingestion_status IN ('pending', 'processing', 'complete', 'failed', 'graph_ready')",
            name="chk_ingestion_status",
        ),
    )
