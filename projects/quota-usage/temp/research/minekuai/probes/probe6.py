import json,urllib.request,urllib.error
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    try:
        with urllib.request.urlopen(r,timeout=25) as x: return json.load(x)
    except urllib.error.HTTPError as e: return {'http':e.code,'body':e.read().decode()[:200]}
t=g('/app/token')['data']
print('today',t['today'])
print('perm',t['permanent'])
print('paid',{k:t['paid'][k] for k in ('balance','totalIn','totalUsed')})
for q in ['/app/llm/requests/daily?days=3&groupCode=paygo',
          '/app/llm/requests/daily?days=3&group=paygo',
          '/app/llm/requests/summary?groupCode=paygo',
          '/app/llm/requests/summary?group=default',
          '/app/llm/requests?page=1&size=1&groupCode=default']:
    d=g(q)
    s=json.dumps(d,ensure_ascii=False)
    print('###',q,'->',s[:400])
