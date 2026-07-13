import socket
import urllib.request
import urllib.error

domain = "hospital-ai-voice-receptionist-production.up.railway.app"
try:
    ip = socket.gethostbyname(domain)
    print(f"DNS Resolution: {domain} resolves to {ip}")
    
    # Try fetching the docs page
    url = f"https://{domain}/docs"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        print(f"HTTP Status: {response.status}")
except socket.gaierror:
    print(f"DNS Resolution Failed: Could not resolve {domain}")
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code} - {e.reason}")
except Exception as e:
    print(f"Other Error: {str(e)}")
