import asyncio
from sqlalchemy import text
from app.database.session import async_session_factory

async def count():
    async with async_session_factory() as db:
        res_hosp = await db.execute(text("SELECT count(*) FROM hospitals;"))
        count_hosp = res_hosp.scalar()
        res_docs = await db.execute(text("SELECT count(*) FROM doctors;"))
        count_docs = res_docs.scalar()
        res_slots = await db.execute(text("SELECT count(*) FROM doctor_availability_cache;"))
        count_slots = res_slots.scalar()
        print(f"Hospitals: {count_hosp} | Doctors: {count_docs} | Cached Slots: {count_slots}")

if __name__ == "__main__":
    asyncio.run(count())
