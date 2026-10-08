import urllib.request
import json

for n in [63, 64]:
    try:
        url = f"https://api.github.com/repos/Ratnesh-101/compass/pulls/{n}"
        req = urllib.request.Request(url, headers={"User-Agent": "CompassPRCheck"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"=== PR #{n} ===")
            print(f"Title: {data.get('title')}")
            print(f"User: {data.get('user', {}).get('login')}")
            print(f"State: {data.get('state')}")
            print(f"Base: {data.get('base', {}).get('ref')} ({data.get('base', {}).get('sha')[:8]})")
            print(f"Head: {data.get('head', {}).get('ref')} ({data.get('head', {}).get('sha')[:8]})")
            print(f"Mergeable: {data.get('mergeable')} (state: {data.get('mergeable_state')})")
            print(f"Draft: {data.get('draft')}")
            print(f"Body: {data.get('body')}")
            print()
    except Exception as e:
        print(f"Error checking PR #{n}: {e}")
