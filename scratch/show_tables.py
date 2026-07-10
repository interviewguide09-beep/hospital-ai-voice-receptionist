import asyncio
from sqlalchemy import text
from app.database.session import async_session_factory

async def show_tables():
    async with async_session_factory() as db:
        res = await db.execute(text("SHOW TABLES;"))
        tables = [row[0] for row in res.fetchall()]
        print(f"Current tables in database: {tables}")

if __name__ == "__main__":
    asyncio.run(show_tables())
