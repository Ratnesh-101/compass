import os
import json
import urllib.request
import dotenv

dotenv.load_dotenv()
api_key = os.environ.get("NEBIUS_API_KEY", "")
configured_base = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1").rstrip("/")

endpoints = [
    configured_base,
    "https://api.studio.nebius.ai/v1",
    "https://api.tokenfactory.nebius.com/v1",
]

# De-duplicate endpoints
seen = set()
unique_endpoints = []
for ep in endpoints:
    if ep not in seen:
        seen.add(ep)
        unique_endpoints.append(ep)

for ep in unique_endpoints:
    print("\n=======================================================")
    print(f"Testing Endpoint: {ep}")
    print("=======================================================")
    # GET /models
    req = urllib.request.Request(
        f"{ep}/models",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw_body = resp.read().decode()
            status = resp.status
            data = json.loads(raw_body)
            models = [m["id"] for m in data.get("data", [])]
            print(f"GET {ep}/models -> HTTP {status}")
            print(f"Total model count: {len(models)}")
            print("Model IDs:")
            for m in models:
                print(f"  - {m}")
    except urllib.error.HTTPError as e:
        print(f"GET {ep}/models -> HTTP {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"GET {ep}/models -> Error: {e}")

# Call POST /embeddings for configured base
print("\n=======================================================")
print(f"Calling POST /embeddings on configured base: {configured_base}")
print("=======================================================")
emb_payload = json.dumps({
    "input": "Compass semantic vector dimension verification",
    "model": "Qwen/Qwen3-Embedding-8B",
    "dimensions": 768
}).encode("utf-8")

emb_req = urllib.request.Request(
    f"{configured_base}/embeddings",
    data=emb_payload,
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
)
try:
    with urllib.request.urlopen(emb_req) as resp:
        raw_body = resp.read().decode()
        status = resp.status
        data = json.loads(raw_body)
        vec = data["data"][0]["embedding"]
        print(f"POST {configured_base}/embeddings -> HTTP {status}")
        print(f"Model returned: {data.get('model')}")
        print(f"Vector length: {len(vec)}")
        print(f"Vector preview (first 5): {vec[:5]}")
        print(f"Matches pgvector column VECTOR(768): {len(vec) == 768}")
except urllib.error.HTTPError as e:
    print(f"POST /embeddings -> HTTP {e.code}: {e.read().decode()}")
except Exception as e:
    print(f"POST /embeddings -> Error: {e}")
