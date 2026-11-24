import json,urllib.request
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=40))['data']
t=g('/app/token')
print('today:',t['today'])
print('perm :',t['permanent'])
print('paid :',{k:t['paid'][k] for k in ('balance','totalIn','totalUsed')})
print('exchange:',{k:t['exchange'][k] for k in ('dailyCap','cap','exchangedToday','unitsLeft','open','dailyTimes')})
d=g('/app/llm/requests/daily?days=14')
for r in d['daily']:
    tot=sum(int(r.get(k) or 0) for k in ('inputTokens','cacheReadTokens','outputTokens'))
    print(r['date'],'req',r['requests'],f'{tot/1e4:.2f}万')
