import json,urllib.request,collections
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=40))
rows=[];pn=1
while True:
    d=g(f'/app/llm/requests?pageNum={pn}&pageSize=100')
    if not d['rows']: break
    rows+=d['rows']
    if len(rows)>=d['total']: break
    pn+=1
# 按 (天,通道,密钥) 聚合
tbl=collections.defaultdict(int)
for r in rows:
    u=sum(int(r.get(k) or 0) for k in ('inputTokens','cacheReadTokens','outputTokens'))
    tbl[(r['createTime'][:10], r['groupCode'], r['apiKeyPrefix'])]+=u
for k in sorted(tbl): print(k, f'{tbl[k]/1e4:.2f}万')
