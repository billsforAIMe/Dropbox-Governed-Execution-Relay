#!/bin/bash -p
PATH=/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin
export PATH
IFS=$' \t\n'
unset BASH_ENV ENV CDPATH GLOBIGNORE GH_TOKEN GITHUB_TOKEN GH_ENTERPRISE_TOKEN GITHUB_ENTERPRISE_TOKEN 2>/dev/null || true
set -euo pipefail
umask 077

REPO='billsforAIMe/Dropbox-Governed-Execution-Relay'
REPO_ID='1351496555'
RULESET_ID='21965737'
OLD='66056fb7e5a545a6f9532ed00d13008ce0bd2db4'
CAND='fbac917617fb6c6c2a52d3dd1f152756a58bcdae'
TREE='89221e30ab072e959b9c5a03b035dcd2d8e9950a'
CBRANCH='builder/gen4-runtime-composition'
HTTPS='https://github.com/billsforAIMe/Dropbox-Governed-Execution-Relay.git'
SSH='git@github.com:billsforAIMe/Dropbox-Governed-Execution-Relay.git'
STAMP="$(/bin/date -u +%Y%m%dT%H%M%SZ)"
STATE="$HOME/ChatGPT/State/Tools/Dropbox Governed Execution Relay/GOVERNANCE"
REC="$STATE/ORDINARY_SOURCE_PUBLICATION_WRITER.json"
OUT="$HOME/Library/CloudStorage/Dropbox/Software/NSP - Temporary Files/Post94 Cross-Tool Status"
[ -d "$OUT" ] || OUT="$HOME/Dropbox/Software/NSP - Temporary Files/Post94 Cross-Tool Status"
[ -d "$OUT" ] || OUT="$HOME/Downloads"
LOG="$OUT/DGER_PR18_SOURCE_PUBLICATION_${STAMP}.log"
WORK="$(/usr/bin/mktemp -d /private/tmp/dger-pr18-publish.XXXXXX)"
GH="$(command -v gh || true)"; JQ="$(command -v jq || true)"
[ -n "$GH" ] && [ -n "$JQ" ] || { echo 'DGER_PUBLICATION_REQUIRED_CLI_MISSING'; exit 69; }

api() { "$GH" api --hostname github.com "$@"; }
write_keys() { api "repos/$REPO/keys?per_page=100" | "$JQ" -c '[.[]|select(.read_only==false)]'; }
zero_keys() { [ "$(write_keys | "$JQ" 'length')" -eq 0 ]; }
remote_main() { /usr/bin/git ls-remote "$HTTPS" refs/heads/main | /usr/bin/awk 'NF==2 && $2=="refs/heads/main"{print $1}'; }

recover_owned_writer() {
  [ -f "$REC" ] || { zero_keys || return 91; return 0; }
  title="$($JQ -er '.title' "$REC")" || return 92
  pub="$($JQ -er '.public_key' "$REC")" || return 92
  rid="$($JQ -r '.key_id // empty' "$REC")"
  keys="$(write_keys)" || return 93
  match="$(printf '%s' "$keys" | "$JQ" --arg t "$title" --arg p "$pub" --arg rid "$rid" '[.[]|select((($rid!="") and ((.id|tostring)==$rid)) or ((.title==$t) and (.key==$p)))]')"
  unknown="$(printf '%s' "$keys" | "$JQ" --arg t "$title" --arg p "$pub" --arg rid "$rid" '[.[]|select((((($rid!="") and ((.id|tostring)==$rid)) or ((.title==$t) and (.key==$p)))|not))]|length')"
  [ "$unknown" -eq 0 ] || return 94
  n="$(printf '%s' "$match" | "$JQ" 'length')"; [ "$n" -le 1 ] || return 95
  if [ "$n" -eq 1 ]; then
    kid="$(printf '%s' "$match" | "$JQ" -r '.[0].id')"
    api --method DELETE "repos/$REPO/keys/$kid" >/dev/null || return 96
  fi
  zero_keys || return 97
  /bin/rm -f "$REC"; /bin/sync
  return 0
}

cleanup() {
  rc=$?
  trap - EXIT INT TERM HUP
  cleanup_rc=0
  if [ -f "$REC" ]; then recover_owned_writer || cleanup_rc=$?; fi
  /bin/rm -rf "$WORK" 2>/dev/null || true
  if [ "$cleanup_rc" -ne 0 ]; then
    echo "DGER_PUBLICATION_WRITER_CLEANUP_REQUIRED rc=$cleanup_rc record=$REC"
    rc=98
  fi
  if [ "$rc" -eq 0 ]; then echo 'DGER_PR18_SOURCE_PUBLICATION_COMMAND_PASS'; else echo "DGER_PR18_SOURCE_PUBLICATION_COMMAND_FAIL rc=$rc"; fi
  echo "RESULT_LOG=$LOG"
  exit "$rc"
}
trap cleanup EXIT INT TERM HUP
exec > >(/usr/bin/tee -a "$LOG") 2>&1

echo "START_UTC=$STAMP"
echo "EXPECTED_MAIN=$OLD"
echo "CANDIDATE=$CAND"
echo "CANDIDATE_TREE=$TREE"
echo 'CLAIM_SCOPE=SOURCE_PUBLICATION_ONLY'
echo 'DEPLOYMENT_ACTIVATION_REGISTRY_RUNTIME=NOT_CLAIMED'

[ "$(api user | "$JQ" -r '.login')" = 'billsforAIMe' ] || { echo 'GITHUB_ADMIN_IDENTITY_MISMATCH'; exit 70; }
/bin/mkdir -p "$STATE"
recover_owned_writer || { echo 'ABANDONED_WRITER_RECOVERY_BLOCKED'; exit 71; }
echo 'ABANDONED_WRITER_RECOVERY=PASS'

check_controls() {
  repo_json="$(api "repos/$REPO")"
  printf '%s' "$repo_json" | "$JQ" -e --argjson id "$REPO_ID" '.id==$id and .full_name=="billsforAIMe/Dropbox-Governed-Execution-Relay" and .default_branch=="main" and (.archived|not) and (.disabled|not)' >/dev/null
  [ "$(api "repos/$REPO/rulesets?per_page=100" | "$JQ" -c '[.[].id]|sort')" = "[$RULESET_ID]" ]
  api "repos/$REPO/rulesets/$RULESET_ID" | "$JQ" -e --argjson id "$RULESET_ID" '
    .id==$id and .name=="DGER authoritative selector guard" and .target=="branch" and .enforcement=="active" and
    .conditions.ref_name.include==["refs/heads/main"] and .conditions.ref_name.exclude==[] and
    ([.rules[].type]|sort)==["creation","deletion","non_fast_forward","update"] and
    .bypass_actors==[{"actor_id":null,"actor_type":"DeployKey","bypass_mode":"always"}] and
    .current_user_can_bypass=="never"' >/dev/null
  zero_keys
}
check_controls || { echo 'PROVIDER_CONTROL_TUPLE_MISMATCH'; exit 72; }
echo 'PROVIDER_CONTROLS_PRE=PASS'

/usr/bin/git -C "$WORK" init -q
/usr/bin/git -C "$WORK" remote add origin "$HTTPS"
/usr/bin/git -C "$WORK" fetch -q --no-tags origin "+refs/heads/main:refs/remotes/origin/main" "+refs/heads/$CBRANCH:refs/remotes/origin/candidate"
M="$(/usr/bin/git -C "$WORK" rev-parse refs/remotes/origin/main)"
C="$(/usr/bin/git -C "$WORK" rev-parse refs/remotes/origin/candidate)"
T="$(/usr/bin/git -C "$WORK" rev-parse "$CAND^{tree}")"
[ "$M" = "$OLD" ] || [ "$M" = "$CAND" ] || { echo "DGER_MAIN_MOVED_REASSESS observed=$M"; exit 73; }
[ "$C" = "$CAND" ] || { echo "DGER_CANDIDATE_BRANCH_MOVED observed=$C"; exit 73; }
[ "$T" = "$TREE" ] || { echo "DGER_CANDIDATE_TREE_MISMATCH observed=$T"; exit 73; }
/usr/bin/git -C "$WORK" merge-base --is-ancestor "$OLD" "$CAND"
/usr/bin/git -C "$WORK" fsck --strict --no-dangling >/dev/null
echo 'CANDIDATE_IDENTITY_ANCESTRY_INTEGRITY=PASS'

NOW="$(remote_main)"
if [ "$NOW" = "$CAND" ]; then
  zero_keys || { echo 'SOURCE_ALREADY_CANDIDATE_BUT_WRITE_KEY_PRESENT'; exit 74; }
  echo 'SOURCE_ALREADY_EXACT_CANDIDATE=PASS'
else
  [ "$NOW" = "$OLD" ] || { echo "STALE_PREDECESSOR observed=$NOW"; exit 75; }
  check_controls || { echo 'PROVIDER_CONTROL_TUPLE_CHANGED_BEFORE_WRITER'; exit 76; }
  [ "$(remote_main)" = "$OLD" ] || { echo 'MAIN_MOVED_BEFORE_WRITER_CREATE'; exit 75; }

  KEY="$WORK/publisher_ed25519"
  /usr/bin/ssh-keygen -q -t ed25519 -N '' -C "DGER_PR18_SOURCE_PUBLICATION-$STAMP" -f "$KEY"
  PUB="$(cat "$KEY.pub")"
  SIG="$(printf '%s' "$PUB" | /usr/bin/shasum -a 256 | /usr/bin/awk '{print substr($1,1,12)}')"
  TITLE="DGER_PR18_SOURCE_PUBLICATION-$STAMP-$SIG"
  "$JQ" -n --arg repo "$REPO" --arg title "$TITLE" --arg pub "$PUB" --arg cand "$CAND" --arg old "$OLD" '{schema:"dger-ordinary-source-publication-writer/v1",repo:$repo,title:$title,public_key:$pub,key_id:null,candidate:$cand,expected_main:$old}' > "$REC.tmp"
  /bin/chmod 600 "$REC.tmp"; /bin/mv "$REC.tmp" "$REC"; /bin/sync
  CREATED="$("$JQ" -n --arg title "$TITLE" --arg key "$PUB" '{title:$title,key:$key,read_only:false}' | api --method POST "repos/$REPO/keys" --input -)"
  KID="$(printf '%s' "$CREATED" | "$JQ" -er '.id')"
  "$JQ" --argjson id "$KID" '.key_id=$id' "$REC" > "$REC.tmp"; /bin/chmod 600 "$REC.tmp"; /bin/mv "$REC.tmp" "$REC"; /bin/sync
  [ "$(write_keys | "$JQ" -r 'length')" -eq 1 ] && [ "$(write_keys | "$JQ" -r '.[0].id')" = "$KID" ] || { echo 'ACT_SCOPED_DEPLOY_KEY_SET_MISMATCH'; exit 77; }
  echo 'ACT_SCOPED_DEPLOY_KEY_CREATED=PASS'

  check_key_controls() {
    api "repos/$REPO/rulesets/$RULESET_ID" | "$JQ" -e '.enforcement=="active" and .current_user_can_bypass=="never" and .bypass_actors==[{"actor_id":null,"actor_type":"DeployKey","bypass_mode":"always"}]' >/dev/null
    [ "$(write_keys | "$JQ" -r 'length')" -eq 1 ] && [ "$(write_keys | "$JQ" -r '.[0].id')" = "$KID" ]
  }
  check_key_controls || { echo 'PROVIDER_CONTROL_TUPLE_CHANGED_AT_CAS'; exit 78; }
  [ "$(remote_main)" = "$OLD" ] || { echo 'MAIN_MOVED_BEFORE_CAS'; exit 75; }
  KNOWN="$WORK/known_hosts"
  printf '%s\n' 'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' > "$KNOWN"
  /bin/chmod 600 "$KNOWN"
  export GIT_SSH_COMMAND="/usr/bin/ssh -i $KEY -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN"
  /usr/bin/git -C "$WORK" remote add governed "$SSH"
  set +e
  /usr/bin/git -C "$WORK" push "--force-with-lease=refs/heads/main:$OLD" governed "$CAND:refs/heads/main"
  PUSH_RC=$?
  set -e
  unset GIT_SSH_COMMAND
  POST="$(remote_main)"
  echo "CAS_PUSH_RC=$PUSH_RC"
  echo "OBSERVED_MAIN_POST_CAS=$POST"
  [ "$POST" = "$CAND" ] || { echo 'SOURCE_CAS_NOT_PROVEN_APPLIED'; exit 79; }
  echo 'EXACT_OLD_CAS_AND_MAIN_READBACK=PASS'

  api --method DELETE "repos/$REPO/keys/$KID" >/dev/null
  zero_keys || { echo 'DEPLOY_KEY_DELETE_OR_ZERO_KEY_PROOF_FAILED'; exit 80; }
  /bin/rm -f "$REC"; /bin/sync
  echo 'ACT_SCOPED_DEPLOY_KEY_DESTROYED=PASS'
fi

# Fresh positive destination verification after writer removal.
[ "$(remote_main)" = "$CAND" ] || { echo 'POSITIVE_READBACK_MAIN_MISMATCH'; exit 81; }
READ="$WORK/readback"; /bin/mkdir "$READ"; /usr/bin/git -C "$READ" init -q
/usr/bin/git -C "$READ" fetch -q --no-tags "$HTTPS" refs/heads/main
RT="$(/usr/bin/git -C "$READ" rev-parse 'FETCH_HEAD^{tree}')"
[ "$RT" = "$TREE" ] || { echo "POSITIVE_READBACK_TREE_MISMATCH observed=$RT"; exit 81; }
check_controls || { echo 'PROVIDER_CONTROL_TUPLE_OR_ZERO_KEYS_POST_MISMATCH'; exit 82; }
echo "POSITIVE_READBACK_MAIN=$CAND"
echo "POSITIVE_READBACK_TREE=$TREE"
echo 'ZERO_STANDING_WRITE_DEPLOY_KEYS=PASS'
echo 'PROVIDER_CONTROLS_POST=PASS'
echo 'DEPLOYMENT_ACTIVATION_REGISTRY_RUNTIME=NOT_CLAIMED'
echo 'DGER_PR18_SOURCE_PUBLICATION_PASS'
