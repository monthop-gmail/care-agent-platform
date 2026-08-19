"""organization initial — care_organization + care_org_membership

Revision ID: 0001_organization_initial
Revises:
Create Date: 2026-08-20

🔒 ทั้งสองตารางมี tenant_id และเข้า RLS ตามปกติ — องค์กรไม่ใช่ control plane
   และไม่ใช่ทะเบียนกลาง (ADR-0010 ข้อ 2)
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_organization_initial"
down_revision = None
branch_labels = None
depends_on = None

ORG = "care_organization"
MEMBERSHIP = "care_org_membership"


def upgrade() -> None:
    op.create_table(
        ORG,
        sa.Column("organization_id", sa.String(63), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("external_ref", sa.String(128), nullable=True),
        sa.Column("contact", sa.String(255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.JSON(), nullable=True),
    )
    op.create_index("ix_care_organization_tenant_id", ORG, ["tenant_id"])
    op.create_index("ix_care_organization_lookup", ORG, ["tenant_id", "kind"])

    op.create_table(
        MEMBERSHIP,
        sa.Column("membership_id", sa.String(63), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column(
            "organization_id",
            sa.String(63),
            sa.ForeignKey(f"{ORG}.organization_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("principal_type", sa.String(16), nullable=False),
        sa.Column("principal_id", sa.String(63), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("ended_reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_care_org_membership_tenant_id", MEMBERSHIP, ["tenant_id"])
    op.create_index("ix_care_org_membership_organization_id", MEMBERSHIP, ["organization_id"])
    op.create_index("ix_care_org_membership_principal_id", MEMBERSHIP, ["principal_id"])
    op.create_index(
        "ix_care_org_membership_principal", MEMBERSHIP, ["tenant_id", "principal_id", "active"]
    )


def downgrade() -> None:
    op.drop_table(MEMBERSHIP)
    op.drop_table(ORG)
