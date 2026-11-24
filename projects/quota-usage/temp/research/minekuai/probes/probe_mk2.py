import json, urllib.request, urllib.error

cfg = json.load(open('/var/minis/shared/mk-quota/config.json'))
TOKEN = cfg['access_token']
CID = cfg.get('client_id', '428a8310cd442757ae699df5d894f051')
BASE = 'https://minekuai.cn'

def get(path, method='GET', body=None):
    req = urllib.request.Request(BASE + path, method=method)
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
        return e.code, e.read().decode()[:200]
    except Exception as e:
        return -1, repr(e)

paths = [
    '/app/token/paid',
    '/app/token/paygo',
    '/app/token/quota',
    '/app/token/detail',
    '/app/token/order/list?page=1&size=2',
    '/app/token/orders?page=1&size=2',
    '/app/token/records?page=1&size=2',
    '/app/token/logs?page=1&size=2',
    '/app/token/packs',
    '/app/paygo',
    '/app/paygo/token',
    '/app/llm/keys',
    '/app/apikeys',
    '/app/token/keys',
    '/app/pay/orders?pageNum=1&pageSize=2',
    '/app/order/orders?page=1&size=2',
    '/app/recharge/records?page=1&size=2',
    '/app/balance/yuan',
    '/app/wallet/points',
]
for p in paths:
    st, txt = get(p)
    print(f'{p} -> {st} :: {txt[:300]}')