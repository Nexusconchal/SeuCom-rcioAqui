"""Bounded, read-only local load probe. Not a production capacity certificate."""
import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from urllib.request import urlopen


def probe(base, paths, count=100, workers=8):
    if urlsplit(base).hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('Esta ferramenta só executa carga no ambiente local.')
    if not 1 <= count <= 500 or not 1 <= workers <= 16 or any(not p.startswith('/') or p.startswith('//') or '#' in p for p in paths):
        raise ValueError('Use até 500 consultas, 16 conexões e caminhos locais.')
    def get(index):
        started=time.monotonic()
        try:
            with urlopen(base.rstrip('/')+paths[index%len(paths)],timeout=20) as response:
                response.read(2*1024*1024)
                return response.status,round((time.monotonic()-started)*1000,2)
        except OSError:
            return 0,round((time.monotonic()-started)*1000,2)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows=list(pool.map(get,range(count)))
    values=sorted(row[1] for row in rows)
    return dict(requests=count,concurrency=workers,errors=sum(status!=200 for status,_ in rows),
                median_ms=statistics.median(values),p95_ms=values[min(len(values)-1,int(len(values)*.95))],
                note='Somente leituras locais. Não mede pagamentos reais, impressoras, WhatsApp nem capacidade nacional.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base')
    parser.add_argument('--path',action='append',default=['/health','/'])
    parser.add_argument('--requests',type=int,default=100)
    parser.add_argument('--workers',type=int,default=8)
    args=parser.parse_args()
    result=probe(args.base,args.path,args.requests,args.workers)
    print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(1 if result['errors'] else 0)
