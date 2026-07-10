import asyncio
from sqlalchemy import text
from app.database.session import async_session_factory

async def drop_all_tables():
    print("Connecting to database to drop all tables...")
    async with async_session_factory() as db:
        # Disable foreign key checks
        await db.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        
        # Get list of all tables
        res = await db.execute(text("SHOW TABLES;"))
        tables = [row[0] for row in res.fetchall()]
        print(f"Found tables to drop: {tables}")
        
        for table in tables:
            print(f"Dropping table: {table}")
            await db.execute(text(f"DROP TABLE `{table}`;"))
            
        # Re-enable foreign key checks
        await db.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
        await db.commit()
        print("All tables dropped successfully!")

if __name__ == "__main__":
    asyncio.run(drop_all_tables())
