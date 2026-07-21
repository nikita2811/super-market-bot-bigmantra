"""add column chat_id to Customer table

Revision ID: 5bb30725c08f
Revises: 6aa8a3f9a194
Create Date: 2026-07-21 08:42:54.666344

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5bb30725c08f'
down_revision: Union[str, Sequence[str], None] = '6aa8a3f9a194'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('customers', sa.Column('chat_id', sa.String(255),nullable=True))


def downgrade() -> None:
 
    pass
