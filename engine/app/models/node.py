import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Integer, ForeignKey, DateTime, CheckConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import relationship

from app.db.postgres import Base


class Node(Base):
    __tablename__ = "nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    parent_ids = Column(ARRAY(UUID(as_uuid=True)), default=list)
    child_ids = Column(ARRAY(UUID(as_uuid=True)), default=list)
    depth = Column(Integer, nullable=False, default=0)
    order_index = Column(Integer, nullable=False, default=0)
    application_examples = Column(JSONB, nullable=True)
    supplementary_content = Column(Text, nullable=True)
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
    course = relationship("Course", back_populates="nodes")
    questions = relationship(
        "Question", back_populates="node", cascade="all, delete-orphan"
    )
    parent_edges = relationship(
        "NodeEdge",
        foreign_keys="NodeEdge.child_id",
        back_populates="child_node",
        cascade="all, delete-orphan",
    )
    child_edges = relationship(
        "NodeEdge",
        foreign_keys="NodeEdge.parent_id",
        back_populates="parent_node",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_nodes_course_id", "course_id"),
        Index("idx_nodes_depth", "course_id", "depth"),
    )


class NodeEdge(Base):
    __tablename__ = "node_edges"

    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    child_id = Column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    edge_type = Column(String(20), default="prerequisite")

    # Relationships
    parent_node = relationship(
        "Node", foreign_keys=[parent_id], back_populates="child_edges"
    )
    child_node = relationship(
        "Node", foreign_keys=[child_id], back_populates="parent_edges"
    )

    __table_args__ = (
        CheckConstraint("parent_id != child_id", name="chk_no_self_loop"),
        CheckConstraint(
            "edge_type IN ('prerequisite', 'related')", name="chk_edge_type"
        ),
        Index("idx_node_edges_child", "child_id"),
    )
