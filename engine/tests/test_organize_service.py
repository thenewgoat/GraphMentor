"""Tests for OrganizeService CREATE_GROUP and DISSOLVE_GROUP apply logic."""
from app.models.course import Course
from app.models.node import Node, NodeEdge
from app.services.organize_service import OrganizeService


def _make_course(db):
    course = Course(title="Organize Test", ingestion_status="graph_ready")
    db.add(course)
    db.flush()
    return course


class TestCreateGroup:
    def test_create_group_adds_group_node(self, db):
        course = _make_course(db)
        n1 = Node(course_id=course.id, title="A", depth=2, order_index=0)
        n2 = Node(course_id=course.id, title="B", depth=2, order_index=1)
        db.add_all([n1, n2])
        db.flush()

        service = OrganizeService(db=db, openai_api_key="fake")
        suggestions = [{
            "id": 0, "type": "CREATE_GROUP",
            "group_title": "AB Group",
            "children": ["A", "B"],
            "node_titles": ["A", "B"],
            "reasoning": "test",
        }]
        result = service.apply(course_id=course.id, suggestion_ids=[0], suggestions=suggestions)
        assert result["applied"] == 1

        group = db.query(Node).filter_by(course_id=course.id, title="AB Group").first()
        assert group is not None
        assert group.node_type == "group"

        # Children should have hierarchy edges from group
        edges = db.query(NodeEdge).filter_by(parent_id=group.id).all()
        assert len(edges) == 2
        assert all(e.edge_category == "hierarchy" for e in edges)
        assert all(e.edge_label == "contains" for e in edges)

    def test_create_group_reparents_children_depth(self, db):
        course = _make_course(db)
        n1 = Node(course_id=course.id, title="A", depth=2, order_index=0)
        db.add(n1)
        db.flush()

        service = OrganizeService(db=db, openai_api_key="fake")
        suggestions = [{
            "id": 0, "type": "CREATE_GROUP",
            "group_title": "G",
            "children": ["A"],
            "node_titles": ["A"],
            "reasoning": "test",
        }]
        service.apply(course_id=course.id, suggestion_ids=[0], suggestions=suggestions)

        db.refresh(n1)
        group = db.query(Node).filter_by(course_id=course.id, title="G").first()
        assert n1.depth == group.depth + 1

    def test_create_group_no_title_returns_zero(self, db):
        course = _make_course(db)
        service = OrganizeService(db=db, openai_api_key="fake")
        suggestions = [{
            "id": 0, "type": "CREATE_GROUP",
            "children": ["A"],
            "node_titles": ["A"],
            "reasoning": "test",
        }]
        result = service.apply(course_id=course.id, suggestion_ids=[0], suggestions=suggestions)
        assert result["applied"] == 0

    def test_create_group_unknown_children_returns_zero(self, db):
        course = _make_course(db)
        service = OrganizeService(db=db, openai_api_key="fake")
        suggestions = [{
            "id": 0, "type": "CREATE_GROUP",
            "group_title": "G",
            "children": ["Nonexistent"],
            "node_titles": ["Nonexistent"],
            "reasoning": "test",
        }]
        result = service.apply(course_id=course.id, suggestion_ids=[0], suggestions=suggestions)
        assert result["applied"] == 0


class TestDissolveGroup:
    def test_dissolve_group_removes_group(self, db):
        course = _make_course(db)
        group = Node(course_id=course.id, title="G", depth=1, order_index=0, node_type="group")
        child = Node(course_id=course.id, title="C", depth=2, order_index=0)
        db.add_all([group, child])
        db.flush()

        db.add(NodeEdge(parent_id=group.id, child_id=child.id, edge_category="hierarchy", edge_label="contains"))
        db.flush()

        service = OrganizeService(db=db, openai_api_key="fake")
        suggestions = [{
            "id": 0, "type": "DISSOLVE_GROUP",
            "node_titles": ["G"],
            "reasoning": "test",
        }]
        result = service.apply(course_id=course.id, suggestion_ids=[0], suggestions=suggestions)
        assert result["applied"] == 1

        assert db.query(Node).filter_by(course_id=course.id, title="G").first() is None

        db.refresh(child)
        assert child.depth == 1

    def test_dissolve_group_transfers_edges(self, db):
        course = _make_course(db)
        external = Node(course_id=course.id, title="E", depth=1, order_index=0)
        group = Node(course_id=course.id, title="G", depth=1, order_index=1, node_type="group")
        child = Node(course_id=course.id, title="C", depth=2, order_index=0)
        db.add_all([external, group, child])
        db.flush()

        # hierarchy edge from group to child
        db.add(NodeEdge(parent_id=group.id, child_id=child.id, edge_category="hierarchy", edge_label="contains"))
        # dependency edge from external to group
        db.add(NodeEdge(parent_id=external.id, child_id=group.id, edge_category="dependency", edge_label="builds upon"))
        db.flush()

        service = OrganizeService(db=db, openai_api_key="fake")
        suggestions = [{
            "id": 0, "type": "DISSOLVE_GROUP",
            "node_titles": ["G"],
            "reasoning": "test",
        }]
        service.apply(course_id=course.id, suggestion_ids=[0], suggestions=suggestions)

        # External -> Child edge should exist (transferred)
        transferred = db.get(NodeEdge, (external.id, child.id))
        assert transferred is not None
        assert transferred.edge_category == "dependency"
        assert transferred.edge_label == "builds upon"

    def test_dissolve_non_group_fails(self, db):
        course = _make_course(db)
        node = Node(course_id=course.id, title="N", depth=1, order_index=0, node_type="concept")
        db.add(node)
        db.flush()

        service = OrganizeService(db=db, openai_api_key="fake")
        suggestions = [{
            "id": 0, "type": "DISSOLVE_GROUP",
            "node_titles": ["N"],
            "reasoning": "test",
        }]
        result = service.apply(course_id=course.id, suggestion_ids=[0], suggestions=suggestions)
        assert result["applied"] == 0
