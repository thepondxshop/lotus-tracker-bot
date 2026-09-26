"""Private publisher verification and date-window views."""
import json
import discord
from discord import app_commands
from sqlalchemy import select
from .official import OfficialCheck
from .official_parser import PRESETS, VERSION

class OfficialCommands(app_commands.Group):
    def __init__(self,root):
        super().__init__(name='official',description='Publisher checks, release windows and source evidence')
        self.root=root;self.verifier=root.watch_group.runner.official
    async def interaction_check(self,interaction): return await self.root.interaction_check(interaction)
    async def on_error(self,interaction,error): await self.root.on_error(interaction,error)

    @app_commands.command(name='discovery',description='Enable automatic One Piece product-page leads or view discovery status')
    async def discovery(self,interaction:discord.Interaction,enabled:bool|None=None):
        from .commands import embed
        async def work():
            if enabled is not None:
                await self.verifier.discovery.configure(interaction.guild_id,interaction.user.id,enabled)
            return await self.verifier.discovery.status(interaction.guild_id)
        def render(data):
            result=embed('Official page discovery 1.6.3',
                f"Automatic discovery: {'ON' if data['enabled'] else 'OFF'}\n"
                'Supported: English One Piece OP / EB / PRB / PEB boosters; starter/deck sets; DP; tins; Devil Fruit collections; illustration boxes; sleeves, playmats and other individual product pages.\n'
                'The product index is checked on a five-minute target while enabled; source cooldowns still apply.\n'
                'New leads use your existing Release Radar publishing channel and post before admin review.\n'
                'Known pages/links are baselined at first setup.\n'
                f"Saved page states: {data['counts']}")
            result.add_field(name='Existing page',value='Add/scan its specific official source, then use /release official importpage source_id:<ID>.',inline=False)
            result.add_field(name='Delivery',value='Check /release radar publishing. Discovery does not enable publishing or confirm retailer availability.',inline=False)
            return result
        await self.root._run(interaction,work,render)

    @app_commands.command(name='importpage',description='Import one saved official One Piece product page into Release Radar')
    async def importpage(self,interaction:discord.Interaction,source_id:int):
        from .commands import embed
        async def work():
            result=await self.verifier.discovery.import_source(interaction.guild_id,interaction.user.id,source_id)
            await self.verifier.reconcile(interaction.guild_id,'One Piece')
            return result
        await self.root._run(interaction,work,lambda data:embed('Official page discovery',
            f"Result: {data['state']} • Release #{data['release_id']}\n"
            'New records are eligible for automatic publishing when publishing is enabled.\n'
            'Existing records reuse their catalog entry. To announce an existing entry: '
            f"/release radar announce release_id:{data['release_id']}\n"
            'No retailer stock or preorder availability was asserted.'))

    @app_commands.command(name='sources',description='Show official publisher sources for all ten games')
    async def sources(self,interaction:discord.Interaction):
        from .commands import embed,safe
        def render(rows):
            lines=[]
            for r in rows:
                last=json.loads(r['last_json'])
                lines.append(f"**#{r['id']} {safe(r['game'],80)}** • {'ON' if r['enabled'] else 'OFF'}\n{safe(r['url'],180)}\n{last.get('error') or ('Checked' if last else 'Pending')} • {last.get('pages_ok',0)} pages")
            result=embed('Official publisher sources '+VERSION,'\n\n'.join(lines)[:3800])
            result.add_field(name='Coverage',value='Sources are configured automatically. Public text and supported matching are required; a configured source does not guarantee complete catalog coverage.',inline=False)
            return result
        await self.root._run(interaction,lambda:self.verifier.sources(interaction.guild_id),render)

    @app_commands.command(name='add',description='Add a specific official article or product page on a supported publisher domain')
    @app_commands.choices(game=[app_commands.Choice(name=g,value=g) for g in PRESETS])
    async def add(self,interaction:discord.Interaction,game:str,url:str,region:str='UNKNOWN',language:str='UNKNOWN'):
        from .commands import embed
        await self.root._run(interaction,lambda:self.verifier.add(interaction.guild_id,game,url,language,region),
            lambda r:embed('Official source saved',f"Source #{r['id']} • {r['game']}\nScheduled checks are automatic. A source does not by itself confirm any product."))

    @app_commands.command(name='settings',description='Pause or resume an official publisher source')
    async def settings(self,interaction:discord.Interaction,source_id:int,enabled:bool):
        from .commands import embed
        await self.root._run(interaction,lambda:self.verifier.settings(interaction.guild_id,source_id,enabled),
            lambda r:embed('Official source updated',f"Source #{r['id']} • Enabled: {r['enabled']}"))

    @app_commands.command(name='scan',description='Scan an official source now; source cooldown still applies')
    async def scan(self,interaction:discord.Interaction,source_id:int):
        from .commands import embed
        await self.root._run(interaction,lambda:self.verifier.scan(interaction.guild_id,source_id),
            lambda r:embed('Official verification scan',f"Pages checked: {r['pages_ok']}\nRemaining pages: {r['remaining']}\nResult: {r['error'] or 'Completed'}\nUse /release official check with a release ID to see matched evidence."))

    @staticmethod
    def render_result(data):
        from .commands import embed,safe
        r=data['release'];check=data['check']
        result=embed(f"Official verification • Release #{r['id']}",safe(r['title'],200))
        result.add_field(name='Check',value=f"{check['state']}\nLast evaluated: {data['checked_at'] or 'Pending'}",inline=False)
        if check.get('distributor_dates'):
            result.add_field(name='Distributor-reported dates',value=', '.join(check['distributor_dates'])[:1000],inline=False)
        for e in check.get('evidence',[])[:5]:
            window=' / '.join(w['label']+' ('+w['precision']+')' for w in e['windows']) or 'No unambiguous release date extracted'
            detail=f"{safe(e['url'],400)}\n{safe(window,200)}\nScope: {e['match_scope']} • {e['region']} / {e['language']}\nChecked: {e['fetched_at']}"
            if e.get('stale'): detail+='\nSTALE: previous evidence retained; recheck required'
            if e['issues']: detail+='\n'+safe(', '.join(e['issues']),220)
            result.add_field(name=e['state'],value=detail[:1024],inline=False)
        if not check.get('evidence'):
            errors=[x['last'].get('error') for x in check.get('sources',[]) if x['last'].get('error')]
            result.add_field(name='Awaiting evidence',value='No supported official match yet. This does not disprove the distributor listing.'+('\nSource errors: '+', '.join(errors) if errors else ''),inline=False)
        result.add_field(name='Interpretation',value='Set and game-launch dates are broader than SKU dates. Month/quarter windows are not exact dates. This check does not change retailer stock, open preorders, or overwrite the confirmed calendar.',inline=False)
        return result

    @app_commands.command(name='check',description='See official evidence and conflicts for a catalog release ID')
    async def check(self,interaction:discord.Interaction,release_id:int):
        await self.root._run(interaction,lambda:self.verifier.result(interaction.guild_id,release_id),self.render_result)

    @app_commands.command(name='status',description='Check the independent official verification worker')
    async def status(self,interaction:discord.Interaction):
        from .commands import embed
        async def data():
            rows=await self.verifier.sources(interaction.guild_id)
            return {'sources':len(rows),'enabled':sum(x['enabled'] for x in rows)}
        await self.root._run(interaction,data,lambda r:embed('Official verifier '+VERSION,
            f"Worker: {self.verifier.state}\nSources: {r['sources']} • Enabled: {r['enabled']}\nScan running: {self.verifier.lock.locked()}\nLast error: {self.verifier.last_error or 'None'}\n\nNew catalog records are checked against saved publisher pages, then scheduled for a fresh source check. Publisher checks run independently of retailer alerts."))
