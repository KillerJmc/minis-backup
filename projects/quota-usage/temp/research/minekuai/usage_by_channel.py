import json,urllib.request,collections
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def raw(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=40))
t=raw('/app/token')['data']
rows=[];pn=1
while True:
    d=raw(f'/app/llm/requests?pageNum={pn}&pageSize=100')
    rws=d.get('rows') or (d.get('data') or {}).get('rows') or []
    if not rws: break
    rows+=rws
    tot=d.get('total') or (d.get('data') or {}).get('total') or 0
    if len(rows)>=tot: break
    pn+=1
agg=collections.defaultdict(int); today=collections.defaultdict(int)
for r in rows:
    u=sum(int(r.get(k) or 0) for k in ('inputTokens','cacheReadTokens','outputTokens'))
    agg[r['groupCode']]+=u
    if r['createTime'][:10]==t['day']: today[r['groupCode']]+=u
p=t['paid']; pm=t['permanent']; td=t['today']
print('PAID  used',p['totalUsed'],'bal',p['balance'],'in',p['totalIn'],'| today',today['paygo'],'win',agg['paygo'])
print('TODAY used',td['used'],'bal',td['remaining'],'in',td['exchanged']+td['bonus'],'| win',agg.get('default',0))
print('PERM  used',pm['totalUsed'],'bal',pm['balance'],'in',pm['totalIn'],'| today',today['lite_token'],'win',agg['lite_token'])
print('rows',len(rows))
