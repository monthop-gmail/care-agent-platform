"""alembic env — generate โดย pstack อย่าเรียกด้วย alembic CLI ตรงๆ
ใช้ผ่าน `python cli.py makemigration/migrate` เท่านั้น (connection ถูกส่งมาทาง attributes)
"""
from alembic import context

from core.db import Base

config = context.config
module_tables = config.attributes.get("module_tables")


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        if name.startswith("alembic_version"):
            return False
        if module_tables is not None:
            return name in module_tables
    return True


connection = config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    version_table=config.get_main_option("version_table"),
    include_object=include_object,
    render_as_batch=connection.dialect.name == "sqlite",
)
with context.begin_transaction():
    context.run_migrations()
