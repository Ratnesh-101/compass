import urllib.request
import json

checks = [
    (63, "097d0f6654fd5025cafd2bd61323a046e5aad739"),
    (64, "48a00590c8b5d1c7a8f277faca24739d7facaadc"),
    ("main", "993a72362aa04b1e2bbb96dc61d9fcd7f5d789da")
]

for n, sha in checks:
    try:
        url = f"https://api.github.com/repos/Ratnesh-101/compass/commits/{sha}/check-runs"
        req = urllib.request.Request(url, headers={"User-Agent": "CompassCheck", "Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"=== PR #{n} Checks ({data.get('total_count')} total) ===")
            for cr in data.get("check_runs", []):
                print(f"  {cr.get('name')}: status={cr.get('status')}, conclusion={cr.get('conclusion')}")
    except Exception as e:
        print(f"Error fetching checks for PR #{n}: {e}")
