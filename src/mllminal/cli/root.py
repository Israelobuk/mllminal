"""Click routing that preserves subcommands while allowing root Mil targets."""

from __future__ import annotations

from typer._click.core import Command, Context
from typer.core import TyperGroup


class MilRootGroup(TyperGroup):
    """Route unknown root tokens to the hidden prompt/workspace command."""

    def resolve_command(
        self, ctx: Context, args: list[str]
    ) -> tuple[str | None, Command | None, list[str]]:
        if args and not args[0].startswith("-") and self.get_command(ctx, args[0]) is None:
            fallback = self.get_command(ctx, "_root_target")
            if fallback is not None:
                return "_root_target", fallback, args
        return super().resolve_command(ctx, args)
