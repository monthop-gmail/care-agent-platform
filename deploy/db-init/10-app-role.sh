#!/bin/sh
# สร้าง role ที่แอปใช้ต่อ DB แบบ NOSUPERUSER
#
# ทำไมต้องมีไฟล์นี้: image `postgres` สร้าง user ที่ระบุใน POSTGRES_USER เป็น **superuser**
# เสมอ และ **RLS ถูก bypass เสมอโดย superuser** — `FORCE ROW LEVEL SECURITY` คุมได้แค่
# table owner ไม่ได้คุม superuser ดังนั้นถ้าแอปต่อ DB ด้วย POSTGRES_USER โดยตรง
# tenant isolation ชั้น DB จะไม่ทำงานเลยโดยไม่มี error ให้เห็น
# (ดู MODULE_GUIDE §9 ของ pstack และ care-agent-platform#1)
#
# POSTGRES_USER จึงเป็น superuser สำหรับ bootstrap เท่านั้น ส่วนแอปใช้ APP_DB_USER
# ซึ่งเป็นเจ้าของ schema ได้ (FORCE คุม owner อยู่แล้ว) แต่ต้องไม่เป็น superuser
#
# ⚠️ สคริปต์นี้รันเฉพาะตอน initdb ครั้งแรกเท่านั้น (pgdata ว่าง)
#    volume ที่มีข้อมูลอยู่แล้วต้องรัน SQL เดียวกันด้วยมือครั้งเดียว — ดู README หัวข้อ
#    "ย้าย deployment เดิมมาใช้ role ที่ไม่ใช่ superuser"
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
	CREATE ROLE "$APP_DB_USER" LOGIN PASSWORD '$APP_DB_PASSWORD'
	    NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
	ALTER DATABASE "$POSTGRES_DB" OWNER TO "$APP_DB_USER";
	ALTER SCHEMA public OWNER TO "$APP_DB_USER";
	GRANT ALL ON SCHEMA public TO "$APP_DB_USER";
SQL

echo "สร้าง role '$APP_DB_USER' (NOSUPERUSER NOBYPASSRLS) และโอน ownership ของ $POSTGRES_DB แล้ว"
