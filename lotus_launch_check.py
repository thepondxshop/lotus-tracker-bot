"""Read-only consolidated marketplace launch checklist."""
import argparse, asyncio, json
from app.version import VERSION
from app.marketplaces.launch_status import local_status,database_status
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',action='store_true')
    a=p.parse_args();report=local_status()
    if a.database:report=asyncio.run(database_status(report))
    print('LOTUS LAUNCH CHECK | '+json.dumps({'version':VERSION,**report},default=str))
