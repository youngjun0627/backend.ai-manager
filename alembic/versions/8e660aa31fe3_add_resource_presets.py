"""add-resource-presets

Revision ID: 8e660aa31fe3
Revises: 01456c812164
Create Date: 2019-03-30 01:45:07.525096

"""
from alembic import op
import sqlalchemy as sa
import ai.backend.manager.models.base  # noqa


# revision identifiers, used by Alembic.
revision = '8e660aa31fe3'
down_revision = '01456c812164'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        'resource_presets',
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('resource_slots',
                  ai.backend.manager.models.base.ResourceSlotColumn(),
                  nullable=False),
        sa.PrimaryKeyConstraint('name', name=op.f('pk_resource_presets'))
    )
    # Add initial fixtures for resource presets
    query = '''
    INSERT INTO resource_presets
    VALUES (
        'small',
        '{"cpu":"1","mem":"2147483648"}'::jsonb
    );
    INSERT INTO resource_presets
    VALUES (
        'small-gpu',
        '{"cpu":"1","mem":"2147483648","cuda.device":"1","cuda.shares":"0.5"}'::jsonb
    );
    INSERT INTO resource_presets
    VALUES (
        'medium',
        '{"cpu":"2","mem":"4294967296"}'::jsonb
    );
    INSERT INTO resource_presets
    VALUES (
        'medium-gpu',
        '{"cpu":"2","mem":"4294967296","cuda.device":"1","cuda.shares":"1.0"}'::jsonb
    );
    INSERT INTO resource_presets
    VALUES (
        'large',
        '{"cpu":"4","mem":"8589934592"}'::jsonb
    );
    INSERT INTO resource_presets
    VALUES (
        'large-gpu',
        '{"cpu":"4","mem":"8589934592","cuda.device":"2","cuda.shares":"2.0"}'::jsonb
    );
    '''
    connection = op.get_bind()
    connection.execute(query)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('resource_presets')
    # ### end Alembic commands ###
