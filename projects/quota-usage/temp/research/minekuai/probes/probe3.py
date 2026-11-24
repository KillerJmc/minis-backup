import json,urllib.request,urllib.error
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p,m='GET',b=None):
    r=urllib.request.Request('https://minekuai.cn'+p,method=m)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    r.add_header('accept','application/json')
    if b is not None:
        r.add_header('content-type','application/json'); r.data=json.dumps(b).encode()
    try:
        with urllib.request.urlopen(r,timeout=20) as x: return x.status,x.read().decode()
    except urllib.error.HTTPError as e: return e.code,e.read().decode()[:300]
    except Exception as e: return -1,repr(e)
for p,m in [('/app/token/paid/orders?page=1&size=5','GET'),
            ('/app/token/paid/orders','GET'),
            ('/app/recharge/options','GET'),
            ('/app/site/sales','GET'),
            ('/app/wallet/logs?page=1&size=3','GET'),
            ('/app/fish/logs?page=1&size=3','GET'),
            ('/app/api-member/quota','GET'),
            ('/app/groups','GET')]:
    s,t=g(p,m); print(f'=== {p} [{m}] -> {s}'); print(t[:1000]); print()
