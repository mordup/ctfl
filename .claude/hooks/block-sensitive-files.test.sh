#!/usr/bin/env bash
# Exercises .claude/hooks/block-sensitive-files.sh. Sensitive test strings live
# only in this file, never in the command that invokes it, because the hook now
# inspects Bash command text.
H="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/block-sensitive-files.sh"

verdict() { # $1 = json payload -> reason, or ALLOWED
  local out
  out="$(printf '%s' "$1" | bash "$H" 2>&1)"
  if [ -z "$out" ]; then printf 'ALLOWED'
  else printf '%s' "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecisionReason // "MALFORMED: "+.' 2>/dev/null || printf 'RAW: %s' "$out")"
  fi
}
bash_payload() { jq -nc --arg c "$1" '{tool_name:"Bash",tool_input:{command:$c}}'; }
read_payload() { jq -nc --arg p "$1" '{tool_name:"Read",tool_input:{file_path:$p}}'; }

fail=0
expect_block() { r="$(verdict "$2")"
  if [ "$r" = ALLOWED ]; then printf '  FAIL allowed  %-42s\n' "$1"; fail=1
  else printf '  ok   blocked  %-42s %s\n' "$1" "$r"; fi; }
expect_allow() { r="$(verdict "$2")"
  if [ "$r" = ALLOWED ]; then printf '  ok   allowed  %-42s\n' "$1"
  else printf '  FAIL blocked  %-42s %s\n' "$1" "$r"; fail=1; fi; }

echo "=== Bash: the loophole this change closes ==="
expect_block 'cat ~/.claude/.credentials.json'  "$(bash_payload 'cat ~/.claude/.credentials.json')"
expect_block 'cat <home>/.ssh/id_rsa'           "$(bash_payload "cat $HOME/.ssh/id_rsa")"
expect_block 'bash -c "cat ~/.ssh/id_ed25519"'  "$(bash_payload 'bash -c "cat ~/.ssh/id_ed25519"')"
expect_block 'less ~/.netrc'                    "$(bash_payload 'less ~/.netrc')"
expect_block 'cat "$HOME/.pgpass"'              "$(bash_payload 'cat "$HOME/.pgpass"')"
expect_block 'strings ~/.gnupg/pubring.kbx'     "$(bash_payload 'strings ~/.gnupg/pubring.kbx')"
expect_block 'grep ~/.cache/ctfl/oauth_x.json'  "$(bash_payload 'grep -r x ~/.cache/ctfl/oauth_x.json')"
expect_block 'cp ~/.ssh/id_rsa /tmp/x'          "$(bash_payload 'cp ~/.ssh/id_rsa /tmp/x')"
expect_block 'tar czf out.tgz ~/.gnupg'         "$(bash_payload 'tar czf out.tgz ~/.gnupg')"

echo
echo "=== file tools: unchanged behaviour ==="
expect_block 'Read <home>/.claude/.credentials.json' "$(read_payload "$HOME/.claude/.credentials.json")"
expect_block 'Read ~/.ssh/id_ecdsa'                  "$(read_payload '~/.ssh/id_ecdsa')"

echo
echo "=== must stay allowed (false-positive check) ==="
expect_allow 'python -m pytest tests/ -q'       "$(bash_payload 'python -m pytest tests/ -q')"
expect_allow 'git commit -m "fix credentials"'  "$(bash_payload 'git commit -m "fix credentials handling"')"
expect_allow 'ls ~/.ssh/'                       "$(bash_payload 'ls ~/.ssh/')"
expect_allow 'grep -rn credentials ctfl/'       "$(bash_payload 'grep -rn credentials ctfl/')"
expect_allow 'cat ctfl/providers/oauth.py'      "$(bash_payload 'cat ctfl/providers/oauth.py')"
expect_allow 'rm /tmp/ctfl-v2.8.0.tar.gz'       "$(bash_payload 'rm /tmp/ctfl-v2.8.0.tar.gz')"
expect_allow 'gh release view v2.8.0'           "$(bash_payload 'gh release view v2.8.0')"
expect_allow 'Read ctfl/popup.py'               "$(read_payload 'ctfl/popup.py')"

echo
[ "$fail" -eq 0 ] && echo "ALL PASS" || echo "SOME FAILED"
exit "$fail"
