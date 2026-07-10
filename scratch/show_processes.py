import asyncio
from sqlalchemy import text
from app.database.session import async_session_factory

async def show_processes():
    async with async_session_factory() as db:
        res = await db.execute(text("SHOW PROCESSLIST;"))
        for row in res.fetchall():
            print(row)

if __name__ == "__main__":
    asyncio.run(show_processes())
