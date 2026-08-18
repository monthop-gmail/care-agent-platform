# Patient Lifecycle

## 1. Provisioning

```
สร้าง Tenant (ครอบครัว / คลินิก / โรงพยาบาล)
      ↓
สร้าง Patient
      ↓
Care Profile  ← เปิด/ปิดความสามารถทีละอย่าง (ไม่ใช่ทุกคนต้องใช้ครบ)
      ↓
ผูก Caregiver + ให้ consent ทีละ scope
      ↓
ใส่ Routine / Medication / Appointment
      ↓
เลือกช่องทาง (LINE / app / เสียง)
      ↓
Care Agent เริ่มทำงาน
```

Care Profile เป็น config ไม่ใช่โค้ด — คนหนึ่งอาจเปิดแค่ `medication` + `appointment`
อีกคนเปิดครบ อีกคนเป็นผู้สูงอายุที่ไม่มีภาวะความจำเสื่อมเลยก็ใช้ได้

```yaml
care_profile:
  routine: true
  medication: true
  appointment: true
  nutrition: false
  safety: false
  memory_assistance: true
  caregiver_escalation: true
```

> ระบบนี้ไม่ใช่ "Dementia Agent" — เป็น Care Agent ที่ปรับตามคน

## 2. วันปกติ

```
06:45  ตื่น
       └→ Orientation: วันนี้วันอะไร อยู่ไหน วันนี้ต้องทำอะไร
07:00  ยาก่อนอาหาร  → reminder → ยืนยัน
07:30  อาหารเช้า    → reminder → ยืนยัน
08:00  ยาหลังอาหาร  → reminder → เงียบ → เตือนซ้ำ → ถาม → missed → caregiver
10:00  care plan: เดิน 20 นาที (คำสั่งหมอ)
12:00  มื้อกลางวัน
...
20:00  ยาก่อนนอน
21:00  Daily setup พรุ่งนี้ (มีนัดไหม ต้องเตรียมอะไร)
```

## 3. รอบการพบหมอ (วงจรที่ยาวที่สุดในระบบ)

```
ระหว่างวัน  บันทึกอาการ + คำถามที่อยากถามหมอ   (care_journal)
     ↓
ก่อนนัด 1 วัน  แจ้ง + เตรียมเอกสาร/เสื้อผ้า      (care_appt_prep)
     ↓
เช้าวันนัด   preparation checklist ทีละขั้น
     ↓
ก่อนออกจากบ้าน  ตรวจของ / บัตร / ยา
     ↓
พบหมอ        visit brief: อาการที่บันทึก + คำถาม + สรุปยาปัจจุบัน
     ↓
หลังพบหมอ    คำสั่งใหม่ → proposal → คนยืนยัน → medication version ใหม่ + care plan ใหม่
     ↓
วันถัดไป     คำสั่งหมอกลายเป็น task ประจำวันอัตโนมัติ
```

จุดที่ต้องระวังที่สุดคือขั้น "หลังพบหมอ" — **agent ห้ามแก้ยาเอง**
([ADR-0006](../decisions/0006-ai-has-no-medical-authority.md))

## 4. Care Timeline

ทุกอย่างข้างบนไปรวมที่ timeline เดียวต่อผู้ป่วยหนึ่งคน ทำให้ระบบเปลี่ยนจาก
calendar reminder เป็น workflow engine สำหรับชีวิตจริง

```
18 ส.ค.  18:00 เตือนนัดพรุ่งนี้ · 20:00 ตรวจ preparation
19 ส.ค.  06:00 ตื่น · 06:15 แต่งตัว · 06:30 เอกสาร · 07:00 รถ · 08:00 ตรวจเลือด
```

## 5. การถอนตัว

ถอน consent · ปิด care profile · ลบข้อมูลตาม PDPA
— **audit event ลบไม่ได้** (append-only) แต่ต้องลบข้อมูลส่วนบุคคลที่อ้างถึงได้
วิธีจัดการเรื่องนี้ต้องมี ADR แยกก่อนถึง M6
