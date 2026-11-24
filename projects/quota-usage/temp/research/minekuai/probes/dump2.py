import json,urllib.request
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p,auth=True):
    r=urllib.request.Request('https://minekuai.cn'+p)
    if auth:
        r.add_header('Authorization','Bearer '+cfg['access_token'])
        r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=25))
for p,a in [('/app/site/banner',False),('/app/llm/models/public',False),('/app/llm/models',True),('/app/llm/requests/daily?days=7',True),('/app/checkin',True)]:
    try:
        d=g(p,a)
        s=json.dumps(d,ensure_ascii=False)
        print('###',p); print(s[:1500]); print()
    except Exception as e:
        print('###',p,'ERR',e)
