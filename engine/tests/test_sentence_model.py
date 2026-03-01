import uuid
import hashlib
from app.models.sentence import Sentence, NodeSentence
from app.models.course import Course
from app.models.node import Node


class TestSentence:
    def test_create_sentence(self, db):
        course = Course(
            title="Test Course",
            source_pdf_path="/tmp/test.pdf",
            source_pdf_hash=hashlib.sha256(b"test").hexdigest(),
            ingestion_status="processing",
        )
        db.add(course)
        db.flush()

        sentence = Sentence(
            course_id=course.id,
            page=1,
            position=0,
            slide_title="Introduction",
            text="This is a test sentence.",
            hash=hashlib.sha256(b"This is a test sentence.").hexdigest(),
        )
        db.add(sentence)
        db.flush()

        assert sentence.id is not None
        assert sentence.page == 1
        assert sentence.position == 0
        assert sentence.slide_title == "Introduction"
        assert sentence.text == "This is a test sentence."

    def test_sentence_cascade_delete(self, db):
        course = Course(
            title="Cascade Course",
            source_pdf_path="/tmp/cascade.pdf",
            source_pdf_hash=hashlib.sha256(b"cascade").hexdigest(),
            ingestion_status="processing",
        )
        db.add(course)
        db.flush()

        sentence = Sentence(
            course_id=course.id,
            page=1,
            position=0,
            text="Cascade test.",
            hash=hashlib.sha256(b"Cascade test.").hexdigest(),
        )
        db.add(sentence)
        db.flush()

        db.delete(course)
        db.flush()

        result = db.query(Sentence).filter_by(course_id=course.id).all()
        assert result == []


class TestNodeSentence:
    def test_create_node_sentence(self, db):
        course = Course(
            title="NS Course",
            source_pdf_path="/tmp/ns.pdf",
            source_pdf_hash=hashlib.sha256(b"ns").hexdigest(),
            ingestion_status="complete",
        )
        db.add(course)
        db.flush()

        node = Node(course_id=course.id, title="Topic A", depth=0, order_index=0)
        sentence = Sentence(
            course_id=course.id,
            page=1,
            position=0,
            text="Node sentence link.",
            hash=hashlib.sha256(b"Node sentence link.").hexdigest(),
        )
        db.add_all([node, sentence])
        db.flush()

        ns = NodeSentence(node_id=node.id, sentence_id=sentence.id)
        db.add(ns)
        db.flush()

        assert ns.node_id == node.id
        assert ns.sentence_id == sentence.id
