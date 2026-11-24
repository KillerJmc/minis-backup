import json,urllib.request,collections
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=30))
rows=[]
page=1
while True:
    d=g(f'/app/llm/requests?page={page}&size=100')
    rows+=d['rows']
    if len(rows)>=d['total'] or not d['rows']: break
    page+=1
print('fetched',len(rows))
agg=collections.defaultdict(int)
cnt=collections.Counter()
for r in rows:
    day=r['createTime'][:10]
    u=sum(int(r.get(k) or 0) for k in ('inputTokens','cacheReadTokens','outputTokens'))
    agg[(day,r['groupCode'])]+=u
    cnt[(day,r['groupCode'])]+=1
for k in sorted(agg):
    print(k, f'{agg[k]/1e4:.2f}万', cnt[k],'req')
print('groups', collections.Counter(r['groupCode'] for r in rows))
