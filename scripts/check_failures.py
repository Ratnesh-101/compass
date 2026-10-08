import urllib.request
import json

url = "https://api.github.com/repos/Ratnesh-101/compass/commits/48a00590c8b5d1c7a8f277faca24739d7facaadc/check-runs"
req = urllib.request.Request(url, headers={"User-Agent": "CompassCheck", "Accept": "application/vnd.github.v3+json"})
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode("utf-8"))
    for cr in data.get("check_runs", []):
        if cr.get("conclusion") == "failure":
            print(f"Check: {cr.get('name')}")
            print(f"  Title: {cr.get('output', {}).get('title')}")
            print(f"  Summary:\n{cr.get('output', {}).get('summary')}")
            print(f"  HTML URL: {cr.get('html_url')}")
            print("-" * 50)
