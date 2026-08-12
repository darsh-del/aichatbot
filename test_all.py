import requests
import json
import time

BASE_URL = "http://localhost:8000"
API_KEY = "i264a4FZs7jFyXxzQ03AZRFbmxE7AtpC2UpFVx--IS4"

def test_language():
    print("Testing Language Support (Russian)...")
    payload = {
        "messages": [{"role": "user", "content": "Привет, расскажите о рафтинге. Какие есть варианты?"}]
    }
    try:
        response = requests.post(f"{BASE_URL}/api/chat", json=payload, stream=True)
        content = ""
        for line in response.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith("data: "):
                    data = json.loads(decoded[6:])
                    if data.get("delta"):
                        content += data["delta"]
        
        print("\nResponse:")
        print(content)
        if any('\u0400' <= c <= '\u04FF' for c in content):
            print("Language Test: PASSED (Russian detected)")
        else:
            print("Language Test: FAILED (No Russian detected)")
    except Exception as e:
        print(f"Language Test Failed with error: {e}")

def test_comparison():
    print("\nTesting Comparison Table...")
    payload = {
        "messages": [{"role": "user", "content": "Compare 12km vs 16km rafting"}]
    }
    try:
        response = requests.post(f"{BASE_URL}/api/chat", json=payload, stream=True)
        content = ""
        for line in response.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith("data: "):
                    data = json.loads(decoded[6:])
                    if data.get("delta"):
                        content += data["delta"]
        
        print("\nResponse:")
        print(content)
        if "|" in content and "-|-" in content.replace(" ", ""):
            print("Comparison Test: PASSED (Markdown table detected)")
        else:
            print("Comparison Test: FAILED (No table detected)")
    except Exception as e:
        print(f"Comparison Test Failed with error: {e}")

def test_dashboard_api():
    print("\nTesting Dashboard API...")
    headers = {"Authorization": f"Bearer {API_KEY}"}
    try:
        response = requests.get(f"{BASE_URL}/api/admin/session-summaries", headers=headers)
        if response.status_code == 200:
            data = response.json()
            print(f"Dashboard API Test: PASSED. Summaries returned: {len(data.get('summaries', []))}")
        else:
            print(f"Dashboard API Test: FAILED. Status: {response.status_code}, Body: {response.text}")
    except Exception as e:
        print(f"Dashboard API Test Failed with error: {e}")

if __name__ == "__main__":
    test_language()
    test_comparison()
    test_dashboard_api()
