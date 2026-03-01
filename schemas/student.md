# Schema: Student

## Overview

The student schema comprises two tables. The `students` table holds student identity, course enrollment, and session-level state (current position in the learning loop, learning phase, interaction count). The `student_node_states` junction table holds per-student-per-node mastery data -- this is where all scoring, accuracy, confidence, and mistake classification lives.

This separation is a deliberate design decision: nodes are course-level content (shared across all students), while mastery is per-student state. The junction table pattern enables efficient queries for both "all nodes for a student" and "all students for a node" without polluting the node schema.

## Fields

### `students` table

| Field | Type | Constraints | Default | Description |
|---|---|---|---|---|
| `id` | UUID | PK | `gen_random_uuid()` | Unique student identifier |
| `course_id` | UUID | FK -> `courses.id`, NOT NULL | -- | Enrolled course |
| `display_name` | VARCHAR(100) | NOT NULL | -- | Student's display name |
| `current_node_id` | UUID | FK -> `nodes.id`, Nullable | `NULL` | Current position in the learning loop. NULL before baseline or after completion |
| `learning_state` | VARCHAR(20) | NOT NULL | `'baseline'` | Current phase in the learning state machine. Enum: `baseline`, `learning`, `review`, `exam` |
| `session_interaction_count` | INT | NOT NULL | `0` | Number of follow-up interactions in the current session. Used for CIF cap enforcement |
| `created_at` | TIMESTAMPTZ | NOT NULL | `NOW()` | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL | `NOW()` | Last modification timestamp |

### `student_node_states` junction table

| Field | Type | Constraints | Default | Description |
|---|---|---|---|---|
| `student_id` | UUID | FK -> `students.id`, NOT NULL | -- | Student reference |
| `node_id` | UUID | FK -> `nodes.id`, NOT NULL | -- | Node reference |
| `mastery_score` | FLOAT | NOT NULL, CHECK (0 <= val <= 100) | `0` | Composite mastery score (accuracy x confidence x time_decay + teach_base) |
| `accuracy` | FLOAT | NOT NULL, CHECK (0 <= val <= 1) | `0` | Correct / Total attempts ratio |
| `confidence_score` | FLOAT | NOT NULL, CHECK (0 <= val <= 1) | `0` | Time-based confidence weight derived from response time vs expected time |
| `teach_completion_score` | FLOAT | NOT NULL, CHECK (0 <= val <= 1) | `0` | Engagement bonus from completing teach phase content |
| `mistake_classification` | VARCHAR(30)[] | Nullable | `NULL` | Array of heuristic labels: conceptual_misunderstanding, memory_decay, misreading, pattern_confusion, surface_error |
| `last_reviewed` | TIMESTAMPTZ | Nullable | `NULL` | Timestamp of last quiz or review interaction for this node. Used in time decay calculation |
| `total_attempts` | INT | NOT NULL | `0` | Total quiz attempts for this student-node pair |
| `correct_attempts` | INT | NOT NULL | `0` | Correct quiz attempts for this student-node pair |

Composite PK: `(student_id, node_id)`.

## Relationships

- **`students` belongs to** `courses` via `course_id`.
- **`students` references** `nodes` via `current_node_id` (nullable -- NULL when not actively in a learning loop iteration).
- **`students` has many** `student_node_states` via `student_id`.
- **`students` has many** `attempts` via `attempts.student_id`.
- **`student_node_states` bridges** `students` and `nodes` -- classic many-to-many junction table.
- **`student_node_states` references** `nodes` via `node_id` -- used to look up the node's `content_chunk_ids` for ChromaDB retrieval when reviewing mistakes.

## PostgreSQL DDL

```sql
CREATE TABLE students (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id                   UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    display_name                VARCHAR(100) NOT NULL,
    current_node_id             UUID REFERENCES nodes(id) ON DELETE SET NULL,
    learning_state              VARCHAR(20) NOT NULL DEFAULT 'baseline',
    session_interaction_count   INT NOT NULL DEFAULT 0,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (learning_state IN ('baseline', 'learning', 'review', 'exam'))
);

CREATE TABLE student_node_states (
    student_id              UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    node_id                 UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    mastery_score           FLOAT NOT NULL DEFAULT 0,
    accuracy                FLOAT NOT NULL DEFAULT 0,
    confidence_score        FLOAT NOT NULL DEFAULT 0,
    teach_completion_score  FLOAT NOT NULL DEFAULT 0,
    mistake_classification  VARCHAR(30)[],
    last_reviewed           TIMESTAMPTZ,
    total_attempts          INT NOT NULL DEFAULT 0,
    correct_attempts        INT NOT NULL DEFAULT 0,
    PRIMARY KEY (student_id, node_id),
    CHECK (mastery_score >= 0 AND mastery_score <= 100),
    CHECK (accuracy >= 0 AND accuracy <= 1),
    CHECK (confidence_score >= 0 AND confidence_score <= 1),
    CHECK (teach_completion_score >= 0 AND teach_completion_score <= 1),
    CHECK (correct_attempts <= total_attempts)
);

CREATE INDEX idx_students_course_id ON students(course_id);
CREATE INDEX idx_students_current_node ON students(current_node_id);
CREATE INDEX idx_student_node_states_node ON student_node_states(node_id);
CREATE INDEX idx_student_node_states_mastery ON student_node_states(student_id, mastery_score);
```

## SQLAlchemy Model

```python
from sqlalchemy import (
    Column, String, Integer, Float, ForeignKey, CheckConstraint, text,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, TIMESTAMP
from sqlalchemy.orm import relationship
import uuid

from app.db.postgres import Base


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        CheckConstraint(
            "learning_state IN ('baseline', 'learning', 'review', 'exam')"
        ),
    )

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
    learning_state = Column(String(20), nullable=False, server_default="baseline")
    session_interaction_count = Column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    course = relationship("Course", back_populates="students")
    current_node = relationship("Node", foreign_keys=[current_node_id])
    node_states = relationship("StudentNodeState", back_populates="student")
    attempts = relationship("Attempt", back_populates="student")


class StudentNodeState(Base):
    __tablename__ = "student_node_states"
    __table_args__ = (
        CheckConstraint("mastery_score >= 0 AND mastery_score <= 100"),
        CheckConstraint("accuracy >= 0 AND accuracy <= 1"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 1"),
        CheckConstraint("teach_completion_score >= 0 AND teach_completion_score <= 1"),
        CheckConstraint("correct_attempts <= total_attempts"),
    )

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
    mastery_score = Column(Float, nullable=False, server_default=text("0"))
    accuracy = Column(Float, nullable=False, server_default=text("0"))
    confidence_score = Column(Float, nullable=False, server_default=text("0"))
    teach_completion_score = Column(Float, nullable=False, server_default=text("0"))
    mistake_classification = Column(ARRAY(String(30)), nullable=True)
    last_reviewed = Column(TIMESTAMP(timezone=True), nullable=True)
    total_attempts = Column(Integer, nullable=False, server_default=text("0"))
    correct_attempts = Column(Integer, nullable=False, server_default=text("0"))

    # Relationships
    student = relationship("Student", back_populates="node_states")
    node = relationship("Node", back_populates="student_node_states")
```

## TypeScript Type

```typescript
/** Student identity and session state. */
export interface Student {
  id: string;                         // UUID
  courseId: string;                    // UUID — FK to courses
  displayName: string;
  currentNodeId: string | null;       // UUID — nullable, current position in loop
  learningState: "baseline" | "learning" | "review" | "exam";
  sessionInteractionCount: number;    // CIF cap counter
  createdAt: string;                  // ISO 8601
  updatedAt: string;                  // ISO 8601
}

/** Per-student-per-node mastery state. Junction table row. */
export interface StudentNodeState {
  studentId: string;                  // UUID
  nodeId: string;                     // UUID
  masteryScore: number;               // 0-100
  accuracy: number;                   // 0-1
  confidenceScore: number;            // 0-1
  teachCompletionScore: number;       // 0-1
  mistakeClassification: string[] | null;  // Heuristic labels
  lastReviewed: string | null;        // ISO 8601 or null
  totalAttempts: number;
  correctAttempts: number;
}
```

## ChromaDB Linkage

The `student_node_states` table does not directly reference ChromaDB. However, it is closely coupled to ChromaDB-backed content through the `node_id` foreign key:

- **Teach phase retrieval:** When the scoring engine identifies a student's weakest node (lowest `mastery_score`), the teach service uses the node's `content_chunk_ids` to query ChromaDB for grounded explanation content.
- **Mistake-driven retrieval:** When `mistake_classification` contains `conceptual_misunderstanding`, the teach phase may perform targeted ChromaDB queries scoped to the node's chunks to generate focused re-explanations.
- **Time decay calculation:** The `last_reviewed` timestamp feeds into the mastery formula: `TimeDecay = e^(-lambda * days_since_review)`, where lambda comes from `courses.time_decay_lambda`.
