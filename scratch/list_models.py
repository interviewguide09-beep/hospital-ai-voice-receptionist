import asyncio
import httpx
from app.core.config import settings

async def list_models():
    api_key = settings.GEMINI_API_KEY
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    print(f"Connecting to Google Gemini API to list models...")
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url)
            data = res.json()
            if "models" in data:
                print("Available models:")
                for m in data["models"]:
                    name = m.get("name")
                    methods = m.get("supportedGenerationMethods", [])
                    if "bidiGenerateContent" in methods:
                        print(f"  [LIVE SUPPORTED] {name}")
            else:
                print("Response data:", data)
        except Exception as e:
            print("Error listing models:", str(e))

if __name__ == "__main__":
    asyncio.run(list_models())
