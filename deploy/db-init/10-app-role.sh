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

# ส่งค่าเข้า psql เป็นตัวแปร แล้วให้ psql quote ให้ (:"ident" กับ :'literal')
# ไม่ประกอบ SQL ด้วยการแทนค่าใน shell — รหัสผ่านที่มี ' หรือ " จะได้ไม่ทำให้สคริปต์พังหรือเพี้ยน
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v approle="$APP_DB_USER" -v apppass="$APP_DB_PASSWORD" -v appdb="$POSTGRES_DB" <<-'SQL'
	CREATE ROLE :"approle" LOGIN PASSWORD :'apppass'
	    NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
	ALTER DATABASE :"appdb" OWNER TO :"approle";
	ALTER SCHEMA public OWNER TO :"approle";
	GRANT ALL ON SCHEMA public TO :"approle";
SQL

echo "สร้าง role '$APP_DB_USER' (NOSUPERUSER NOBYPASSRLS) และโอน ownership ของ $POSTGRES_DB แล้ว"
