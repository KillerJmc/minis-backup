import json,urllib.request,urllib.error
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    try:
        with urllib.request.urlopen(r,timeout=20) as x: return json.load(x)
    except urllib.error.HTTPError as e: return {'http':e.code}
for p in ['/app/token/mode','/app/addon/items','/app/addon/mine','/app/invite/mine','/app/cdk/redeem']:
    print('###',p, json.dumps(g(p),ensure_ascii=False)[:600])
