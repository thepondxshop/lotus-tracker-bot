"""Guided eBay watchlist and sold-record import; never sends alerts."""
import argparse
import asyncio
import csv
import json
import os
import tempfile
from copy import deepcopy
from urllib.parse import urlsplit
from pathlib import Path
from app.marketplaces.ebay_live_policy import load_targets
from app.marketplaces.ebay_evidence import evidence_record, comparison, config_hash, identity_key

COLUMNS = ['listing_id','sold_at','item_price','currency','gtin','condition_id','language','configuration','quantity','price_kind','source_kind','exact_match']
PRESET = {'id':'pokemon-151-bundle-en','reviewed':True,'game':'Pokemon','gtin':'820650853210',
 'condition_id':'1000','quantity':1,'required_terms':['151','booster bundle'],
 'excluded_terms':['single pack','empty','repack','break spot','display case','lot of','japanese','korean','chinese'],
 'aspects':{'Language':'English','Configuration':'Box'},'currency':'USD',
 'comparison_mode':'ITEM_ONLY','sold_records':[],
 'identity_source':'https://shop.thirdeyecomics.com/products/pokemon-tcg-scarlet-violet-151-booster-bundle'}

def save(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd, temporary=tempfile.mkstemp(prefix='.lotus-targets-',suffix='.json',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out: json.dump(rows,out,indent=2);out.write('\n')
        load_targets(temporary)
        if path.exists():
            # Exclusive backup: never overwrite a previous operator backup.
            with path.with_name(path.name+'.backup-'+__import__('uuid').uuid4().hex[:8]).open('x') as out:
                out.write(path.read_text())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

def read_json(path):
    path = Path(path)
    if path.stat().st_size > 4194304:
        raise ValueError('Input exceeds 4 MiB')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def merge_targets(existing, incoming):
    """Add identities only. Existing targets and their evidence cannot be overwritten."""
    if not isinstance(incoming, list) or not incoming:
        raise ValueError('Expected a nonempty target list')
    merged = deepcopy(existing)
    ids = {t['id'] for t in merged}
    for target in incoming:
        if not isinstance(target, dict) or target.get('id') in ids:
            raise ValueError('Duplicate/existing target ID; existing evidence preserved')
        if target.get('comparison_mode') != 'ITEM_ONLY':
            raise ValueError('New targets require ITEM_ONLY comparison')
        aspects = target.get('aspects', {})
        if not isinstance(aspects, dict) or not all(aspects.get(k) for k in ('Language', 'Configuration')):
            raise ValueError('Explicit language and configuration required')
        source = urlsplit(str(target.get('identity_source', '')))
        if source.scheme != 'https' or not source.hostname or source.username or source.password:
            raise ValueError('HTTPS product identity source required')
        if target.get('sold_records') or 'aggregate_snapshot' in target or target.get('comparison'):
            raise ValueError('Import identities first; import sold evidence separately')
        ids.add(target.get('id'))
        merged.append(deepcopy(target))
    # Reuse exactly the runtime validator without changing a live file.
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory) / 'targets.json'
        temporary.write_text(json.dumps(merged))
        load_targets(temporary)
    return merged


def replace_snapshot(target, snapshot):
    """Require explicit binding to this identity; never stamp or extend evidence dates."""
    from app.marketplaces.ebay_evidence import identity_key
    from app.marketplaces.ebay_snapshot import snapshot_comparison
    report = snapshot_comparison(snapshot, identity_key(target))
    if not report['ready']:
        raise ValueError(report['reason'])
    updated = deepcopy(target)
    updated['aggregate_snapshot'] = deepcopy(snapshot)
    updated['sold_records'] = []
    return updated


def import_sales(target, path, replace=False):
    if 'aggregate_snapshot' in target and not replace:
        raise ValueError('Use --replace-benchmark to replace the old aggregate with fresh sales')
    if Path(path).stat().st_size > 1048576:
        raise ValueError('CSV too large')
    records = {} if replace else {r['record_key']: r for r in target.get('sold_records', [])}
    count = 0
    with open(path, newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        if not set(COLUMNS).issubset(reader.fieldnames or []):
            raise ValueError('CSV columns missing')
        for count, row in enumerate(reader, 1):
            if count > 500:
                raise ValueError('Maximum 500 CSV rows')
            record = evidence_record(row, target)
            old = records.get(record['record_key'])
            if old and old != record:
                raise ValueError('Conflicting duplicate listing; no changes saved')
            records[record['record_key']] = record
    if not count or len(records) > 500:
        raise ValueError('Expected 1–500 total sold records')
    updated = deepcopy(target)
    updated.pop('aggregate_snapshot', None)
    updated['sold_records'] = list(records.values())
    if replace and not comparison(updated)['ready']:
        raise ValueError('Replacement needs at least five distinct valid sales; old evidence preserved')
    return updated


async def readiness(rows):
    from app.marketplaces.ebay_live_store import Store
    from app.marketplaces import ebay_shadow
    fingerprint=config_hash(rows)
    store=Store()
    try:
        await store.start();await ebay_shadow.ensure(store)
        identity=await store.ready()
        reports=[]
        for t in rows:
            reports.append({'target':t['id'],'comparison':comparison(t),
                'fixed_shadow_ready':await ebay_shadow.ready(store,fingerprint,t['id'],False),
                'auction_shadow_ready':await ebay_shadow.ready(store,fingerprint,t['id'],True)})
        ready=bool(rows) and identity and all(r['comparison']['ready'] and r['fixed_shadow_ready'] for r in reports)
        print(json.dumps({'identity_ready':identity,'targets':reports,'fixed_price_ready_for_operator_review':ready,
                          'reviewed_config_sha256':fingerprint if ready else None,
                          'note':'No settings changed. Auction delivery additionally requires its own eligible shadow observation for this exact configuration.'},indent=2))
    finally: await store.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets',default=os.getenv('EBAY_TARGETS_FILE','ebay-targets.json'))
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--import-targets', metavar='JSON')
    action.add_argument('--import-snapshot', metavar='JSON')
    action.add_argument('--target-template', metavar='PATH')
    action.add_argument('--init-151',action='store_true')
    action.add_argument('--apply-151-snapshot',action='store_true')
    action.add_argument('--csv-template',metavar='PATH')
    action.add_argument('--import-sold',metavar='CSV')
    action.add_argument('--status',action='store_true')
    action.add_argument('--add-sale',action='store_true')
    action.add_argument('--export',action='store_true')
    action.add_argument('--readiness',action='store_true')
    parser.add_argument('--target',default=PRESET['id'])
    parser.add_argument('--confirm-reviewed',action='store_true')
    parser.add_argument('--replace-benchmark',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args();path=Path(args.targets)
    if args.dry_run and not (args.import_targets or args.import_sold or args.import_snapshot):
        parser.error('--dry-run requires an import action')
    if args.replace_benchmark and not (args.import_sold or args.import_snapshot):
        parser.error('--replace-benchmark requires a sold CSV or snapshot import')
    if args.target_template:
        template = deepcopy(PRESET)
        template.update(id='replace-with-product-id', game='', gtin='', reviewed=False,
                        required_terms=[], identity_source='', aspects={'Language':'','Configuration':''})
        with open(args.target_template, 'x') as out:
            json.dump([template], out, indent=2); out.write('\n')
        print('Created unreviewed identity template; complete from product evidence before import.'); return
    if args.csv_template:
        with open(args.csv_template,'x',newline='') as out: csv.writer(out).writerow(COLUMNS)
        print('Created header-only CSV; no sales or prices invented.');return
    rows=load_targets(path) if path.exists() else []
    if args.import_targets or args.import_snapshot or args.import_sold:
        if not args.confirm_reviewed and not args.dry_run:
            parser.error('--confirm-reviewed required after checking original evidence')
        before = config_hash(rows)
        try:
            if args.import_targets:
                rows = merge_targets(rows, read_json(args.import_targets))
            else:
                index = next((i for i,t in enumerate(rows) if t['id']==args.target), None)
                if index is None or rows[index].get('comparison_mode') != 'ITEM_ONLY':
                    raise ValueError('Select an existing item-only target with --target')
                if args.import_snapshot:
                    if not args.replace_benchmark:
                        raise ValueError('--replace-benchmark required for aggregate replacement')
                    rows[index] = replace_snapshot(rows[index], read_json(args.import_snapshot))
                else:
                    rows[index] = import_sales(rows[index], args.import_sold, args.replace_benchmark)
            if not args.dry_run:
                save(path, rows)
        except (ValueError, OSError, KeyError, TypeError) as error:
            parser.error(str(error)+'; no changes saved')
        print(json.dumps({'state':'PREVIEW' if args.dry_run else 'SAVED', 'path':str(path.resolve()),
            'targets':[{'id':t['id'],'identity_key':identity_key(t),
                        'comparison':comparison(t)} for t in rows],
            'config_changed':before!=config_hash(rows), 'config_hash':config_hash(rows),
            'alerts_sent':0, 'live_enabled':False,
            'note':'Config changes require new eligible shadow evidence and approval. Keep saved JSON in persistent storage or the repository.'},indent=2))
        return
    if args.init_151:
        if any(t['id']==PRESET['id'] for t in rows): print('Existing target preserved.');return
        rows.append(PRESET);save(path,rows)
        print('Added one reviewed product identity. Sold benchmark absent; alerts remain blocked.');return
    if args.apply_151_snapshot:
        if not args.confirm_reviewed: parser.error('--confirm-reviewed required for the reviewed screenshot snapshot')
        target=next((t for t in rows if t['id']==args.target),None)
        if not target: parser.error('Run --init-151 first')
        from app.marketplaces.ebay_snapshot import apply_151_snapshot
        try:
            apply_151_snapshot(target)
            report=comparison(target)
            if not report['ready']: parser.error(report['reason']+'; no changes saved')
        except ValueError as error: parser.error(str(error)+'; no changes saved')
        save(path,rows)
    if args.export:
        print(json.dumps(rows,indent=2));return
    if args.add_sale:
        if not args.confirm_reviewed: parser.error('--confirm-reviewed required; verify exact product and actual sold amount first')
        target=next((t for t in rows if t['id']==args.target),None)
        if not target or target.get('comparison_mode')!='ITEM_ONLY': parser.error('Initialize the item-only target first')
        if 'aggregate_snapshot' in target: parser.error('Aggregate snapshot is active; individual-sale entry is blocked to prevent overlapping evidence')
        print('Review target: '+target['id']+'; one unit. No lots, hidden offers or asking prices.')
        row={k:input(label).strip() for k,label in (
            ('listing_id','eBay listing number: '),
            ('sold_at','Sale date/time with timezone (YYYY-MM-DDTHH:MM:SS-04:00 for October New York): '),
            ('item_price','Actual sold ITEM price in USD, excluding shipping/tax: '),
            ('price_kind','Price kind (SOLD_FIXED / SOLD_AUCTION / SOLD_BEST_OFFER_ACTUAL): '),
            ('source_kind','Source (EBAY_SOLD_LISTING / EBAY_PRODUCT_RESEARCH): '))}
        row.update(gtin=target['gtin'],condition_id=target['condition_id'],language=target['aspects']['Language'],
                   configuration=target['aspects']['Configuration'],currency='USD',quantity='1',exact_match='true')
        try: record=evidence_record(row,target)
        except ValueError as error: parser.error(str(error)+'; no changes saved')
        existing=next((r for r in target.get('sold_records',[]) if r['record_key']==record['record_key']),None)
        if existing and existing!=record: parser.error('Conflicting duplicate listing; no changes saved')
        if not existing: target.setdefault('sold_records',[]).append(record);save(path,rows)
    if args.readiness: asyncio.run(readiness(rows));return
    print(json.dumps({'path':str(path.resolve()),'targets':[{'id':t['id'],'identity_key':identity_key(t),'comparison':comparison(t)} for t in rows],
        'alerts_sent':0,'note':'Keep the target JSON in your repository or persistent storage; container edits alone do not survive redeployment.'},indent=2))
if __name__=='__main__': main()
