# Security

## What Duck Pond touches

Duck Pond reads your local agent transcripts (by default `~/.claude/projects`) to draw the
pool. It **never writes** to that folder, never sends anything over the network, and stores
nothing except Blender's own preferences and, for `DuckPond.exe`, an unpacked copy of the
add-on and a launch log under `%LOCALAPPDATA%\DuckPond`.

Transcripts can contain prompts, file paths, command output and, occasionally, secrets that
were pasted into a session. Duck Pond shows short excerpts of that text on cards and tags.
Redaction is **on by default**: `theme.redact` masks strings that look like API keys, bearer
tokens and long random identifiers, and truncates every excerpt. Press `R` in the viewport or
use the sidebar to turn it off. Kiosk mode on a shared screen should keep it on.

Renders and screenshots written to `out/` may contain that text. `out/` is git-ignored; check
before sharing one.

## Reporting a vulnerability

If you find a way for Duck Pond to leak, write or execute something it should not (for
example a crafted transcript line that breaks out of the parser, or redaction missing a
class of secret), please report it privately rather than in a public issue:

- use GitHub's **Report a vulnerability** button on the repository's Security tab, or
- contact the maintainer directly through their GitHub profile.

Include what you saw, how to reproduce it (a minimal redacted transcript is ideal) and the
Blender and Duck Pond versions. You will get an acknowledgement within a week. Fixes ship as
a patch release and are noted in `CHANGELOG.md`; you will be credited unless you prefer not
to be.

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x | yes |
| 0.1.x | no |
