#!/usr/bin/env bash
# Exercises .claude/hooks/block-sensitive-files.py. Sensitive test strings live
# only in this file, never in the command that invokes it, because the hook now
# inspects Bash command text.
H="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/block-sensitive-files.py"

# Only the payload builders below need jq; the hook itself does not. Without it
# every payload would be empty and the suite would fail for the wrong reason.
command -v jq >/dev/null 2>&1 || { echo "jq is required to build the test payloads" >&2; exit 2; }

verdict() { # $1 = json payload -> reason, or ALLOWED
  local out rc
  out="$(printf '%s' "$1" | python3 "$H" 2>&1)"
  rc=$?
  # A non-zero exit is itself a deny signal to Claude Code, so it must not be
  # read as ALLOWED just because nothing was printed on stdout.
  if [ "$rc" -ne 0 ]; then printf 'EXIT %d: %s' "$rc" "${out:-<no reason given>}"; return; fi
  if [ -z "$out" ]; then printf 'ALLOWED'
  else printf '%s' "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecisionReason // "MALFORMED: "+.' 2>/dev/null || printf 'RAW: %s' "$out")"
  fi
}
bash_payload() { jq -nc --arg c "$1" '{tool_name:"Bash",tool_input:{command:$c}}'; }
read_payload() { jq -nc --arg p "$1" '{tool_name:"Read",tool_input:{file_path:$p}}'; }
grep_payload() { jq -nc --arg p "$1" '{tool_name:"Grep",tool_input:{pattern:".",path:$p}}'; }
glob_payload() { jq -nc --arg p "$1" '{tool_name:"Glob",tool_input:{pattern:$p}}'; }
glob_in_payload() { jq -nc --arg p "$1" --arg d "$2" '{tool_name:"Glob",tool_input:{pattern:$p,path:$d}}'; }
grep_re_payload() { jq -nc --arg r "$1" --arg d "$2" '{tool_name:"Grep",tool_input:{pattern:$r,path:$d}}'; }

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
echo "=== Bash: forms that are not the fully-spelled path ==="
expect_block 'tar czf out.tgz ~/.ssh'           "$(bash_payload 'tar czf out.tgz ~/.ssh')"
expect_block 'ls ~/.ssh/'                       "$(bash_payload 'ls ~/.ssh/')"
expect_block 'cat ~/.ssh/*'                     "$(bash_payload 'cat ~/.ssh/*')"
expect_block 'cd ~/.ssh && cat id_rsa'          "$(bash_payload 'cd ~/.ssh && cat id_rsa')"
expect_block 'cd ~/.claude; cat .credentials'   "$(bash_payload 'cd ~/.claude; cat .credentials.json')"
expect_block "cat ~/'.ssh'/id_rsa"              "$(bash_payload "cat ~/'.ssh'/id_rsa")"
expect_block 'cp -r ~/.claude /tmp/x'           "$(bash_payload 'cp -r ~/.claude /tmp/x')"
expect_block 'tar czf x.tgz ~/.cache/ctfl'      "$(bash_payload 'tar czf x.tgz ~/.cache/ctfl')"

echo
echo "=== file tools: unchanged behaviour ==="
expect_block 'Read <home>/.claude/.credentials.json' "$(read_payload "$HOME/.claude/.credentials.json")"
expect_block 'Read ~/.ssh/id_ecdsa'                  "$(read_payload '~/.ssh/id_ecdsa')"
expect_block 'Grep ~/.ssh/id_rsa'                    "$(grep_payload '~/.ssh/id_rsa')"

echo
echo "=== Glob: the target lives in .pattern, not .path ==="
expect_block 'Glob <home>/.ssh/*'              "$(glob_payload "$HOME/.ssh/*")"
expect_block 'Glob **/.credentials.json'                   "$(glob_payload '**/.credentials.json')"
expect_block 'Glob ~/.gnupg/*'                   "$(glob_payload '~/.gnupg/*')"
expect_block 'Glob .ssh/* (relative)'          "$(glob_payload '.ssh/*')"
expect_block 'Glob *.json in ~/.cache/ctfl'         "$(glob_in_payload '*.json' "$HOME/.cache/ctfl")"

echo
echo "=== Bash: path whose FIRST component is the sensitive dir ==="
expect_block 'cat .ssh/id_rsa'                  "$(bash_payload 'cat .ssh/id_rsa')"
expect_block 'cd ~ && cat .ssh/id_rsa'          "$(bash_payload 'cd ~ && cat .ssh/id_rsa')"
expect_block 'cd ~ && cat .gnupg/pubring.kbx'    "$(bash_payload 'cd ~ && cat .gnupg/pubring.kbx')"
expect_block 'tar czf x.tgz .ssh'              "$(bash_payload 'tar czf x.tgz .ssh')"
expect_block 'cd ~/.claude && cat .credentials.json'         "$(bash_payload 'cd ~/.claude && cat .credentials.json')"

echo
echo "=== must stay allowed (false-positive check) ==="
expect_allow 'python -m pytest tests/ -q'       "$(bash_payload 'python -m pytest tests/ -q')"
expect_allow 'git commit -m "fix credentials"'  "$(bash_payload 'git commit -m "fix credentials handling"')"
expect_allow 'git commit -m "... ~/.netrc ..."' "$(bash_payload 'git commit -m "docs: mention ~/.netrc handling"')"
expect_allow 'echo "see ~/.gnupg" >> README.md' "$(bash_payload 'echo "see ~/.gnupg for keys" >> README.md')"
expect_allow 'cat ~/.claude/CLAUDE.md'          "$(bash_payload 'cat ~/.claude/CLAUDE.md')"
expect_allow 'grep -rn credentials ctfl/'       "$(bash_payload 'grep -rn credentials ctfl/')"
expect_allow 'cat ctfl/providers/oauth.py'      "$(bash_payload 'cat ctfl/providers/oauth.py')"
expect_allow 'rm /tmp/ctfl-v2.8.0.tar.gz'       "$(bash_payload 'rm /tmp/ctfl-v2.8.0.tar.gz')"
expect_allow 'gh release view v2.8.0'           "$(bash_payload 'gh release view v2.8.0')"
expect_allow 'Read ctfl/popup.py'               "$(read_payload 'ctfl/popup.py')"
expect_allow 'Grep regex ".ssh" in ctfl/'      "$(grep_re_payload '.ssh' 'ctfl')"
expect_allow 'Grep regex "id_rsa" in tests/'     "$(grep_re_payload 'id_rsa' 'tests')"
expect_allow 'Glob **/*.py'                     "$(glob_payload '**/*.py')"
expect_allow 'Glob .claude/skills/**/*.md'        "$(glob_payload '.claude/skills/**/*.md')"
expect_allow 'Read .claude/settings.json'         "$(read_payload '.claude/settings.json')"
expect_allow 'cat .claude/settings.json'          "$(bash_payload 'cat .claude/settings.json')"

echo
echo "=== fail-closed path ==="
# Exit 2 blocks the call and hands stderr back as the reason, so an empty
# stderr denies every tool call with a blank explanation.
out="$(printf 'not json' | python3 "$H" 2>&1)"
rc=$?
if [ "$rc" -eq 2 ] && [ -n "$out" ]; then
  printf '  ok   exit 2      %-42s %s\n' 'unparseable input' "$out"
else
  printf '  FAIL             %-42s rc=%s reason=%s\n' 'unparseable input' "$rc" "${out:-<empty>}"
  fail=1
fi

echo
[ "$fail" -eq 0 ] && echo "ALL PASS" || echo "SOME FAILED"
exit "$fail"
