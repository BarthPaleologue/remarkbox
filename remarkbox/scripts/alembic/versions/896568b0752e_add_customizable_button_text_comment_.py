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


def _column_exists(table, column):
    """Check if a column exists in a SQLite table."""
    conn = op.get_bind()
    result = conn.execute(sa.text("PRAGMA table_info('{}')".format(table)))
    return any(row[1] == column for row in result)


def upgrade():
    # T4: customizable button text and comment labels
    if not _column_exists('rb_namespace', 'submit_button_text'):
        op.add_column('rb_namespace', sa.Column('submit_button_text', sa.Unicode(length=256), nullable=True))
    if not _column_exists('rb_namespace', 'comment_label_singular'):
        op.add_column('rb_namespace', sa.Column('comment_label_singular', sa.Unicode(length=256), nullable=True))
    if not _column_exists('rb_namespace', 'comment_label_plural'):
        op.add_column('rb_namespace', sa.Column('comment_label_plural', sa.Unicode(length=256), nullable=True))
    # T8: nesting depth settings
    if not _column_exists('rb_namespace', 'max_nesting_depth'):
        op.add_column('rb_namespace', sa.Column('max_nesting_depth', sa.Integer(), nullable=True))
    if not _column_exists('rb_namespace', 'collapse_depth'):
        op.add_column('rb_namespace', sa.Column('collapse_depth', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('rb_namespace', 'collapse_depth')
    op.drop_column('rb_namespace', 'max_nesting_depth')
    op.drop_column('rb_namespace', 'comment_label_plural')
    op.drop_column('rb_namespace', 'comment_label_singular')
    op.drop_column('rb_namespace', 'submit_button_text')
