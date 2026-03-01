# Schema: Node

## Overview

A node represents a single topic or concept in the knowledge DAG (Directed Acyclic Graph). Nodes are course-level content entities with no per-student state -- mastery and progress are tracked separately in the `student_node_states` junction table. Each node maps to a set of content chunks stored in ChromaDB for RAG retrieval during the teach phase.

Nodes form a DAG via a separate `node_edges` join table that supports typed relationships (prerequisite, related). The `depth` field encodes the node's position in the DAG hierarchy, used for depth-cap enforcement and topological ordering. The `order_index` field controls sibling display order within the graph view.

## Fields

### `nodes` table

| Field | Type | Constraints | Default | Description |
|---|---|---|---|---|
| `id` | UUID | PK | `gen_random_uuid()` | Unique node identifier |
| `course_id` | UUID | FK -> `courses.id`, NOT NULL | -- | Owning course |
| `title` | VARCHAR(255) | NOT NULL | -- | Human-readable topic title |
| `parent_ids` | UUID[] | References `nodes.id` | `'{}'` | Denormalized DAG parent list (source of truth is `node_edges`) |
| `child_ids` | UUID[] | References `nodes.id` | `'{}'` | Denormalized DAG child list (source of truth is `node_edges`) |
| `content_chunk_ids` | TEXT[] | -- | `'{}'` | ChromaDB document IDs linking to embedded content chunks |
| `depth` | INT | NOT NULL | `0` | DAG depth level (0 = root). Used for depth cap and topological display |
| `order_index` | INT | NOT NULL | `0` | Sibling ordering within the same depth level |
| `application_examples` | JSONB | Nullable | `NULL` | Optional real-life application examples derived from lecture material |
| `created_at` | TIMESTAMPTZ | NOT NULL | `NOW()` | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | `NOW()` | Last modification timestamp |

### `node_edges` join table

| Field | Type | Constraints | Default | Description |
|---|---|---|---|---|
| `parent_id` | UUID | FK -> `nodes.id`, NOT NULL | -- | Source node (prerequisite) |
| `child_id` | UUID | FK -> `nodes.id`, NOT NULL | -- | Target node (dependent) |
| `edge_type` | VARCHAR(20) | NOT NULL | `'prerequisite'` | Relationship type: `'prerequisite'` or `'related'` |

Composite PK: `(parent_id, child_id)`.

## Relationships

- **Belongs to** `courses` via `course_id`.
- **Self-referential many-to-many** via `node_edges` join table. A node can have multiple parents (prerequisites) and multiple children (dependents), forming a DAG.
- **Has many** `student_node_states` (junction table on `student.md`) -- per-student mastery is NOT stored on the node.
- **Has many** `questions` via `questions.node_id`.
- **Referenced by** `students.current_node_id` (nullable FK for current position in the learning loop).
- **ChromaDB linkage:** `content_chunk_ids` references documents in the ChromaDB collection named `course_{course_id}_chunks`. These IDs are used during RAG retrieval in the teach phase and for grounding quiz generation.

## PostgreSQL DDL

```sql
CREATE TABLE nodes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id       UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title           VARCHAR(255) NOT NULL,
    parent_ids      UUID[] NOT NULL DEFAULT '{}',
    child_ids       UUID[] NOT NULL DEFAULT '{}',
    content_chunk_ids TEXT[] NOT NULL DEFAULT '{}',
    depth           INT NOT NULL DEFAULT 0,
    order_index     INT NOT NULL DEFAULT 0,
    application_examples JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE node_edges (
    parent_id   UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    child_id    UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    edge_type   VARCHAR(20) NOT NULL DEFAULT 'prerequisite',
    PRIMARY KEY (parent_id, child_id),
    CHECK (edge_type IN ('prerequisite', 'related')),
    CHECK (parent_id <> child_id)
);

CREATE INDEX idx_nodes_course_id ON nodes(course_id);
CREATE INDEX idx_nodes_depth ON nodes(course_id, depth);
CREATE INDEX idx_node_edges_child ON node_edges(child_id);
```

## SQLAlchemy Model

```python
from sqlalchemy import Column, String, Integer, ForeignKey, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB, TIMESTAMP
from sqlalchemy.orm import relationship
import uuid

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
    parent_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}")
    child_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}")
    content_chunk_ids = Column(ARRAY(String), nullable=False, server_default="{}")
    depth = Column(Integer, nullable=False, server_default=text("0"))
    order_index = Column(Integer, nullable=False, server_default=text("0"))
    application_examples = Column(JSONB, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    course = relationship("Course", back_populates="nodes")
    questions = relationship("Question", back_populates="node")
    student_node_states = relationship("StudentNodeState", back_populates="node")

    # Edge relationships via association table
    children = relationship(
        "Node",
        secondary="node_edges",
        primaryjoin="Node.id == node_edges.c.parent_id",
        secondaryjoin="Node.id == node_edges.c.child_id",
        backref="parents",
    )


class NodeEdge(Base):
    __tablename__ = "node_edges"
    __table_args__ = (
        CheckConstraint("edge_type IN ('prerequisite', 'related')"),
        CheckConstraint("parent_id <> child_id"),
    )

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
    edge_type = Column(String(20), nullable=False, server_default="prerequisite")
```

## TypeScript Type

```typescript
/** Knowledge graph node — course-level content, no per-student state. */
export interface Node {
  id: string;                    // UUID
  courseId: string;               // UUID — FK to courses
  title: string;
  parentIds: string[];            // UUID[] — denormalized DAG parents
  childIds: string[];             // UUID[] — denormalized DAG children
  contentChunkIds: string[];      // ChromaDB document IDs
  depth: number;                  // DAG depth (0 = root)
  orderIndex: number;             // Sibling ordering
  applicationExamples: Record<string, unknown> | null;
  createdAt: string;              // ISO 8601
  updatedAt: string;              // ISO 8601
}

/** Edge in the knowledge DAG. */
export interface NodeEdge {
  parentId: string;               // UUID
  childId: string;                // UUID
  edgeType: "prerequisite" | "related";
}
```

## ChromaDB Linkage

- **Collection naming:** Each course has a ChromaDB collection named `course_{course_id}_chunks`.
- **Document IDs:** The `content_chunk_ids` array on each node contains string IDs that correspond to documents in the course's ChromaDB collection.
- **Ingestion flow:** During PDF ingestion, text is chunked and embedded into ChromaDB. The graph builder then assigns chunk IDs to relevant nodes based on topic extraction.
- **Retrieval flow:** During the teach phase, the system queries ChromaDB using `content_chunk_ids` to retrieve grounded content for RAG-based explanations.
- **Denormalization note:** `parent_ids` and `child_ids` are denormalized from `node_edges` for fast read access. The `node_edges` table is the source of truth and must be kept in sync via application logic or triggers.
