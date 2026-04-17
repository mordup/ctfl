#!/usr/bin/env bash
# PreToolUse guard — blocks reads/writes on sensitive files by path
# pattern. Complements the static deny rules in settings.json by
# covering a wider pattern set (SSH keys, GPG, .netrc, .pgpass). Path
# matching is string-based and does not follow symlinks.

command -v jq >/dev/null 2>&1 || exit 2  # fail closed if jq is missing

input="$(cat 2>/dev/null || true)"
path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null)"
[ -z "$path" ] && exit 0

# Expand leading ~ so patterns match consistently.
path="${path/#\~/$HOME}"

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

case "$path" in
  */.credentials.json)
    block "blocked: Claude OAuth credentials" ;;
  */.cache/ctfl/*.json|*/.cache/ctfl/*.txt)
    block "blocked: CTFL OAuth/cookie cache" ;;
  */.ssh/id_*|*/.ssh/*_rsa|*/.ssh/*_rsa.pub|*/.ssh/*_ed25519|*/.ssh/*_ed25519.pub|*/.ssh/*_ecdsa|*/.ssh/*_ecdsa.pub)
    block "blocked: SSH key" ;;
  */.netrc|*/.pgpass)
    block "blocked: credential file" ;;
  */.gnupg/*)
    block "blocked: GPG keyring" ;;
esac

exit 0
