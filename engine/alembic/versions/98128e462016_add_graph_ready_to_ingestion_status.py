"""add graph_ready to ingestion_status

Revision ID: 98128e462016
Revises: 637ce91dc5da
Create Date: 2026-03-02 10:44:58.374294

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '98128e462016'
down_revision: Union[str, Sequence[str], None] = '637ce91dc5da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("chk_ingestion_status", "courses", type_="check")
    op.create_check_constraint(
        "chk_ingestion_status",
        "courses",
        "ingestion_status IN ('pending', 'processing', 'complete', 'failed', 'graph_ready')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("chk_ingestion_status", "courses", type_="check")
    op.create_check_constraint(
        "chk_ingestion_status",
        "courses",
        "ingestion_status IN ('pending', 'processing', 'complete', 'failed')",
    )
