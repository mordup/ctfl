#!/usr/bin/env python3
"""PreToolUse guard — blocks access to sensitive files by path pattern.

Complements the static deny rules in settings.json by covering a wider
pattern set (SSH keys, GPG, .netrc, .pgpass, OAuth caches).

Covers two tool shapes:
  Read/Write/Edit/Grep/Glob — tool_input.file_path / .path is matched directly.
  Bash                      — the command is parsed with shlex and every token
                              is matched with the same patterns, so
                              `cat ~/.ssh/id_rsa` is stopped like Read would be.

shlex parsing is what keeps the two failure modes apart. `cat ~/'.ssh'/id_rsa`
comes back as the single token `~/.ssh/id_rsa` and is blocked, while
`git commit -m "note on ~/.netrc handling"` stays one quoted argument that
matches nothing. A quoted argument is matched whole and never re-split on
whitespace, so a nested shell (`bash -c "cat ~/.ssh/id_rsa"`) is still caught;
the cost is that an argument *ending* exactly at a sensitive path
(`-m "fix ~/.netrc"`) is blocked as though it were the path itself.

This is a guardrail against accidental or injected access, not a sandbox:
matching is string-based, does not follow symlinks, and a command that
deliberately obfuscates a path (concatenation, encoding, variables resolved at
runtime) can still get through. Treat it as defence in depth behind the
permission allowlist, not as a boundary.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from fnmatch import fnmatch

HOME = os.path.expanduser("~")

# Single source of truth for what counts as sensitive. Matched against a whole
# token with ~ and $VAR expanded and any trailing slash removed, so `~/.ssh/`,
# `~/.ssh` and `$HOME/.ssh` all land on the same rule.
#
# The directory arms matter as much as the file ones: without them `tar czf
# out.tgz ~/.ssh` and `cd ~/.ssh && cat id_rsa` both walk straight past.
PATH_RULES = [
    ("*/.credentials.json", "blocked: Claude OAuth credentials"),
    ("*/.cache/ctfl", "blocked: CTFL OAuth/cookie cache"),
    ("*/.cache/ctfl/*", "blocked: CTFL OAuth/cookie cache"),
    # The whole ~/.ssh tree, not just key filenames — known_hosts and config
    # are not something an agent needs, and enumerating key names is what let
    # the directory form through before.
    ("*/.ssh", "blocked: SSH directory"),
    ("*/.ssh/*", "blocked: SSH directory"),
    ("*/.netrc", "blocked: credential file"),
    ("*/.pgpass", "blocked: credential file"),
    ("*/.gnupg", "blocked: GPG keyring"),
    ("*/.gnupg/*", "blocked: GPG keyring"),
    # $HOME/.claude only, and only the directory itself: this repo has its own
    # .claude/, and the global CLAUDE.md, settings and agents under ~/.claude
    # are read legitimately. The secret inside it is covered by the
    # */.credentials.json rule above.
    (f"{HOME}/.claude", "blocked: Claude home directory"),
]

# Applied to tokens with no slash, which is where a `cd`-then-read lands:
# `cd ~/.ssh && cat id_rsa` splits into a directory token and a bare filename,
# and only the pair of rule sets together stops both halves.
NAME_RULES = [
    (".credentials.json", "blocked: Claude OAuth credentials"),
    (".netrc", "blocked: credential file"),
    (".pgpass", "blocked: credential file"),
    (".ssh", "blocked: SSH directory"),
    (".gnupg", "blocked: GPG keyring"),
    ("id_rsa*", "blocked: SSH key"),
    ("id_ed25519*", "blocked: SSH key"),
    ("id_ecdsa*", "blocked: SSH key"),
]


def reason_for(token: str) -> str | None:
    """Return the denial reason for a token, or None if it is not sensitive."""
    expanded = os.path.expandvars(os.path.expanduser(token.strip()))
    candidate = expanded.rstrip("/") or expanded
    if not candidate:
        return None
    for pattern, reason in PATH_RULES:
        if fnmatch(candidate, pattern):
            return reason
    if "/" not in candidate:
        for pattern, reason in NAME_RULES:
            if fnmatch(candidate, pattern):
                return reason
    return None


def tokenize(command: str) -> list[str]:
    """Split a command the way a shell would, keeping quoted args intact."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        # Unbalanced quotes and friends — fall back to a whitespace split so a
        # malformed command is scanned more loosely, not skipped.
        return command.split()


def deny(reason: str) -> int:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    return 0


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        # Fail closed, but say why: exit 2 blocks the call and hands stderr
        # back as the reason, so a silent exit would deny every tool call with
        # a blank explanation.
        print("block-sensitive-files: hook input was not valid JSON", file=sys.stderr)
        return 2

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    path = tool_input.get("file_path") or tool_input.get("path")
    if path:
        reason = reason_for(str(path))
        return deny(reason) if reason else 0

    command = tool_input.get("command")
    if command:
        for token in tokenize(str(command)):
            reason = reason_for(token)
            if reason:
                return deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
