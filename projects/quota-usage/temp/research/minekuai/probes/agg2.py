import json,urllib.request,collections
cfg=json.load(open('/var/minis/shared/mk-quota/config.json'))
def g(p):
    r=urllib.request.Request('https://minekuai.cn'+p)
    r.add_header('Authorization','Bearer '+cfg['access_token'])
    r.add_header('clientid',cfg['client_id'])
    return json.load(urllib.request.urlopen(r,timeout=30))
rows=[];page=1;total=None
while True:
    d=g(f'/app/llm/requests?page={page}&size=20')
    total=d['total']
    if not d['rows']: break
    rows+=d['rows']
    if len(rows)>=total: break
    page+=1
print('total',total,'fetched',len(rows),'uniq',len({r['id'] for r in rows}))
print(collections.Counter((r['createTime'][:10],r['groupCode']) for r in rows))
