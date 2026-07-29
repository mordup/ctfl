#!/usr/bin/env bash
# PreToolUse guard — blocks access to sensitive files by path pattern.
# Complements the static deny rules in settings.json by covering a wider
# pattern set (SSH keys, GPG, .netrc, .pgpass).
#
# Covers two tool shapes:
#   Read/Write/Edit — tool_input.file_path is matched directly.
#   Bash            — every path-looking token in tool_input.command is
#                     pulled out and matched with the same patterns, so
#                     `cat ~/.ssh/id_rsa` is stopped like Read would be.
#
# This is a guardrail against accidental or injected access, not a sandbox:
# matching is string-based, does not follow symlinks, and a command that
# deliberately obfuscates a path (concatenation, encoding, variables
# resolved at runtime) can still get through. Treat it as defence in depth
# behind the permission allowlist, not as a boundary.

command -v jq >/dev/null 2>&1 || exit 2  # fail closed if jq is missing

input="$(cat 2>/dev/null || true)"

block() {
  jq -n --arg reason "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

# Single source of truth for what counts as sensitive. Takes an absolute or
# ~-relative path and blocks if it matches; returns otherwise.
check_path() {
  local p="${1/#\~/$HOME}"
  case "$p" in
    */.credentials.json)
      block "blocked: Claude OAuth credentials" ;;
    */.cache/ctfl/*.json|*/.cache/ctfl/*.txt)
      block "blocked: CTFL OAuth/cookie cache" ;;
    */.ssh/id_*|*/.ssh/*_rsa|*/.ssh/*_rsa.pub|*/.ssh/*_ed25519|*/.ssh/*_ed25519.pub|*/.ssh/*_ecdsa|*/.ssh/*_ecdsa.pub)
      block "blocked: SSH key" ;;
    */.netrc|*/.pgpass)
      block "blocked: credential file" ;;
    */.gnupg|*/.gnupg/*)
      block "blocked: GPG keyring" ;;
  esac
}

path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null)"
if [ -n "$path" ]; then
  check_path "$path"
  exit 0
fi

command_line="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)"
if [ -n "$command_line" ]; then
  # Split on shell separators and quote characters so a quoted or
  # =-assigned path still surfaces as its own token, then test the ones
  # that look like paths. Unresolved variables are left as-is: a literal
  # "$HOME/.netrc" still matches the */.netrc pattern.
  # `|| [ -n "$token" ]` matters: tr leaves no trailing newline, so a plain
  # read drops the final token — which is exactly where the path usually is
  # (`cat ~/.ssh/id_rsa`).
  while IFS= read -r token || [ -n "$token" ]; do
    case "$token" in
      */*|'~'/*) check_path "$token" ;;
    esac
  done < <(printf '%s' "$command_line" | tr -s ' \t\n"'\''`;|&()<>=' '\n')
fi

exit 0
