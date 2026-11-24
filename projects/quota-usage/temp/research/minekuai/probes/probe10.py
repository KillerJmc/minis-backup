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
today=[r for r in rows if r['createTime'][:10]=='2026-11-23']
print(collections.Counter((r['apiKeyPrefix'],r['groupCode']) for r in today))
for r in today:
    if r['apiKeyPrefix']=='sk-5nAqk':
        print(r['createTime'], r['groupCode'], r['status'], r.get('blockReason'), r.get('errorCode'))
