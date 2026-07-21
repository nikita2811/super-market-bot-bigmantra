"""add idempotency_key to account_transactions

Revision ID: 6aa8a3f9a194
Revises: 1c04e1063e0f
Create Date: 2026-07-20 21:06:50.689500

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6aa8a3f9a194'
down_revision: Union[str, Sequence[str], None] = '1c04e1063e0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
   op.add_column("account_transactions", sa.Column("idempotency_key", sa.String(), nullable=True))
   op.create_unique_constraint(
        "uq_account_transactions_idempotency_key", "account_transactions", ["idempotency_key"]
    )


def downgrade() -> None:
    pass
