"""approval initial — ap_approval_request + ap_approval

Revision ID: 0001_approval_initial
Revises:
Create Date: 2026-08-19

🔒 ไม่มี UPDATE path บนตาราง `ap_approval` — decision เป็น immutable ตาม approval/v1
   การเปลี่ยนใจคือแถวใหม่ที่ `supersedes` แถวเดิม ประวัติจึงอ่านย้อนได้เสมอว่าใครเปลี่ยนใจเมื่อไร
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_approval_initial"
down_revision = None
branch_labels = None
depends_on = None

REQUEST = "ap_approval_request"
APPROVAL = "ap_approval"


def upgrade() -> None:
    op.create_table(
        REQUEST,
        sa.Column("request_id", sa.String(63), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("workspace_id", sa.String(63), nullable=True),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("action_risk", sa.String(16), nullable=False),
        sa.Column("authority_required", sa.String(32), nullable=False),
        sa.Column("policy_id", sa.String(64), nullable=False),
        sa.Column("subject_type", sa.String(24), nullable=False),
        sa.Column("subject_id", sa.String(63), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("proposed", sa.JSON(), nullable=True),
        sa.Column("requested_by", sa.JSON(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("correlation_id", sa.String(63), nullable=True),
    )
    op.create_index("ix_ap_approval_request_tenant_id", REQUEST, ["tenant_id"])
    op.create_index("ix_ap_approval_request_capability", REQUEST, ["capability"])
    op.create_index("ix_ap_approval_request_subject_id", REQUEST, ["subject_id"])
    op.create_index("ix_ap_approval_pending", REQUEST, ["tenant_id", "state", "expires_at"])

    op.create_table(
        APPROVAL,
        sa.Column("approval_id", sa.String(63), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("workspace_id", sa.String(63), nullable=True),
        sa.Column(
            "request_id",
            sa.String(63),
            sa.ForeignKey(f"{REQUEST}.request_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_type", sa.String(24), nullable=False),
        sa.Column("subject_id", sa.String(63), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("authority", sa.JSON(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_id", sa.String(64), nullable=True),
        sa.Column("action_risk", sa.String(16), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes", sa.String(63), nullable=True),
    )
    op.create_index("ix_ap_approval_tenant_id", APPROVAL, ["tenant_id"])
    op.create_index("ix_ap_approval_request_id", APPROVAL, ["request_id"])
    op.create_index("ix_ap_approval_subject", APPROVAL, ["tenant_id", "subject_type", "subject_id"])


def downgrade() -> None:
    op.drop_table(APPROVAL)
    op.drop_table(REQUEST)
