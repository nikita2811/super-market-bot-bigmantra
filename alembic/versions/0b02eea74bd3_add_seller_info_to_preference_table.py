"""add seller info to preference table

Revision ID: 0b02eea74bd3
Revises: 06af70badf2a
Create Date: 2026-07-20 13:59:19.103146

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0b02eea74bd3'
down_revision: Union[str, Sequence[str], None] = '06af70badf2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('preferences', sa.Column('shop_name', sa.String(255),nullable=True))
    op.add_column('preferences', sa.Column('address', sa.String(255),nullable=True))
    op.add_column('preferences',sa.Column('gstin',sa.String(255),nullable=True))
    op.add_column('preferences',sa.Column('Phone',sa.Integer(),nullable=True))
    
   

def downgrade() -> None:
   
    pass
