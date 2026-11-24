import json,urllib.request,collections
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=30))
rows=[];pn=1;total=0
while True:
    d=g(f'/app/llm/requests?pageNum={pn}&pageSize=100')
    total=d['total']
    if not d['rows']: break
    rows+=d['rows']
    if len(rows)>=total: break
    pn+=1
print('total',total,'fetched',len(rows),'earliest',min(r['createTime'] for r in rows))
agg=collections.defaultdict(int);cnt=collections.Counter()
for r in rows:
    u=sum(int(r.get(k) or 0) for k in ('inputTokens','cacheReadTokens','outputTokens'))
    k=(r['createTime'][:10],r['groupCode']);agg[k]+=u;cnt[k]+=1
for k in sorted(agg): print(k,f'{agg[k]/1e4:.2f}万',cnt[k],'req')
print('keys of a lite_token row:')
for r in rows:
    if r['groupCode']!='paygo':
        print(json.dumps(r,ensure_ascii=False)[:700]);break
