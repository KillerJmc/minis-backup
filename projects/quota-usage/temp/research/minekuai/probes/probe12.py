import json,urllib.request
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
key=None
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=25))['data']
ks=g('/app/apikeys')
for k in ks:
    if k['keyPrefix']=='sk-5nAqk':
        print('quota key fields:',json.dumps({kk:vv for kk,vv in k.items() if kk not in ('key',)},ensure_ascii=False)[:800])
