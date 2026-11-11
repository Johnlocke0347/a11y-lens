"""A11Y Lens - autonomous accessibility testing and repair verification for Hermes Agent.

register() only declares tools/commands/skills.  It does no I/O, spawns nothing and opens no sockets;
the browser is launched lazily, inside an isolated worker process, when a scan is requested.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TOOLSET = "a11y-lens"
_HERE = Path(__file__).resolve().parent


def register(ctx) -> None:
    from .cli import make_cli_handler, make_slash_handler, setup_parser
    from .tools import TOOLS, Runtime, make_handlers

    rt = Runtime(ctx)
    handlers = make_handlers(rt)
    for name, schema, emoji in TOOLS:
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=handlers[name],
                          description=schema["description"].split(". ")[0], emoji=emoji)

    ctx.register_command("a11y", make_slash_handler(rt),
                         description="Accessibility scans: /a11y scan <url|path> | list | report | compare | doctor",
                         args_hint="<scan|list|report|compare|doctor> …")
    ctx.register_cli_command(
        name="a11y", help="A11Y Lens: install browser, self-test, authorise origins, scan",
        setup_fn=setup_parser, handler_fn=make_cli_handler(rt, ctx),
        description="Manage A11Y Lens (hermes a11y install | doctor | allow <origin> | scan <target> | compare <a> <b>)",
    )
    skill = _HERE / "skills" / "a11y-repair" / "SKILL.md"
    if skill.exists():
        ctx.register_skill("a11y-repair", skill, description="Scan -> fix -> rescan -> compare workflow for accessibility repairs")
