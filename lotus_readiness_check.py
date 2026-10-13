"""READY1: inspect local gates and optionally existing database rows. Never enables stores."""
import argparse
import ast
import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def emit(label, data):
    print(label + ' | ' + json.dumps(data, default=str), flush=True)


def literal_assignment(path, name):
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError('Missing expected assignment: ' + name)


def local_report(root=ROOT):
    pipeline = root / 'app/major_retailers/pipeline.py'
    return {
        'version': 'READY1', 'production_blocks': literal_assignment(pipeline, 'PRODUCTION_BLOCKS'),
        'validation_passes_required': literal_assignment(pipeline, 'VALIDATION_PASSES_REQUIRED'),
        'bestbuy_api_key_present': bool(os.getenv('BESTBUY_API_KEY', '').strip()),
        'database_url_present': bool(os.getenv('DATABASE_URL', '').strip()),
        'note': 'Code gates are independent of retailer approvals. Credentials do not prove live access.'}


async def database_report():
    # Do not import app.database: its startup path is unrelated to a read-only audit.
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.engine import make_url
    raw = os.getenv('DATABASE_URL', '').strip()
    if not raw:
        raise ValueError('DATABASE_URL missing')
    url = make_url(raw)
    if url.drivername not in ('postgres', 'postgresql', 'postgresql+asyncpg'):
        raise ValueError('PostgreSQL required')
    engine = create_async_engine(url.set(drivername='postgresql+asyncpg'), connect_args={'timeout': 10})
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(text('SET TRANSACTION READ ONLY'))
                await connection.execute(text("SET LOCAL statement_timeout = '5000ms'"))
                queries = {
                    'stores': '''SELECT id, name, domain, platform, region, active, health_status,
                        consecutive_failures, last_success_at,
                        (last_error IS NOT NULL AND last_error <> '') AS has_last_error,
                        (disabled_reason IS NOT NULL AND disabled_reason <> '') AS has_disabled_reason
                        FROM public.stores ORDER BY id LIMIT 500''',
                    'major_retailer_runtime': '''SELECT retailer_key, store_id, mode, kill_switch,
                        baseline_ready, validation_passes, last_probe_success, last_success_at,
                        last_accepted, last_emitted_events,
                        (last_error IS NOT NULL AND last_error <> '') AS has_last_error
                        FROM public.major_retailer_runtime ORDER BY retailer_key LIMIT 100''',
                    'major_retailer_system_control': '''SELECT control_key, global_kill_switch
                        FROM public.major_retailer_system_control LIMIT 10'''}
                for table, query in queries.items():
                    exists = await connection.scalar(text('SELECT to_regclass(:table)'), {'table': 'public.' + table})
                    if not exists:
                        emit('LOTUS READINESS DATABASE', {'table': table, 'state': 'NOT_CREATED'})
                        continue
                    rows = (await connection.execute(text(query))).mappings().all()
                    emit('LOTUS READINESS DATABASE', {'table': table, 'rows': [dict(row) for row in rows]})
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', action='store_true', help='Read existing Railway PostgreSQL rows; no writes')
    args = parser.parse_args()
    try:
        emit('LOTUS READINESS LOCAL', local_report())
        if args.database:
            asyncio.run(database_report())
    except Exception as error:
        # Exception text can contain a connection URL. Never print it.
        emit('LOTUS READINESS ERROR', {'type': type(error).__name__, 'database_requested': args.database})
        return 1
    emit('LOTUS READINESS NOTE', {'live_access_tested': False, 'discord_delivery_tested': False,
                                 'stores_enabled': False, 'database_modified': False})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
