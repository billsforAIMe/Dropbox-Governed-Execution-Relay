#!/bin/bash
set -euo pipefail
umask 077
PATH='/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'
export PATH
unset BASH_ENV ENV CDPATH GLOBIGNORE 2>/dev/null || true

LABEL='com.brettmacpro.chatgpt.dropbox-governed-execution-relay'
STATE="$HOME/ChatGPT/State/Tools/Dropbox Governed Execution Relay"
IDENTITY="$STATE/delivered-identity.json"
BINDING="$STATE/runtime-binding.json"
LA_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

hash_file() {
  local p="$1"
  if [ -f "$p" ] && [ ! -L "$p" ]; then
    /usr/bin/shasum -a 256 "$p" | /usr/bin/awk '{print $1}'
  else
    printf 'ABSENT_OR_UNSAFE'
  fi
}

emit_file() {
  local key="$1" p="$2"
  if [ -f "$p" ] && [ ! -L "$p" ]; then
    printf '%s_path=%s\n' "$key" "$p"
    printf '%s_sha256=%s\n' "$key" "$(hash_file "$p")"
    printf '%s_mode=%s\n' "$key" "$(/usr/bin/stat -f '%Sp' "$p" 2>/dev/null || printf UNKNOWN)"
  else
    printf '%s_path=%s\n' "$key" "$p"
    printf '%s_status=ABSENT_OR_UNSAFE\n' "$key"
  fi
}

find_fixed_exe() {
  local p
  for p in "$@"; do
    if [ -f "$p" ] && [ ! -L "$p" ] && [ -x "$p" ]; then
      printf '%s\n' "$p"
      return 0
    fi
  done
  return 1
}

printf 'DGER_GEN3_MAC_QUALIFY_V1\n'
printf 'user=%s\n' "$(/usr/bin/id -un)"
printf 'uid=%s\n' "$(/usr/bin/id -u)"
printf 'home=%s\n' "$HOME"
printf 'kernel=%s\n' "$(/usr/bin/uname -srm)"
printf 'state_dir=%s\n' "$STATE"

GH="$(find_fixed_exe /opt/homebrew/bin/gh /usr/local/bin/gh /usr/bin/gh || true)"
GITSTORAGE="$(find_fixed_exe /usr/local/bin/gitstorage /opt/homebrew/bin/gitstorage "$HOME/.local/bin/gitstorage" || true)"
GOD="$(find_fixed_exe /usr/local/bin/governed-offline-deployer /opt/homebrew/bin/governed-offline-deployer || true)"
PYRUNWAY="$(find_fixed_exe /usr/local/bin/pyrunway /opt/homebrew/bin/pyrunway || true)"

for spec in "gh:$GH" "gitstorage:$GITSTORAGE" "god:$GOD" "pyrunway:$PYRUNWAY"; do
  key="${spec%%:*}"; val="${spec#*:}"
  if [ -n "$val" ]; then
    printf '%s_path=%s\n' "$key" "$val"
    printf '%s_sha256=%s\n' "$key" "$(hash_file "$val")"
  else
    printf '%s_status=ABSENT\n' "$key"
  fi
done

emit_file delivered_identity "$IDENTITY"
emit_file runtime_binding "$BINDING"
emit_file launchagent_plist "$LA_PLIST"

if [ -f "$IDENTITY" ] && [ ! -L "$IDENTITY" ]; then
  for k in runtime_root candidate_sha candidate_tree; do
    v="$(/usr/bin/plutil -extract "$k" raw -o - "$IDENTITY" 2>/dev/null || true)"
    printf 'delivered_%s=%s\n' "$k" "$v"
  done
fi

if [ -f "$BINDING" ] && [ ! -L "$BINDING" ]; then
  for k in moh_home gtg_endpoint gtg_token_file allow_insecure_localhost_gtg; do
    v="$(/usr/bin/plutil -extract "$k" raw -o - "$BINDING" 2>/dev/null || true)"
    printf 'binding_%s=%s\n' "$k" "$v"
  done
  TOKEN_FILE="$(/usr/bin/plutil -extract gtg_token_file raw -o - "$BINDING" 2>/dev/null || true)"
  if [ -n "$TOKEN_FILE" ]; then
    printf 'gtg_token_file_path=%s\n' "$TOKEN_FILE"
    if [ -f "$TOKEN_FILE" ] && [ ! -L "$TOKEN_FILE" ]; then
      printf 'gtg_token_file_status=PRESENT\n'
      printf 'gtg_token_file_mode=%s\n' "$(/usr/bin/stat -f '%Sp' "$TOKEN_FILE" 2>/dev/null || printf UNKNOWN)"
    else
      printf 'gtg_token_file_status=ABSENT_OR_UNSAFE\n'
    fi
  fi
fi

RUNTIME_ROOT="$(/usr/bin/plutil -extract runtime_root raw -o - "$IDENTITY" 2>/dev/null || true)"
if [ -n "$RUNTIME_ROOT" ] && [ -d "$RUNTIME_ROOT" ] && [ ! -L "$RUNTIME_ROOT" ]; then
  printf 'runtime_root_status=PRESENT\n'
  emit_file runtime_launcher "$RUNTIME_ROOT/launcher/dropbox-governed-execution-relay"
  emit_file runtime_entry "$RUNTIME_ROOT/scripts/dger.py"
  emit_file runtime_release "$RUNTIME_ROOT/GOVERNED_RELEASE.json"
else
  printf 'runtime_root_status=ABSENT_OR_UNSAFE\n'
fi

if [ -f "$LA_PLIST" ] && [ ! -L "$LA_PLIST" ]; then
  printf 'launchagent_program=%s\n' "$(/usr/bin/plutil -extract ProgramArguments.0 raw -o - "$LA_PLIST" 2>/dev/null || true)"
fi
if /bin/launchctl print "gui/$(/usr/bin/id -u)/$LABEL" >/tmp/dger-launchctl-probe.$$ 2>&1; then
  printf 'launchagent_loaded=true\n'
  /usr/bin/grep -E '^[[:space:]]*(state|pid|last exit code) =' /tmp/dger-launchctl-probe.$$ | /usr/bin/head -n 12 | /usr/bin/sed 's/^[[:space:]]*/launchagent_/' || true
else
  printf 'launchagent_loaded=false\n'
fi
/bin/rm -f /tmp/dger-launchctl-probe.$$

if [ -n "$GH" ]; then
  if "$GH" auth status -h github.com >/dev/null 2>&1; then
    printf 'gh_auth_github=true\n'
  else
    printf 'gh_auth_github=false\n'
  fi
  if OUT="$("$GH" api 'repos/billsforAIMe/Dropbox-Governed-Execution-Relay/keys?per_page=100' --jq 'length' 2>/dev/null)"; then
    printf 'gh_can_read_deploy_keys=true\n'
    printf 'existing_deploy_key_count=%s\n' "$OUT"
  else
    printf 'gh_can_read_deploy_keys=false\n'
  fi
fi

if [ -n "$GOD" ]; then
  if OUT="$($GOD contract-info 2>&1)"; then
    printf 'god_contract_info=PASS\n'
    printf '%s\n' "$OUT" | /usr/bin/head -c 4096 | /usr/bin/sed 's/^/god_contract:/'
    printf '\n'
  else
    rc=$?
    printf 'god_contract_info=FAIL:%s\n' "$rc"
    printf '%s\n' "$OUT" | /usr/bin/head -c 2048 | /usr/bin/sed 's/^/god_contract_error:/'
    printf '\n'
  fi
fi

printf 'god_candidate_files_begin\n'
for root in "$STATE" "$HOME/ChatGPT/Tools/Dropbox Governed Execution Relay" "$HOME/ChatGPT/State/Tools"; do
  [ -d "$root" ] || continue
  /usr/bin/find "$root" -maxdepth 5 -type f \( -iname '*god*profile*.json' -o -iname '*consumer*profile*.json' -o -iname '*adapter*.py' -o -iname '*adapter*.command' \) -print 2>/dev/null | /usr/bin/head -n 100 || true
done
printf 'god_candidate_files_end\n'

for repo in "$HOME/ChatGPT/Git/Tools/Dropbox Governed Execution Relay.git" "$HOME/ChatGPT/Tools/Dropbox Governed Execution Relay"; do
  if [ -d "$repo" ]; then
    printf 'local_dger_repo=%s\n' "$repo"
    if /usr/bin/git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
      printf 'local_dger_head=%s\n' "$(/usr/bin/git -C "$repo" rev-parse HEAD 2>/dev/null || true)"
      printf 'local_dger_main=%s\n' "$(/usr/bin/git -C "$repo" rev-parse refs/heads/main 2>/dev/null || true)"
      printf 'local_dger_candidate_present=%s\n' "$(/usr/bin/git -C "$repo" cat-file -e '48da71bb021c51043da841e9e8f4a49c09ba2ef7^{commit}' 2>/dev/null && printf true || printf false)"
    fi
  fi
done

printf 'ssh_keygen=%s\n' "$(find_fixed_exe /usr/bin/ssh-keygen /bin/ssh-keygen || true)"
printf 'ssh_agent=%s\n' "$(find_fixed_exe /usr/bin/ssh-agent /bin/ssh-agent || true)"
printf 'ssh_add=%s\n' "$(find_fixed_exe /usr/bin/ssh-add /bin/ssh-add || true)"
printf 'git=%s\n' "$(find_fixed_exe /usr/bin/git /opt/homebrew/bin/git || true)"
printf 'DGER_GEN3_MAC_QUALIFY_DONE\n'
