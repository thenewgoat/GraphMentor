# Schema: Course

## Overview

The course is the top-level container entity in GraphMentor. It represents a single uploaded PDF lecture set and all derived learning content. The current system focuses on single-course usage, but the schema is designed for multi-course extensibility -- every child entity (nodes, students, questions) references a course, enabling future isolation.

The course table also holds system-wide tuning parameters: mastery threshold, time decay lambda, CIF enforcement limits, and topic radius. These are per-course rather than global constants so that different courses can have different learning dynamics.

The `ingestion_status` field tracks the PDF processing pipeline state, from upload through chunking, embedding, and graph construction.

## Fields

### `courses` table

| Field | Type | Constraints | Default | Description |
|---|---|---|---|---|
| `id` | UUID | PK | `gen_random_uuid()` | Unique course identifier |
| `title` | VARCHAR(255) | NOT NULL | -- | Course title (e.g., "CS 101 - Intro to Algorithms") |
| `description` | TEXT | Nullable | `NULL` | Optional course description or notes |
| `source_pdf_path` | TEXT | NOT NULL | -- | Local filesystem path to the uploaded PDF |
| `source_pdf_hash` | VARCHAR(64) | NOT NULL, UNIQUE | -- | SHA-256 hash of the PDF file. Prevents duplicate ingestion |
| `mastery_threshold` | FLOAT | NOT NULL | `75.0` | Mastery score (0-100) at which a node is considered "complete" |
| `time_decay_lambda` | FLOAT | NOT NULL | `0.1` | Lambda parameter for time decay formula: `e^(-lambda * days_since_review)` |
| `max_follow_ups_per_session` | INT | NOT NULL | `5` | Maximum follow-up interactions allowed per session. CIF enforcement |
| `topic_radius` | INT | NOT NULL | `2` | Maximum DAG distance from the current node for CIF scoping (node +/- radius) |
| `ingestion_status` | VARCHAR(20) | NOT NULL | `'pending'` | Pipeline state: `'pending'`, `'processing'`, `'complete'`, or `'failed'` |
| `created_at` | TIMESTAMPTZ | NOT NULL | `NOW()` | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | `NOW()` | Last modification timestamp |

## Relationships

- **Has many** `nodes` -- all knowledge graph nodes belong to a course.
- **Has many** `students` -- student enrollment is per-course.
- **Indirectly has many** `questions` (through nodes) and `attempts` (through students).
- **ChromaDB collection owner:** Each course owns a ChromaDB collection named `course_{course_id}_chunks` that stores all embedded content from the PDF.

## PostgreSQL DDL

```sql
CREATE TABLE courses (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title                       VARCHAR(255) NOT NULL,
    description                 TEXT,
    source_pdf_path             TEXT NOT NULL,
    source_pdf_hash             VARCHAR(64) NOT NULL UNIQUE,
    mastery_threshold           FLOAT NOT NULL DEFAULT 75.0,
    time_decay_lambda           FLOAT NOT NULL DEFAULT 0.1,
    max_follow_ups_per_session  INT NOT NULL DEFAULT 5,
    topic_radius                INT NOT NULL DEFAULT 2,
    ingestion_status            VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (mastery_threshold >= 0 AND mastery_threshold <= 100),
    CHECK (time_decay_lambda > 0),
    CHECK (max_follow_ups_per_session > 0),
    CHECK (topic_radius >= 0),
    CHECK (ingestion_status IN ('pending', 'processing', 'complete', 'failed'))
);

CREATE INDEX idx_courses_ingestion_status ON courses(ingestion_status);
CREATE UNIQUE INDEX idx_courses_pdf_hash ON courses(source_pdf_hash);
```

## SQLAlchemy Model

```python
from sqlalchemy import Column, String, Integer, Float, Text, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from sqlalchemy.orm import relationship
import uuid

from app.db.postgres import Base


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint("mastery_threshold >= 0 AND mastery_threshold <= 100"),
        CheckConstraint("time_decay_lambda > 0"),
        CheckConstraint("max_follow_ups_per_session > 0"),
        CheckConstraint("topic_radius >= 0"),
        CheckConstraint(
            "ingestion_status IN ('pending', 'processing', 'complete', 'failed')"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source_pdf_path = Column(Text, nullable=False)
    source_pdf_hash = Column(String(64), nullable=False, unique=True)
    mastery_threshold = Column(Float, nullable=False, server_default=text("75.0"))
    time_decay_lambda = Column(Float, nullable=False, server_default=text("0.1"))
    max_follow_ups_per_session = Column(
        Integer, nullable=False, server_default=text("5")
    )
    topic_radius = Column(Integer, nullable=False, server_default=text("2"))
    ingestion_status = Column(String(20), nullable=False, server_default="pending")
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    nodes = relationship("Node", back_populates="course", cascade="all, delete-orphan")
    students = relationship(
        "Student", back_populates="course", cascade="all, delete-orphan"
    )
```

## TypeScript Type

```typescript
/** Top-level course container. Owns nodes, students, and a ChromaDB collection. */
export interface Course {
  id: string;                         // UUID
  title: string;
  description: string | null;
  sourcePdfPath: string;              // Local filesystem path
  sourcePdfHash: string;              // SHA-256 hex digest (64 chars)
  masteryThreshold: number;           // 0-100, default 75.0
  timeDecayLambda: number;            // > 0, default 0.1
  maxFollowUpsPerSession: number;     // > 0, default 5
  topicRadius: number;                // >= 0, default 2
  ingestionStatus: "pending" | "processing" | "complete" | "failed";
  createdAt: string;                  // ISO 8601
  updatedAt: string;                  // ISO 8601
}
```

## ChromaDB Linkage

- **Collection lifecycle:** When a course is created and PDF ingestion begins, the engine creates a ChromaDB collection named `course_{course_id}_chunks`. This collection persists for the lifetime of the course.
- **Ingestion pipeline:** During `processing` status, the ingestion service extracts text from `source_pdf_path`, chunks it, generates embeddings (OpenAI text-embedding-ada-002), and stores them in the course's ChromaDB collection. Each chunk becomes a document with a unique ID.
- **Deduplication:** The `source_pdf_hash` (SHA-256) prevents re-ingesting the same PDF. If a matching hash exists, the system rejects the upload or links to the existing course.
- **Collection deletion:** When a course is deleted (CASCADE), the application layer must also delete the corresponding ChromaDB collection. This is not enforced at the database level since ChromaDB is an external store.
- **Collection metadata:** The ChromaDB collection stores metadata per document including `page_number`, `chunk_index`, and `section_title` to support citation generation during the teach phase.
