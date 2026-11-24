import json,urllib.request
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=20))
lg=g('/app/token/logs?page=1&size=50')['rows']
print('total logs',len(lg))
import collections
print(collections.Counter((r['type'],r['scope']) for r in lg))
print('--- usage 类型示例 ---')
for r in lg:
    if r['type'] not in ('buy','exchange','task'):
        print(json.dumps(r,ensure_ascii=False)); break
print('--- latest request ---')
rq=g('/app/llm/requests?page=1&size=3')
print(json.dumps(rq,ensure_ascii=False)[:1500])
