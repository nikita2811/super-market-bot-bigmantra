"""add cancel value to billstatus enum

Revision ID: 06af70badf2a
Revises: 349f23a28e9c
Create Date: 2026-07-20 13:22:43.403331

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '06af70badf2a'
down_revision: Union[str, Sequence[str], None] = '349f23a28e9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute("ALTER TYPE billstatus ADD VALUE IF NOT EXISTS 'cancel'")
    


def downgrade() -> None:
    pass
