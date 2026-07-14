import asyncio
from datetime import date, time, datetime, timedelta
from sqlalchemy import select, delete
from app.database.session import async_session_factory
from app.database.base import Base
from app.database.models.appointment import Hospital, Department, Doctor, DoctorSchedule, WorkingHour
from app.database.models.conversation import FAQ, DoctorAvailabilityCache
from app.core.config import settings

async def seed_cp_tiwari():
    print("Starting CP Tiwari Hospital database seeding...")
    
    # We resolve the hospital phone number dynamically from Twilio phone number config
    twilio_number = settings.TWILIO_PHONE_NUMBER or "+919532399202"
    
    async with async_session_factory() as db:
        # 1. Seed Hospital
        hospital_stmt = select(Hospital).where(Hospital.id == "hosp_default")
        hospital = (await db.execute(hospital_stmt)).scalar_one_or_none()
        
        if not hospital:
            hospital = Hospital(
                id="hosp_default",
                name="CP Tiwari Hospital",
                slug="cp-tiwari-hospital",
                phone=twilio_number,
                email="contact@cptiwarihospital.com",
                timezone="Asia/Kolkata",
                is_active=True
            )
            db.add(hospital)
            await db.flush()
            print(f"Hospital 'CP Tiwari Hospital' seeded with phone {twilio_number}.")
        else:
            hospital.name = "CP Tiwari Hospital"
            hospital.slug = "cp-tiwari-hospital"
            hospital.phone = twilio_number
            await db.flush()
            print(f"Updated existing hospital name to 'CP Tiwari Hospital' with phone {twilio_number}.")

        # 2. Seed Working Hours (Monday to Friday, 10 AM to 5 PM)
        for day in range(1, 6): # Monday=1, Friday=5
            wh_stmt = select(WorkingHour).where(WorkingHour.hospital_id == hospital.id, WorkingHour.day_of_week == day)
            wh = (await db.execute(wh_stmt)).scalar_one_or_none()
            if not wh:
                wh = WorkingHour(
                    id=f"wh_cp_{day}",
                    hospital_id=hospital.id,
                    day_of_week=day,
                    open_time=time(10, 0),
                    close_time=time(17, 0),
                    is_closed=False
                )
                db.add(wh)
        await db.flush()
        print("Hospital Working Hours (Mon-Fri) seeded.")

        # 3. Seed Departments (Orthopedic, Cardiology, Ophthalmology)
        depts_data = {
            "dept_ortho": ("Orthopedics (Haddi)", "Bone, Joint, and Fracture Care"),
            "dept_cardio": ("Cardiology (Heart)", "Heart and Cardiovascular Specialist Care"),
            "dept_eye": ("Ophthalmology (Eye)", "Eye Clinic and Vision Care Specialist")
        }
        
        seeded_depts = {}
        for dept_id, (name, desc) in depts_data.items():
            dept_stmt = select(Department).where(Department.id == dept_id)
            dept = (await db.execute(dept_stmt)).scalar_one_or_none()
            if not dept:
                dept = Department(
                    id=dept_id,
                    hospital_id=hospital.id,
                    name=name,
                    description=desc,
                    is_active=True
                )
                db.add(dept)
            else:
                dept.name = name
                dept.description = desc
            seeded_depts[dept_id] = dept
        await db.flush()
        print("Departments (Orthopedic, Cardiology, Ophthalmology) seeded.")

        # 4. Seed Doctors (One specialist doctor per department)
        docs_data = {
            "doc_ortho": ("Alok", "Tiwari", "dept_ortho", "alok.tiwari@cptiwari.com", "MC-ORTHO-111"),
            "doc_cardio": ("C. P.", "Tiwari", "dept_cardio", "cp.tiwari@cptiwari.com", "MC-CARDIO-222"),
            "doc_eye": ("R. K.", "Tiwari", "dept_eye", "rk.tiwari@cptiwari.com", "MC-EYE-333")
        }
        
        for doc_id, (first, last, dept_id, email, license_num) in docs_data.items():
            doc_stmt = select(Doctor).where(Doctor.id == doc_id)
            doc = (await db.execute(doc_stmt)).scalar_one_or_none()
            if not doc:
                doc = Doctor(
                    id=doc_id,
                    hospital_id=hospital.id,
                    department_id=dept_id,
                    first_name=first,
                    last_name=last,
                    email=email,
                    phone="+919999999999",
                    license_number=license_num,
                    is_active=True
                )
                db.add(doc)
            else:
                doc.first_name = first
                doc.last_name = last
                doc.department_id = dept_id
        await db.flush()
        print("Doctors (Dr. Alok Tiwari, Dr. C. P. Tiwari, Dr. R. K. Tiwari) seeded.")

        # 5. Seed Doctor Schedules (Monday to Friday, 2 shifts: 10 AM-1 PM and 2 PM-5 PM)
        for doc_id in docs_data.keys():
            for day in range(1, 6):
                # Shift 1: 10:00 to 13:00
                sched1_stmt = select(DoctorSchedule).where(
                    DoctorSchedule.doctor_id == doc_id,
                    DoctorSchedule.day_of_week == day,
                    DoctorSchedule.start_time == time(10, 0)
                )
                sched1 = (await db.execute(sched1_stmt)).scalar_one_or_none()
                if not sched1:
                    sched1 = DoctorSchedule(
                        id=f"sched_{doc_id}_{day}_s1",
                        doctor_id=doc_id,
                        day_of_week=day,
                        start_time=time(10, 0),
                        end_time=time(13, 0),
                        slot_duration_minutes=5 # 5 minutes per slot!
                    )
                    db.add(sched1)

                # Shift 2: 14:00 to 17:00
                sched2_stmt = select(DoctorSchedule).where(
                    DoctorSchedule.doctor_id == doc_id,
                    DoctorSchedule.day_of_week == day,
                    DoctorSchedule.start_time == time(14, 0)
                )
                sched2 = (await db.execute(sched2_stmt)).scalar_one_or_none()
                if not sched2:
                    sched2 = DoctorSchedule(
                        id=f"sched_{doc_id}_{day}_s2",
                        doctor_id=doc_id,
                        day_of_week=day,
                        start_time=time(14, 0),
                        end_time=time(17, 0),
                        slot_duration_minutes=5 # 5 minutes per slot!
                    )
                    db.add(sched2)
        await db.flush()
        print("Doctor Schedules (Mon-Fri, 2 Shifts: 10 AM-1 PM & 2 PM-5 PM, 5-minute slots) seeded.")

        await db.execute(delete(DoctorAvailabilityCache))
        await db.flush()
        
        today = date.today()
        tomorrow = today + timedelta(days=1)
        
        print("Generating availability cache slots...")
        cache_slots_to_add = []
        for target_date in [today, tomorrow]:
            day_of_week = target_date.isoweekday()  # 1=Monday, 5=Friday, 6=Saturday, 7=Sunday
            
            # Seed only if target date falls on Monday to Friday
            if 1 <= day_of_week <= 5:
                # Generate 5-minute slots for Shift 1 (10:00 to 13:00)
                shift1_slots = []
                current = datetime.combine(target_date, time(10, 0))
                end_limit = datetime.combine(target_date, time(13, 0))
                while current < end_limit:
                    next_slot = current + timedelta(minutes=5)
                    shift1_slots.append((current.time(), next_slot.time()))
                    current = next_slot
                
                # Generate 5-minute slots for Shift 2 (14:00 to 17:00)
                shift2_slots = []
                current = datetime.combine(target_date, time(14, 0))
                end_limit = datetime.combine(target_date, time(17, 0))
                while current < end_limit:
                    next_slot = current + timedelta(minutes=5)
                    shift2_slots.append((current.time(), next_slot.time()))
                    current = next_slot
                
                all_day_slots = shift1_slots + shift2_slots
                
                for doc_id in docs_data.keys():
                    for idx, (start, end) in enumerate(all_day_slots):
                        cache = DoctorAvailabilityCache(
                            id=f"cache_{doc_id}_{target_date}_{start.hour}_{start.minute}",
                            doctor_id=doc_id,
                            available_date=target_date,
                            slot_start_time=start,
                            slot_end_time=end,
                            is_booked=False
                        )
                        cache_slots_to_add.append(cache)
        
        if cache_slots_to_add:
            db.add_all(cache_slots_to_add)
        await db.flush()
        print("Doctor Availability Cache slots for Today & Tomorrow seeded.")

        # 7. Seed FAQs customized for CP Tiwari Hospital
        faq_stmt = select(FAQ).where(FAQ.hospital_id == hospital.id)
        faq_exists = (await db.execute(faq_stmt)).first()
        if not faq_exists:
            faqs = [
                FAQ(id="faq_cp_1", hospital_id=hospital.id, question="What are CP Tiwari Hospital hours?", answer="CP Tiwari Hospital is open Monday to Friday, 10:00 AM to 5:00 PM. Emergency service is available 24/7.", category="General"),
                FAQ(id="faq_cp_2", hospital_id=hospital.id, question="Which doctors sit in CP Tiwari Hospital?", answer="Dr. Alok Tiwari (Orthopedics/Haddi), Dr. C. P. Tiwari (Cardiology/Heart), and Dr. R. K. Tiwari (Ophthalmology/Eye).", category="Doctors")
            ]
            db.add_all(faqs)
        
        await db.commit()
        print("CP Tiwari Hospital database seeding completed successfully!")

if __name__ == "__main__":
    asyncio.run(seed_cp_tiwari())
