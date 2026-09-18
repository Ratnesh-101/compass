import httpx

gh = httpx.get('https://api.github.com/repos/Ratnesh-101/compass/commits/main').json()
gh_sha = gh.get('sha')
gh_short = gh_sha[:7] if gh_sha else 'unknown'

health = httpx.get('https://compass-backend-qryu.onrender.com/health', timeout=15.0).json()
health_commit = health.get('commit')

print('=' * 75)
print('GITHUB API vs LIVE RENDER HEALTH COMMIT COMPARISON')
print('=' * 75)
print(f'GitHub main HEAD Full SHA : {gh_sha}')
print(f'GitHub main HEAD Short SHA: {gh_short}')
print(f'Live Render /health Commit: {health_commit}')
print(f'Matches Exact Short SHA   : {gh_short == health_commit}')
print('=' * 75)
print('RAW GITHUB COMMIT API DATA:')
print(f'  sha: {gh.get("sha")}')
print(f'  message: {gh.get("commit", {}).get("message", "").splitlines()[0]}')
print(f'  author: {gh.get("commit", {}).get("author", {}).get("name")}')
print(f'  date: {gh.get("commit", {}).get("author", {}).get("date")}')
print('\nRAW LIVE RENDER /health RESPONSE:')
print(f'  {health}')
print('=' * 75)
