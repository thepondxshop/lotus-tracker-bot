import copy
import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import lotus_ebay_setup as setup
from app.marketplaces.ebay_evidence import comparison, identity_key

class ExpansionTests(unittest.TestCase):
    def setUp(self):
        self.target = copy.deepcopy(setup.PRESET)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'targets.json'

    def sales(self, n=5, bad=False):
        path = Path(self.temp.name) / 'sales.csv'
        with path.open('w', newline='') as out:
            writer = csv.DictWriter(out, fieldnames=setup.COLUMNS)
            writer.writeheader()
            for i in range(n):
                writer.writerow(dict(listing_id=str(123456789000+i),
                    sold_at=datetime.now(timezone.utc).isoformat(), item_price='100.00',
                    currency='USD', gtin='wrong' if bad and i==n-1 else self.target['gtin'],
                    condition_id='1000',language='English',configuration='Box',quantity='1',
                    price_kind='SOLD_FIXED',source_kind='EBAY_SOLD_LISTING',exact_match='true'))
        return path

    def snapshot(self):
        now=datetime.now(timezone.utc)
        return dict(schema='PRODUCT_RESEARCH_AGGREGATE1',identity_key=identity_key(self.target),
            reviewed=True,exact_match=True,source_kind='EBAY_PRODUCT_RESEARCH',source_scope='VISIBLE_ROWS_ONLY',
            currency='USD',cost_basis='ITEM_ONLY',period_label='LAST_7_DAYS',
            window_start_bound=(now-timedelta(days=7)).isoformat(),window_end_bound=now.isoformat(),
            captured_at=now.isoformat(),rows=[dict(row_key=str(i),units=1,item_sales='100.00') for i in range(5)])

    def test_bulk_preserves_existing(self):
        added=copy.deepcopy(self.target);added['id']='second-reviewed-product'
        original=copy.deepcopy([self.target])
        rows=setup.merge_targets(original,[added])
        self.assertEqual(len(rows),2); self.assertEqual(original,[self.target])
        setup.save(self.path,rows)
        self.assertEqual(len(setup.load_targets(self.path)),2)

    def test_invalid_batch_no_partial_write(self):
        setup.save(self.path,[self.target]); before=self.path.read_bytes()
        added=copy.deepcopy(self.target);added['id']='second'
        bad=copy.deepcopy(added);bad['id']='third';bad['reviewed']=False
        with self.assertRaises(ValueError): setup.merge_targets([self.target],[added,bad])
        self.assertEqual(self.path.read_bytes(),before)

    def test_duplicate_and_embedded_evidence_rejected(self):
        with self.assertRaises(ValueError): setup.merge_targets([self.target],[self.target])
        added=copy.deepcopy(self.target);added['id']='second';added['aggregate_snapshot']={}
        with self.assertRaises(ValueError): setup.merge_targets([self.target],[added])

    def test_expired_aggregate_replaced_without_overlap(self):
        self.target['aggregate_snapshot']={'old':'expired'}
        updated=setup.import_sales(self.target,self.sales(),replace=True)
        self.assertNotIn('aggregate_snapshot',updated)
        self.assertIn('aggregate_snapshot',self.target)
        self.assertTrue(comparison(updated)['ready'])
        self.assertEqual(comparison(updated)['threshold'],'90.00')

    def test_replacement_needs_explicit_flag_and_five_sales(self):
        self.target['aggregate_snapshot']={'old':'expired'}
        with self.assertRaises(ValueError): setup.import_sales(self.target,self.sales())
        with self.assertRaises(ValueError): setup.import_sales(self.target,self.sales(4),True)
        self.assertEqual(self.target['aggregate_snapshot'],{'old':'expired'})

    def test_invalid_sale_preserves_all(self):
        original=copy.deepcopy(self.target)
        with self.assertRaises(ValueError): setup.import_sales(self.target,self.sales(bad=True),True)
        self.assertEqual(original,self.target)

    def test_snapshot_binding_and_expiry(self):
        snapshot=self.snapshot()
        updated=setup.replace_snapshot(self.target,snapshot)
        self.assertTrue(comparison(updated)['ready'])
        snapshot['identity_key']='wrong'
        with self.assertRaises(ValueError): setup.replace_snapshot(self.target,snapshot)
        snapshot=self.snapshot()
        for key in ['captured_at','window_start_bound','window_end_bound']:
            snapshot[key]=(datetime.fromisoformat(snapshot[key])-timedelta(days=30)).isoformat()
        with self.assertRaises(ValueError): setup.replace_snapshot(self.target,snapshot)

    def test_save_backups_and_runtime_revalidation(self):
        setup.save(self.path,[self.target]); before=self.path.read_bytes()
        updated=setup.import_sales(self.target,self.sales(),True)
        setup.save(self.path,[updated])
        backups=list(self.path.parent.glob('targets.json.backup-*'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),before)
        invalid=copy.deepcopy(updated); invalid['quantity']=2
        saved=self.path.read_bytes()
        with self.assertRaises(ValueError): setup.save(self.path,[invalid])
        self.assertEqual(self.path.read_bytes(),saved)

    def test_dry_run_cli_does_not_write(self):
        from unittest.mock import patch
        import contextlib, io
        setup.save(self.path,[self.target]);before=self.path.read_bytes()
        with patch('sys.argv',['setup','--targets',str(self.path),'--import-sold',str(self.sales()),'--replace-benchmark','--dry-run']), contextlib.redirect_stdout(io.StringIO()) as out:
            setup.main()
        self.assertEqual(json.loads(out.getvalue())['state'],'PREVIEW')
        self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(list(self.path.parent.glob('*.backup-*')))

if __name__=='__main__':unittest.main()
