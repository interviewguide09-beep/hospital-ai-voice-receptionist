import os

def search_files():
    root_dir = "c:/Users/shiva/Desktop/AAA"
    keywords = ["MYSQL", "railway", "hayabusa", "proxy", "21536"]
    for dirpath, _, filenames in os.walk(root_dir):
        # Skip virtualenvs or cache dirs
        if any(x in dirpath for x in ["venv", ".git", "__pycache__", ".gemini", "scratch"]):
            continue
        for f in filenames:
            if f.endswith((".py", ".env", ".example", ".ini", ".md")):
                filepath = os.path.join(dirpath, f)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as file:
                        content = file.read()
                        for kw in keywords:
                            if kw in content:
                                print(f"Found keyword '{kw}' in file: {filepath}")
                except Exception as e:
                    pass

if __name__ == "__main__":
    search_files()
