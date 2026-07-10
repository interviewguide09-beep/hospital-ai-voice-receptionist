import os

def search_n8n():
    print("Searching for N8N_WEBHOOK_URL in codebase...")
    for root, dirs, files in os.walk("app"):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if "N8N_WEBHOOK_URL" in content:
                        print(f"Found in: {path}")

if __name__ == "__main__":
    search_n8n()
