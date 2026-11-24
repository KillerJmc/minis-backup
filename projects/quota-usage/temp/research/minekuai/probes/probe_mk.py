import json, sys, urllib.request, urllib.error

cfg = json.load(open('/var/minis/shared/mk-quota/config.json'))
TOKEN = cfg['access_token']
CID = cfg.get('client_id', '428a8310cd442757ae699df5d894f051')
BASE = 'https://minekuai.cn'

def get(path, method='GET', body=None):
    url = BASE + path
    req = urllib.request.Request(url, method=method)
    req.add_header('Authorization', 'Bearer ' + TOKEN)
    req.add_header('clientid', CID)
    req.add_header('accept', 'application/json')
    if body is not None:
        req.add_header('content-type', 'application/json')
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:
        return -1, repr(e)

paths = [
    '/app/balance',
    '/app/balance/logs?page=1&size=3',
    '/app/token',
    '/app/token/tasks',
    '/app/wallet',
    '/app/fish/mine',
    '/app/fish/tiers',
    '/app/member/me',
    '/app/llm/requests/summary',
    '/app/llm/stats/live',
    '/app/overview',
    '/app/user/info',
    '/app/account',
    '/app/pay/orders?page=1&size=3',
    '/app/order/list?page=1&size=3',
    '/app/recharge/packages',
    '/app/token/plans',
    '/app/goods/list',
]

for p in paths:
    st, txt = get(p)
    print('=' * 70)
    print(f'{p}  -> HTTP {st}')
    print(txt[:1200])