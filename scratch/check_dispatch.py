import os

def search_service():
    print("Searching for AutomationService in codebase...")
    for root, dirs, files in os.walk("app"):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if "AutomationService" in content:
                        print(f"Found in: {path}")

if __name__ == "__main__":
    search_service()
