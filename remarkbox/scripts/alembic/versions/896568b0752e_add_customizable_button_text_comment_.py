"""add customizable button text, comment labels, and nesting depth settings to namespace

Revision ID: 896568b0752e
Revises: a3f7b2c1d4e5
Create Date: 2026-02-01 18:28:50.433155

"""

# revision identifiers, used by Alembic.
revision = '896568b0752e'
down_revision = 'a3f7b2c1d4e5'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    # T4: customizable button text and comment labels
    op.add_column('rb_namespace', sa.Column('submit_button_text', sa.Unicode(length=256), nullable=True))
    op.add_column('rb_namespace', sa.Column('comment_label_singular', sa.Unicode(length=256), nullable=True))
    op.add_column('rb_namespace', sa.Column('comment_label_plural', sa.Unicode(length=256), nullable=True))
    # T8: nesting depth settings
    op.add_column('rb_namespace', sa.Column('max_nesting_depth', sa.Integer(), nullable=True))
    op.add_column('rb_namespace', sa.Column('collapse_depth', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('rb_namespace', 'collapse_depth')
    op.drop_column('rb_namespace', 'max_nesting_depth')
    op.drop_column('rb_namespace', 'comment_label_plural')
    op.drop_column('rb_namespace', 'comment_label_singular')
    op.drop_column('rb_namespace', 'submit_button_text')
