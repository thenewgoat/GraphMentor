"""Student and StudentNodeState models for learning progress tracking."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Float, ForeignKey, DateTime, CheckConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship

from app.db.postgres import Base


class Student(Base):
    __tablename__ = "students"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_name = Column(String(100), nullable=False)
    current_node_id = Column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    learning_state = Column(String(20), nullable=False, default="baseline")
    session_interaction_count = Column(Integer, default=0)
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
    course = relationship("Course", back_populates="students")
    current_node = relationship("Node", foreign_keys=[current_node_id])
    node_states = relationship(
        "StudentNodeState",
        back_populates="student",
        cascade="all, delete-orphan",
    )
    attempts = relationship("Attempt", back_populates="student")

    __table_args__ = (
        CheckConstraint(
            "learning_state IN ('baseline', 'learning', 'review', 'exam')",
            name="chk_learning_state",
        ),
        Index("idx_students_course_id", "course_id"),
    )


class StudentNodeState(Base):
    __tablename__ = "student_node_states"

    student_id = Column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        primary_key=True,
    )
    node_id = Column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mastery_score = Column(Float, default=0)
    accuracy = Column(Float, default=0)
    confidence_score = Column(Float, default=0)
    teach_completion_score = Column(Float, default=0)
    mistake_classification = Column(ARRAY(String(30)), nullable=True)
    last_reviewed = Column(DateTime(timezone=True), nullable=True)
    total_attempts = Column(Integer, default=0)
    correct_attempts = Column(Integer, default=0)

    # Relationships
    student = relationship("Student", back_populates="node_states")
    node = relationship("Node")

    __table_args__ = (
        CheckConstraint(
            "correct_attempts <= total_attempts",
            name="chk_correct_lte_total",
        ),
        Index("idx_sns_node_id", "node_id"),
        Index("idx_sns_mastery", "student_id", "mastery_score"),
    )
