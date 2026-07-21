"""alter phone column typo

Revision ID: 1c04e1063e0f
Revises: 0b02eea74bd3
Create Date: 2026-07-20 15:30:55.337835

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c04e1063e0f'
down_revision: Union[str, Sequence[str], None] = '0b02eea74bd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "preferences",
        column_name="Phone",
        new_column_name="phone",
    )


def downgrade() -> None:
    """Downgrade schema."""
    pass
