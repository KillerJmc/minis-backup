import json,urllib.request
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=20))
d=g('/app/token')['data']
print(json.dumps(d,ensure_ascii=False,indent=1)[:4000])
print('=== LOGS ===')
lg=g('/app/token/logs?page=1&size=20')
print(json.dumps(lg,ensure_ascii=False,indent=1)[:3500])
