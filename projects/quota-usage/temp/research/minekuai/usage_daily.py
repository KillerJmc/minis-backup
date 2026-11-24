import json,urllib.request,collections
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=30))
rows=[];pn=1
while True:
    d=g(f'/app/llm/requests?pageNum={pn}&pageSize=100')
    if not d['rows']: break
    rows+=d['rows']
    if len(rows)>=d['total']: break
    pn+=1
print('total',d['total'],'fetched',len(rows),'uniq',len({r['id'] for r in rows}))
agg=collections.defaultdict(int); cnt=collections.Counter()
for r in rows:
    u=sum(int(r.get(k) or 0) for k in ('inputTokens','cacheReadTokens','outputTokens'))
    agg[(r['createTime'][:10],r['groupCode'])]+=u
    cnt[(r['createTime'][:10],r['groupCode'])]+=1
for k in sorted(agg): print(k,f'{agg[k]/1e4:.2f}万',cnt[k],'req')
