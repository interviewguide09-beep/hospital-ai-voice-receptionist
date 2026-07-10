import asyncio
from sqlalchemy.ext.asyncio import create_async_engine

async def test_pwd(pwd: str):
    url = f"mysql+aiomysql://root:{pwd}@66.33.22.223:21536/"
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
            return "SUCCESS", None
    except Exception as e:
        return "FAILED", str(e)
    finally:
        await engine.dispose()

async def main():
    p1 = ["l", "1"]
    p8 = ["O", "0"]
    p14 = ["Q", "O", "0"]
    p15_16 = ["Scuz", "Seuz", "seuz", "scuz"]
    p32 = ["l", "1"]

    print("Starting password search on IP 66.33.22.223...")
    for char1 in p1:
        for char8 in p8:
            for char14 in p14:
                for char15_16 in p15_16:
                    for char32 in p32:
                        pwd = f"{char1}n1pqrK{char8}kRsuR{char14}{char15_16}sghaicgetcBAY{char32}"
                        status, err = await test_pwd(pwd)
                        if status == "SUCCESS":
                            print(f"FOUND WORKING PASSWORD: {pwd}")
                            return
                        else:
                            # Print progress for non-timeout errors
                            if "timeout" not in str(err).lower():
                                print(f"Tested: {pwd} -> {err}")

    print("Search completed. No working password found.")

if __name__ == "__main__":
    asyncio.run(main())
