"""Document, Page, NodePage, and Reference models for multi-doc ingestion."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Integer, ForeignKey, DateTime,
    CheckConstraint, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, backref

from app.db.postgres import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    filename = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False)
    file_hash = Column(String(64), nullable=False)
    upload_order = Column(Integer, nullable=False)
    page_count = Column(Integer, nullable=True)
    ingestion_status = Column(String(20), nullable=False, default="pending")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    course = relationship("Course", back_populates="documents")
    pages = relationship("Page", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("course_id", "file_hash", name="uq_course_file_hash"),
        CheckConstraint(
            "ingestion_status IN ('pending', 'processing', 'complete', 'failed')",
            name="chk_doc_ingestion_status",
        ),
        Index("idx_documents_course_id", "course_id"),
    )


class Page(Base):
    __tablename__ = "pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number = Column(Integer, nullable=False)
    global_page = Column(Integer, nullable=False)
    slide_title = Column(Text, nullable=True)
    body = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    document = relationship("Document", back_populates="pages")

    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_doc_page"),
        Index("idx_pages_course_id", "course_id"),
        Index("idx_pages_document_id", "document_id"),
    )


class NodePage(Base):
    __tablename__ = "node_pages"

    node_id = Column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    page_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pages.id", ondelete="CASCADE"),
        primary_key=True,
    )

    node = relationship("Node", backref="node_pages")
    page = relationship("Page", backref=backref("node_pages", passive_deletes=True))


class Reference(Base):
    __tablename__ = "references"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    ref_type = Column(String(20), nullable=False)
    title = Column(Text, nullable=False)
    author = Column(Text, nullable=True)
    isbn = Column(String(20), nullable=True)
    url = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint("ref_type IN ('book', 'url')", name="chk_ref_type"),
        Index("idx_references_course_id", "course_id"),
    )
