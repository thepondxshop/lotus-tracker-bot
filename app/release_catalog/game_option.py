"""Dynamic game suggestions keep repeated release options below Discord limits."""
from discord import app_commands
from .extraction import GAMES


class GameOptionError(app_commands.AppCommandError):
    pass


class GameOption(app_commands.Transformer):
    async def autocomplete(self, interaction, value):
        permissions = getattr(interaction, "permissions", None)
        if not getattr(interaction, "guild_id", None) or not getattr(permissions, "administrator", False):
            return []
        query = value.strip().casefold()
        return [app_commands.Choice(name=game, value=game)
                for game, _ in GAMES if query in game.casefold()][:25]

    async def transform(self, interaction, value):
        query = value.strip().casefold()
        for game, _ in GAMES:
            if game.casefold() == query:
                return game
        raise GameOptionError("Choose a supported game from the suggestions.")
