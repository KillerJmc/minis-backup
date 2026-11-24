import json,urllib.request
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=25))
t=g('/app/token')['data']
print('perm', t['permanent'])
print('exchange', {k:t['exchange'][k] for k in ('dailyCap','paidCap','cap','exchangedToday','unitsLeft','open')})
d=g('/app/llm/requests/daily?days=4')['data']['daily']
for r in d:
    u=sum(int(r.get(k) or 0) for k in ('inputTokens','cacheReadTokens','outputTokens'))
    print(r['date'], r['requests'], f'{u/1e4:.2f}万')
