import asyncio
from sqlalchemy import select, func
from app.database.session import async_session_factory
from app.database.models.appointment import Hospital, Doctor, WorkingHour, DoctorSchedule

async def check_db():
    print("Checking database records...")
    async with async_session_factory() as db:
        try:
            hospitals_count = (await db.execute(select(func.count(Hospital.id)))).scalar()
            doctors_count = (await db.execute(select(func.count(Doctor.id)))).scalar()
            wh_count = (await db.execute(select(func.count(WorkingHour.id)))).scalar()
            sched_count = (await db.execute(select(func.count(DoctorSchedule.id)))).scalar()
            
            print(f"Hospitals: {hospitals_count}")
            print(f"Doctors: {doctors_count}")
            print(f"Working Hours: {wh_count}")
            print(f"Doctor Schedules: {sched_count}")
            
            # Print doctor details
            if doctors_count > 0:
                docs = (await db.execute(select(Doctor))).scalars().all()
                for d in docs:
                    print(f"Doctor: ID={d.id}, Name={d.first_name} {d.last_name}, Active={d.is_active}")
        except Exception as e:
            print(f"Database Query Error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(check_db())
