"""medication: provenance ขององค์กรต้นทาง

Revision ID: 0003_medication_provenance
Revises: rls_care_medication
Create Date: 2026-08-20

"hospital_document" ที่ไม่บอกว่าโรงพยาบาลไหน คือคำที่ใครพิมพ์ก็ได้เพื่อให้ดูน่าเชื่อถือขึ้น
(ADR-0010 ข้อ 7) · แถวเดิมได้ NULL ซึ่งตรงกับความจริงว่าตอนนั้นเรายังไม่ได้เก็บ
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_medication_provenance"
down_revision = "rls_care_medication"
branch_labels = None
depends_on = None

TABLE = "care_medication_version"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("source_organization_id", sa.String(63), nullable=True))
    op.add_column(TABLE, sa.Column("source_document_ref", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, "source_document_ref")
    op.drop_column(TABLE, "source_organization_id")
