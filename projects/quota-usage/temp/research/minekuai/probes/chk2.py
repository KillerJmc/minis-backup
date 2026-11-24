import json,urllib.request
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=30))
d=g('/app/llm/requests/daily?days=3')['data']['daily']
for r in d:
    tot=sum(int(r.get(k) or 0) for k in ('inputTokens','cacheReadTokens','outputTokens'))
    print(r['date'],'req',r['requests'],'raw',f'{tot/1e4:.2f}万')
print('--- 分页实测 ---')
for size in (20,100,500):
    p1=g(f'/app/llm/requests?page=1&size={size}')
    print('size',size,'-> total',p1['total'],'rows',len(p1['rows']))
