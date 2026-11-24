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
print('total',d['total'],'fetched',len(rows))
print('groupCode 分布:',collections.Counter(r['groupCode'] for r in rows))
print('endpoint 分布:',collections.Counter(r['endpoint'] for r in rows))
print('最早记录:',rows[-1]['createTime'],' 最晚:',rows[0]['createTime'])
# 11-15..11-19 全部原始记录按天列
for r in rows[::-1]:
    if r['createTime'][:10] <= '2026-11-19':
        u=sum(int(r.get(k) or 0) for k in ('inputTokens','cacheReadTokens','outputTokens'))
        print(r['createTime'], r['groupCode'], r['apiKeyPrefix'], r['endpoint'], f'{u} tokens')
