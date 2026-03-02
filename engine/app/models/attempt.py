"""Question and Attempt models for student assessment tracking."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, ForeignKey, DateTime,
    CheckConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import relationship

from app.db.postgres import Base


class Question(Base):
    __tablename__ = "questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id = Column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_type = Column(String(20), nullable=False)
    question_text = Column(Text, nullable=False)
    options = Column(JSONB, nullable=True)
    correct_answer = Column(Text, nullable=False)
    expected_time_seconds = Column(Integer, nullable=False, default=30)
    difficulty = Column(String(10), nullable=False, default="medium")
    source_chunk_ids = Column(ARRAY(String), default=list)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    node = relationship("Node", back_populates="questions")
    attempts = relationship("Attempt", back_populates="question")

    __table_args__ = (
        CheckConstraint(
            "question_type IN ('multiple_choice', 'short_answer')",
            name="chk_question_type",
        ),
        CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard')",
            name="chk_difficulty",
        ),
        Index("idx_questions_node_id", "node_id"),
        Index("idx_questions_difficulty", "node_id", "difficulty"),
    )


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id = Column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id = Column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    answer = Column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=False)
    response_time_seconds = Column(Float, nullable=False)
    attempt_context = Column(String(20), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    student = relationship("Student", back_populates="attempts")
    question = relationship("Question", back_populates="attempts")
    node = relationship("Node")

    __table_args__ = (
        CheckConstraint(
            "attempt_context IN ('baseline', 'quiz', 'exam')",
            name="chk_attempt_context",
        ),
        Index("idx_attempts_student_id", "student_id"),
        Index("idx_attempts_student_node", "student_id", "node_id"),
        Index("idx_attempts_question_id", "question_id"),
        Index(
            "idx_attempts_created_at", "student_id", "node_id",
            created_at.desc(),
        ),
    )
