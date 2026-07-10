import asyncio
from datetime import date, time, datetime, timedelta
from sqlalchemy import select
from app.database.session import async_session_factory
from app.database.base import Base
from app.database.models.appointment import Hospital, Department, Doctor, DoctorSchedule, WorkingHour
from app.database.models.conversation import FAQ, DoctorAvailabilityCache

async def seed_data():
    print("Starting database seeding...")
    async with async_session_factory() as db:
        # 1. Seed Hospital
        hospital_stmt = select(Hospital).where(Hospital.id == "hosp_default")
        hospital = (await db.execute(hospital_stmt)).scalar_one_or_none()
        
        if not hospital:
            hospital = Hospital(
                id="hosp_default",
                name="St. Mary General Hospital",
                slug="st-mary-hospital",
                phone="+919532399202",
                email="contact@stmary.com",
                timezone="Asia/Kolkata",
                is_active=True
            )
            db.add(hospital)
            await db.flush()
            print("Default Hospital seeded.")
        else:
            print("Hospital already exists.")

        # 2. Seed Working Hours (Monday to Saturday, 9 AM to 5 PM)
        for day in range(1, 7):
            wh_stmt = select(WorkingHour).where(WorkingHour.hospital_id == hospital.id, WorkingHour.day_of_week == day)
            wh = (await db.execute(wh_stmt)).scalar_one_or_none()
            if not wh:
                wh = WorkingHour(
                    id=f"wh_{day}",
                    hospital_id=hospital.id,
                    day_of_week=day,
                    open_time=time(9, 0),
                    close_time=time(17, 0),
                    is_closed=False
                )
                db.add(wh)
        await db.flush()
        print("Hospital Working Hours seeded.")

        # 3. Seed Departments (General Physician, Cardiology)
        dept_gp_stmt = select(Department).where(Department.name == "General Physician")
        dept_gp = (await db.execute(dept_gp_stmt)).scalar_one_or_none()
        if not dept_gp:
            dept_gp = Department(
                id="dept_gp",
                hospital_id=hospital.id,
                name="General Physician",
                description="General Medicine and Primary Care",
                is_active=True
            )
            db.add(dept_gp)
        
        dept_cardio_stmt = select(Department).where(Department.name == "Cardiology")
        dept_cardio = (await db.execute(dept_cardio_stmt)).scalar_one_or_none()
        if not dept_cardio:
            dept_cardio = Department(
                id="dept_cardio",
                hospital_id=hospital.id,
                name="Cardiology",
                description="Heart and Cardiovascular Care",
                is_active=True
            )
            db.add(dept_cardio)
        await db.flush()
        print("Departments seeded.")

        # 4. Seed Doctors
        doc_sharma_stmt = select(Doctor).where(Doctor.id == "doc_sharma")
        doc_sharma = (await db.execute(doc_sharma_stmt)).scalar_one_or_none()
        if not doc_sharma:
            doc_sharma = Doctor(
                id="doc_sharma",
                hospital_id=hospital.id,
                department_id=dept_gp.id,
                first_name="Ramesh",
                last_name="Sharma",
                email="ramesh.sharma@stmary.com",
                phone="+919999999999",
                license_number="MC12345",
                is_active=True
            )
            db.add(doc_sharma)

        doc_verma_stmt = select(Doctor).where(Doctor.id == "doc_verma")
        doc_verma = (await db.execute(doc_verma_stmt)).scalar_one_or_none()
        if not doc_verma:
            doc_verma = Doctor(
                id="doc_verma",
                hospital_id=hospital.id,
                department_id=dept_cardio.id,
                first_name="Sunil",
                last_name="Verma",
                email="sunil.verma@stmary.com",
                phone="+918888888888",
                license_number="MC67890",
                is_active=True
            )
            db.add(doc_verma)
        await db.flush()
        print("Doctors seeded.")

        # 5. Seed Doctor Schedules (Monday, Wednesday, Friday: 10 AM to 12 PM)
        for doc_id in ["doc_sharma", "doc_verma"]:
            for day in [1, 3, 5]:
                sched_stmt = select(DoctorSchedule).where(
                    DoctorSchedule.doctor_id == doc_id,
                    DoctorSchedule.day_of_week == day
                )
                sched = (await db.execute(sched_stmt)).scalar_one_or_none()
                if not sched:
                    sched = DoctorSchedule(
                        id=f"sched_{doc_id}_{day}",
                        doctor_id=doc_id,
                        day_of_week=day,
                        start_time=time(10, 0),
                        end_time=time(12, 0),
                        slot_duration_minutes=30
                    )
                    db.add(sched)
        await db.flush()
        print("Doctor Schedules seeded.")

        # 6. Seed Doctor Availability Cache for next 7 days
        today = date.today()
        for idx in range(7):
            target_date = today + timedelta(days=idx)
            day_of_week = target_date.isoweekday()  # 1=Monday, 7=Sunday
            if day_of_week in [1, 3, 5]:  # Mon, Wed, Fri
                for doc_id in ["doc_sharma", "doc_verma"]:
                    # Create 4 slots: 10:00, 10:30, 11:00, 11:30
                    slots = [
                        (time(10, 0), time(10, 30)),
                        (time(10, 30), time(11, 0)),
                        (time(11, 0), time(11, 30)),
                        (time(11, 30), time(12, 0))
                    ]
                    for idx_slot, (start, end) in enumerate(slots):
                        cache_stmt = select(DoctorAvailabilityCache).where(
                            DoctorAvailabilityCache.doctor_id == doc_id,
                            DoctorAvailabilityCache.available_date == target_date,
                            DoctorAvailabilityCache.slot_start_time == start
                        )
                        cache = (await db.execute(cache_stmt)).scalar_one_or_none()
                        if not cache:
                            cache = DoctorAvailabilityCache(
                                id=f"cache_{doc_id}_{target_date}_{idx_slot}",
                                doctor_id=doc_id,
                                available_date=target_date,
                                slot_start_time=start,
                                slot_end_time=end,
                                is_booked=False
                            )
                            db.add(cache)
        await db.flush()
        print("Doctor Availability Cache seeded.")

        # 7. Seed FAQs
        faq_stmt = select(FAQ).where(FAQ.hospital_id == hospital.id)
        faq_exists = (await db.execute(faq_stmt)).first()
        if not faq_exists:
            faqs = [
                FAQ(id="faq_1", hospital_id=hospital.id, question="What are hospital hours?", answer="Hospital open hours are Monday to Saturday, 9 AM to 5 PM. Emergency is open 24/7.", category="General"),
                FAQ(id="faq_2", hospital_id=hospital.id, question="Is parking available?", answer="Yes, free parking is available inside the hospital premises.", category="General")
            ]
            db.add_all(faqs)
        
        await db.commit()
        print("Database seeding completed successfully!")

if __name__ == "__main__":
    asyncio.run(seed_data())
