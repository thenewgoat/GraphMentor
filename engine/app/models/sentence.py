import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Text, ForeignKey, DateTime, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, backref

from app.db.postgres import Base


class Sentence(Base):
    __tablename__ = "sentences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    page = Column(Integer, nullable=False)
    position = Column(Integer, nullable=False)
    slide_title = Column(Text, nullable=True)
    text = Column(Text, nullable=False)
    hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    course = relationship(
        "Course",
        backref=backref(
            "sentences",
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
    )

    __table_args__ = (
        Index("idx_sentences_course_id", "course_id"),
        Index("idx_sentences_course_page", "course_id", "page"),
    )


class NodeSentence(Base):
    __tablename__ = "node_sentences"

    node_id = Column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sentence_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sentences.id", ondelete="CASCADE"),
        primary_key=True,
    )

    node = relationship("Node", backref="node_sentences")
    sentence = relationship("Sentence", backref="node_sentences")
