"""Tests for all SQLAlchemy models, relationships, and constraints."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    Course, Node, NodeEdge, Student, StudentNodeState, Question, Attempt,
    Document, Page, NodePage, Reference,
)


def _make_course(db, **overrides):
    defaults = dict(title="Test Course")
    defaults.update(overrides)
    course = Course(**defaults)
    db.add(course)
    db.flush()
    return course


class TestCourse:
    def test_create_course(self, db):
        course = _make_course(db)
        assert course.id is not None
        assert course.ingestion_status == "pending"
        assert course.mastery_threshold == 75.0
        assert course.time_decay_lambda == 0.1
        assert course.max_follow_ups_per_session == 5
        assert course.topic_radius == 2

    def test_course_requires_title(self, db):
        course = Course(title=None)
        db.add(course)
        with pytest.raises(IntegrityError):
            db.flush()


class TestNode:
    def test_create_node(self, db):
        course = _make_course(db)
        node = Node(course_id=course.id, title="Topic A")
        db.add(node)
        db.flush()
        assert node.id is not None
        assert node.depth == 0
        assert node.order_index == 0

    def test_node_edge(self, db):
        course = _make_course(db)
        parent = Node(course_id=course.id, title="Parent")
        child = Node(course_id=course.id, title="Child")
        db.add_all([parent, child])
        db.flush()

        edge = NodeEdge(parent_id=parent.id, child_id=child.id, edge_type="prerequisite")
        db.add(edge)
        db.flush()
        assert edge.parent_id == parent.id
        assert edge.child_id == child.id

    def test_node_edge_no_self_loop(self, db):
        course = _make_course(db)
        node = Node(course_id=course.id, title="Self")
        db.add(node)
        db.flush()

        edge = NodeEdge(parent_id=node.id, child_id=node.id)
        db.add(edge)
        with pytest.raises(IntegrityError):
            db.flush()

    def test_node_supplementary_content(self, db):
        course = _make_course(db)
        node = Node(course_id=course.id, title="Topic", supplementary_content="Extra info")
        db.add(node)
        db.flush()
        assert node.supplementary_content == "Extra info"


class TestDocument:
    def test_create_document(self, db):
        course = _make_course(db)
        doc = Document(
            course_id=course.id, title="Lecture 1", filename="lec1.pdf",
            file_path="/tmp/lec1.pdf", file_hash="a" * 64, upload_order=1,
        )
        db.add(doc)
        db.flush()
        assert doc.id is not None
        assert doc.ingestion_status == "pending"

    def test_document_unique_hash_per_course(self, db):
        course = _make_course(db)
        hash_val = "d" * 64
        db.add(Document(
            course_id=course.id, title="Doc 1", filename="d1.pdf",
            file_path="/tmp/d1.pdf", file_hash=hash_val, upload_order=1,
        ))
        db.flush()
        db.add(Document(
            course_id=course.id, title="Doc 2", filename="d2.pdf",
            file_path="/tmp/d2.pdf", file_hash=hash_val, upload_order=2,
        ))
        with pytest.raises(IntegrityError):
            db.flush()

    def test_page_creation(self, db):
        course = _make_course(db)
        doc = Document(
            course_id=course.id, title="Doc", filename="d.pdf",
            file_path="/tmp/d.pdf", file_hash="e" * 64, upload_order=1,
        )
        db.add(doc)
        db.flush()

        page = Page(
            document_id=doc.id, course_id=course.id,
            page_number=1, global_page=1, body="Hello world",
        )
        db.add(page)
        db.flush()
        assert page.id is not None

    def test_node_page_mapping(self, db):
        course = _make_course(db)
        doc = Document(
            course_id=course.id, title="Doc", filename="d.pdf",
            file_path="/tmp/d.pdf", file_hash="f" * 64, upload_order=1,
        )
        node = Node(course_id=course.id, title="Topic")
        db.add_all([doc, node])
        db.flush()

        page = Page(
            document_id=doc.id, course_id=course.id,
            page_number=1, global_page=1, body="Content",
        )
        db.add(page)
        db.flush()

        np = NodePage(node_id=node.id, page_id=page.id)
        db.add(np)
        db.flush()
        assert np.node_id == node.id
        assert np.page_id == page.id

    def test_reference_creation(self, db):
        course = _make_course(db)
        ref = Reference(
            course_id=course.id, ref_type="book",
            title="CLRS", author="Cormen et al.",
        )
        db.add(ref)
        db.flush()
        assert ref.id is not None


class TestStudent:
    def test_create_student(self, db):
        course = _make_course(db)
        student = Student(course_id=course.id, display_name="Alice")
        db.add(student)
        db.flush()
        assert student.id is not None
        assert student.learning_state == "baseline"
        assert student.session_interaction_count == 0
        assert student.current_node_id is None

    def test_student_node_state(self, db):
        course = _make_course(db)
        student = Student(course_id=course.id, display_name="Bob")
        node = Node(course_id=course.id, title="Topic")
        db.add_all([student, node])
        db.flush()

        state = StudentNodeState(
            student_id=student.id,
            node_id=node.id,
            mastery_score=42.5,
            accuracy=0.7,
            total_attempts=10,
            correct_attempts=7,
        )
        db.add(state)
        db.flush()
        assert state.mastery_score == 42.5

    def test_correct_lte_total_constraint(self, db):
        course = _make_course(db)
        student = Student(course_id=course.id, display_name="Eve")
        node = Node(course_id=course.id, title="Topic")
        db.add_all([student, node])
        db.flush()

        state = StudentNodeState(
            student_id=student.id,
            node_id=node.id,
            total_attempts=5,
            correct_attempts=10,
        )
        db.add(state)
        with pytest.raises(IntegrityError):
            db.flush()


class TestAttempt:
    def _make_fixtures(self, db):
        course = _make_course(db)
        node = Node(course_id=course.id, title="Topic")
        student = Student(course_id=course.id, display_name="Carol")
        db.add_all([node, student])
        db.flush()

        question = Question(
            node_id=node.id,
            question_type="multiple_choice",
            question_text="What is X?",
            correct_answer="B",
            options=[
                {"label": "A", "text": "Wrong", "is_correct": False},
                {"label": "B", "text": "Right", "is_correct": True},
            ],
        )
        db.add(question)
        db.flush()
        return course, node, student, question

    def test_create_question(self, db):
        _, node, _, question = self._make_fixtures(db)
        assert question.id is not None
        assert question.node_id == node.id
        assert question.expected_time_seconds == 30
        assert question.difficulty == "medium"

    def test_create_attempt(self, db):
        _, node, student, question = self._make_fixtures(db)
        attempt = Attempt(
            student_id=student.id,
            question_id=question.id,
            node_id=node.id,
            answer="B",
            is_correct=True,
            response_time_seconds=12.5,
            attempt_context="quiz",
        )
        db.add(attempt)
        db.flush()
        assert attempt.id is not None
        assert attempt.is_correct is True
        assert attempt.response_time_seconds == 12.5
