import httpx
import re

r = httpx.get('https://compass-kappa-nine.vercel.app', timeout=15.0)
print('HTML status:', r.status_code)
scripts = re.findall(r'src=["\']([^"\']+\.js)["\']', r.text)
print('Script tags found:', scripts)

for s in scripts:
    url = s if s.startswith('http') else f'https://compass-kappa-nine.vercel.app{s}'
    print('Fetching bundle:', url)
    res = httpx.get(url, timeout=30.0)
    print('Bundle size:', len(res.text))
    has_972 = '97.2' in res.text
    has_894 = '89.4' in res.text
    print('Matches for 97.2:', has_972)
    print('Matches for 89.4:', has_894)
    if has_972:
        idx = res.text.find('97.2')
        print('Context 97.2:', repr(res.text[max(0, idx-50):idx+50]))
    if has_894:
        idx = res.text.find('89.4')
        print('Context 89.4:', repr(res.text[max(0, idx-50):idx+50]))
