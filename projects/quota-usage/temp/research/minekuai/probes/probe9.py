import json,urllib.request
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=25))['data']
t=g('/app/token')
for name,pool in (('today',t['today']),('permanent',t['permanent']),('paid',t['paid'])):
    print(name, {k:pool[k] for k in pool if k in ('balance','totalIn','totalUsed','used','remaining','exchanged','bonus')})
k=g('/app/apikeys')
for key in k:
    print('KEY', key['keyPrefix'], key['name'], '| accessMode', key.get('accessMode'), '| groupCode', key.get('groupCode'), '| lastUsed', key.get('lastUsedTime'))
