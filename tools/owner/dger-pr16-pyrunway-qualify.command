#!/bin/bash -p
PATH=/usr/bin:/bin
export PATH
IFS=$' \t\n'
unset BASH_ENV ENV CDPATH GLOBIGNORE 2>/dev/null || true
set -euo pipefail
umask 077

EXPECTED_MAIN='224d2f74d44d0328abc71a2451a8a346b0809554'
EXPECTED_CANDIDATE='66056fb7e5a545a6f9532ed00d13008ce0bd2db4'
EXPECTED_TREE='e5a665078356f5c3ba0e7867c253b10293610966'
REPO_URL='https://github.com/billsforAIMe/Dropbox-Governed-Execution-Relay.git'
PYRUNWAY='/usr/local/bin/pyrunway'
STAMP="$(/bin/date -u +%Y%m%dT%H%M%SZ)"
DROPBOX_DIR="$HOME/Library/CloudStorage/Dropbox/Software/NSP - Temporary Files/Post94 Cross-Tool Status"
[ -d "$DROPBOX_DIR" ] || DROPBOX_DIR="$HOME/Dropbox/Software/NSP - Temporary Files/Post94 Cross-Tool Status"
[ -d "$DROPBOX_DIR" ] || DROPBOX_DIR="$HOME/Downloads"
LOG="$DROPBOX_DIR/DGER_PR16_PYRUNWAY_QUALIFICATION_${STAMP}.log"
WORK="$(/usr/bin/mktemp -d /private/tmp/dger-pr16-qual.XXXXXX)"

finish() {
  rc=$?
  trap - EXIT INT TERM HUP
  /bin/rm -rf "$WORK" 2>/dev/null || true
  if [ "$rc" -eq 0 ]; then
    echo 'DGER_PR16_PYRUNWAY_QUALIFICATION_PASS'
  else
    echo "DGER_PR16_PYRUNWAY_QUALIFICATION_FAIL rc=$rc"
  fi
  echo "RESULT_LOG=$LOG"
  exit "$rc"
}
trap finish EXIT INT TERM HUP
exec > >(/usr/bin/tee -a "$LOG") 2>&1

echo "START_UTC=$STAMP"
echo "EXPECTED_MAIN=$EXPECTED_MAIN"
echo "EXPECTED_CANDIDATE=$EXPECTED_CANDIDATE"
echo "EXPECTED_TREE=$EXPECTED_TREE"
echo 'CLAIM_SCOPE=BUILDER_ASSURANCE_ONLY'
echo 'SOURCE_PUBLICATION_DEPLOYMENT_ACTIVATION_RUNTIME_REGISTRY=NOT_CLAIMED'

[ -x "$PYRUNWAY" ] || { echo 'PYRUNWAY_ENVIRONMENT_UNAVAILABLE'; exit 69; }
"$PYRUNWAY" --describe
"$PYRUNWAY" --contract >/dev/null
echo 'PYRUNWAY_RUNTIME_BINDING=PASS'

/usr/bin/git -C "$WORK" init -q repo
/usr/bin/git -C "$WORK/repo" remote add origin "$REPO_URL"
/usr/bin/git -C "$WORK/repo" fetch -q --no-tags --depth=100 origin \
  '+refs/heads/main:refs/remotes/origin/main' \
  '+refs/heads/builder/gen4-gep14-correlation:refs/remotes/origin/candidate'
OBS_MAIN="$(/usr/bin/git -C "$WORK/repo" rev-parse refs/remotes/origin/main)"
OBS_CANDIDATE="$(/usr/bin/git -C "$WORK/repo" rev-parse refs/remotes/origin/candidate)"
OBS_TREE="$(/usr/bin/git -C "$WORK/repo" rev-parse "$OBS_CANDIDATE^{tree}")"
[ "$OBS_MAIN" = "$EXPECTED_MAIN" ] || { echo "DGER_MAIN_MOVED_REASSESS observed=$OBS_MAIN"; exit 75; }
[ "$OBS_CANDIDATE" = "$EXPECTED_CANDIDATE" ] || { echo "DGER_CANDIDATE_MOVED_REASSESS observed=$OBS_CANDIDATE"; exit 75; }
[ "$OBS_TREE" = "$EXPECTED_TREE" ] || { echo "DGER_CANDIDATE_TREE_MISMATCH observed=$OBS_TREE"; exit 75; }
/usr/bin/git -C "$WORK/repo" merge-base --is-ancestor "$EXPECTED_MAIN" "$EXPECTED_CANDIDATE"
/usr/bin/git -C "$WORK/repo" checkout -q --detach "$EXPECTED_CANDIDATE"
/usr/bin/git -C "$WORK/repo" diff --check "$EXPECTED_MAIN..$EXPECTED_CANDIDATE"
echo 'CANDIDATE_IDENTITY_ANCESTRY_DIFF_CHECK=PASS'

cd "$WORK/repo"
"$PYRUNWAY" --standalone tests/run_gen4_assurance.py
echo 'GOVERNED_GEN4_ASSURANCE=PASS'
"$PYRUNWAY" --standalone tests/run_all.py
echo 'GOVERNED_FULL_TEST_DISCOVERY=PASS'
