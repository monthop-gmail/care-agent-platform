FROM python:3.12-slim

ARG PSTACK_REF=v0.3.1

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# ดึง pstack ตาม tag ที่ pin — ห้ามแก้โค้ด pstack ใน repo นี้ (ADR-0002)
RUN git clone --depth 1 --branch "${PSTACK_REF}" \
        https://github.com/willpower-institute/pstack.git /app \
    && rm -rf /app/.git

WORKDIR /app
RUN pip install --no-cache-dir .

# dependency เพิ่มเติมของ app repo นี้
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# addons ของ care-agent-platform (PSTACK_ADDONS_PATHS=addons,care_addons)
COPY care_addons /app/care_addons

# config ที่โค้ดอ่านตอน runtime — ขาดไปแล้ว policy engine จะพังตอนมีงานเข้า ไม่ใช่ตอน boot
# (มีเทสกันไว้ที่ tests/test_architecture_rules.py)
COPY policies /app/policies
COPY profiles /app/profiles

# conformance เข้า image ด้วย เพราะ db_role_check ต้องรันจาก "ในเครือข่ายเดียวกับ DB"
# ซึ่ง compose ไม่ได้ expose port ของ db ออกนอก — ผู้ดูแลจึงรันจาก checkout บนเครื่องตัวเองไม่ได้
#
# ⚠️ ใน container รันได้เฉพาะ db_role_check.py และ drift_check.py (อ่านอย่างเดียว)
#    migration/payload/rls check เริ่มด้วย DROP SCHEMA public CASCADE — มันปฏิเสธตัวเอง
#    ถ้าไม่ได้ตั้ง CONFORMANCE_ALLOW_DESTRUCTIVE=1 (ดู conformance/_guard.py)
COPY conformance /app/conformance

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
