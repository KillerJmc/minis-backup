import json,urllib.request
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=30))
base='/app/llm/requests'
for q in ['?page=2&size=20','?pageNum=2&pageSize=20','?current=2&size=20','?offset=20&limit=20','']:
    d=g(base+q)
    ids=[r['id'][-6:] for r in d['rows'][:2]]
    print(f'{q or "(none)"} -> total {d["total"]} rows {len(d["rows"])} first {ids}')
