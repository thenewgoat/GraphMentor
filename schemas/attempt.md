# Schema: Attempt

## Overview

The attempt schema comprises two tables. The `questions` table stores generated quiz items -- these are LLM-generated from node content via RAG and persist for reuse and analytics. The `attempts` table stores individual student responses to questions, capturing answer correctness, timing, and context.

Questions are always scoped to a single node. They include `source_chunk_ids` that trace back to ChromaDB documents used to generate the question, enabling grounding verification. Attempts are the raw event log that drives the scoring engine -- accuracy, confidence, and mistake classification are all computed from attempt records.

## Fields

### `questions` table

| Field | Type | Constraints | Default | Description |
|---|---|---|---|---|
| `id` | UUID | PK | `gen_random_uuid()` | Unique question identifier |
| `node_id` | UUID | FK -> `nodes.id`, NOT NULL | -- | The node this question tests |
| `question_type` | VARCHAR(20) | NOT NULL | -- | Question format: `'multiple_choice'` or `'short_answer'` |
| `question_text` | TEXT | NOT NULL | -- | The question prompt |
| `options` | JSONB | Nullable | `NULL` | For MC questions: `[{label: "A", text: "...", is_correct: true/false}, ...]`. NULL for short answer |
| `correct_answer` | TEXT | NOT NULL | -- | Canonical correct answer text. For MC, the correct option's text |
| `expected_time_seconds` | INT | NOT NULL | `30` | Expected response time. Used in confidence score calculation |
| `difficulty` | VARCHAR(10) | NOT NULL | `'medium'` | Difficulty tier: `'easy'`, `'medium'`, or `'hard'` |
| `source_chunk_ids` | TEXT[] | NOT NULL | `'{}'` | ChromaDB document IDs used to generate this question. Enables grounding audit |
| `created_at` | TIMESTAMPTZ | NOT NULL | `NOW()` | Row creation timestamp |

### `attempts` table

| Field | Type | Constraints | Default | Description |
|---|---|---|---|---|
| `id` | UUID | PK | `gen_random_uuid()` | Unique attempt identifier |
| `student_id` | UUID | FK -> `students.id`, NOT NULL | -- | Student who made the attempt |
| `question_id` | UUID | FK -> `questions.id`, NOT NULL | -- | Question being answered |
| `node_id` | UUID | FK -> `nodes.id`, NOT NULL | -- | Denormalized from `questions.node_id` for query performance |
| `answer` | TEXT | NOT NULL | -- | Student's submitted answer text |
| `is_correct` | BOOLEAN | NOT NULL | -- | Whether the answer was graded as correct |
| `response_time_seconds` | FLOAT | NOT NULL | -- | Time taken to respond in seconds. Feeds confidence modeling |
| `attempt_context` | VARCHAR(20) | NOT NULL | -- | Learning phase when attempt occurred: `'baseline'`, `'quiz'`, or `'exam'` |
| `created_at` | TIMESTAMPTZ | NOT NULL | `NOW()` | Row creation timestamp |

## Relationships

- **`questions` belongs to** `nodes` via `node_id`.
- **`questions` has many** `attempts` via `attempts.question_id`.
- **`attempts` belongs to** `students` via `student_id`.
- **`attempts` belongs to** `questions` via `question_id`.
- **`attempts` references** `nodes` via `node_id` (denormalized -- duplicates `questions.node_id` for efficient student-node queries without joining through questions).
- **Scoring dependency:** After each attempt is recorded, the scoring engine recomputes `student_node_states.accuracy`, `confidence_score`, and `mastery_score` using all attempts for that student-node pair.

## PostgreSQL DDL

```sql
CREATE TABLE questions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id                 UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    question_type           VARCHAR(20) NOT NULL,
    question_text           TEXT NOT NULL,
    options                 JSONB,
    correct_answer          TEXT NOT NULL,
    expected_time_seconds   INT NOT NULL DEFAULT 30,
    difficulty              VARCHAR(10) NOT NULL DEFAULT 'medium',
    source_chunk_ids        TEXT[] NOT NULL DEFAULT '{}',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (question_type IN ('multiple_choice', 'short_answer')),
    CHECK (difficulty IN ('easy', 'medium', 'hard')),
    CHECK (expected_time_seconds > 0)
);

CREATE TABLE attempts (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id              UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    question_id             UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    node_id                 UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    answer                  TEXT NOT NULL,
    is_correct              BOOLEAN NOT NULL,
    response_time_seconds   FLOAT NOT NULL,
    attempt_context         VARCHAR(20) NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (attempt_context IN ('baseline', 'quiz', 'exam')),
    CHECK (response_time_seconds >= 0)
);

CREATE INDEX idx_questions_node_id ON questions(node_id);
CREATE INDEX idx_questions_difficulty ON questions(node_id, difficulty);
CREATE INDEX idx_attempts_student_id ON attempts(student_id);
CREATE INDEX idx_attempts_student_node ON attempts(student_id, node_id);
CREATE INDEX idx_attempts_question_id ON attempts(question_id);
CREATE INDEX idx_attempts_context ON attempts(student_id, attempt_context);
CREATE INDEX idx_attempts_created ON attempts(student_id, node_id, created_at);
```

## SQLAlchemy Model

```python
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, ForeignKey,
    CheckConstraint, text,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB, TIMESTAMP
from sqlalchemy.orm import relationship
import uuid

from app.db.postgres import Base


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint("question_type IN ('multiple_choice', 'short_answer')"),
        CheckConstraint("difficulty IN ('easy', 'medium', 'hard')"),
        CheckConstraint("expected_time_seconds > 0"),
    )

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
    expected_time_seconds = Column(
        Integer, nullable=False, server_default=text("30")
    )
    difficulty = Column(String(10), nullable=False, server_default="medium")
    source_chunk_ids = Column(ARRAY(String), nullable=False, server_default="{}")
    created_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    node = relationship("Node", back_populates="questions")
    attempts = relationship("Attempt", back_populates="question")


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint("attempt_context IN ('baseline', 'quiz', 'exam')"),
        CheckConstraint("response_time_seconds >= 0"),
    )

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
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    student = relationship("Student", back_populates="attempts")
    question = relationship("Question", back_populates="attempts")
    node = relationship("Node")
```

## TypeScript Type

```typescript
/** Multiple-choice option structure stored in questions.options JSONB. */
export interface QuestionOption {
  label: string;          // "A", "B", "C", "D"
  text: string;           // Option text
  isCorrect: boolean;     // Whether this is the correct answer
}

/** Generated quiz question tied to a single node. */
export interface Question {
  id: string;                           // UUID
  nodeId: string;                       // UUID — FK to nodes
  questionType: "multiple_choice" | "short_answer";
  questionText: string;
  options: QuestionOption[] | null;     // Non-null only for multiple_choice
  correctAnswer: string;
  expectedTimeSeconds: number;          // Default 30
  difficulty: "easy" | "medium" | "hard";
  sourceChunkIds: string[];             // ChromaDB document IDs
  createdAt: string;                    // ISO 8601
}

/** A single student response to a question. */
export interface Attempt {
  id: string;                           // UUID
  studentId: string;                    // UUID — FK to students
  questionId: string;                   // UUID — FK to questions
  nodeId: string;                       // UUID — denormalized FK to nodes
  answer: string;
  isCorrect: boolean;
  responseTimeSeconds: number;
  attemptContext: "baseline" | "quiz" | "exam";
  createdAt: string;                    // ISO 8601
}
```

## ChromaDB Linkage

- **Question generation grounding:** The `questions.source_chunk_ids` array contains ChromaDB document IDs from the collection `course_{course_id}_chunks` (where `course_id` is resolved through `nodes.course_id`). These IDs identify the specific content chunks that the quiz generation LLM used as context to formulate the question.
- **Grounding audit:** When a student challenges a question or the system needs to verify correctness, the `source_chunk_ids` allow retrieval of the original lecture material that justifies the expected answer.
- **No direct ChromaDB reference on attempts:** The `attempts` table is a pure event log. Any ChromaDB interaction (e.g., retrieving explanation content after a wrong answer) is mediated through the question's `source_chunk_ids` or the node's `content_chunk_ids`.
- **Confidence calculation flow:** `attempts.response_time_seconds` is compared against `questions.expected_time_seconds` to derive the confidence weight used in mastery scoring. The formula lives in `engine/app/services/confidence.py`.
