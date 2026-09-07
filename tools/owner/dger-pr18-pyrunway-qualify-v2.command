#!/bin/bash -p
PATH=/usr/bin:/bin
export PATH
IFS=$' \t\n'
unset BASH_ENV ENV CDPATH GLOBIGNORE 2>/dev/null || true
set -euo pipefail
umask 077

EXPECTED_MAIN='66056fb7e5a545a6f9532ed00d13008ce0bd2db4'
EXPECTED_CANDIDATE='d47098748e544ea57c3891d6947f26979555ff9d'
EXPECTED_TREE='9ddcb1d11cea7ba94c0aff9b86a68b1d2fc129a1'
CANDIDATE_BRANCH='builder/gen4-runtime-composition'
REPO_URL='https://github.com/billsforAIMe/Dropbox-Governed-Execution-Relay.git'
PYRUNWAY='/usr/local/bin/pyrunway'

EXPECTED_FILES="$(cat <<'EOF'
GOVERNED_EFFECT_SURFACE_INVENTORY.json
src/dger/gen4_runtime_peers.py
tests/run_gen4_assurance.py
tests/test_gen4_runtime_peers.py
tools/validate_gen4_effect_surface_inventory.py
EOF
)"

STAMP="$(/bin/date -u +%Y%m%dT%H%M%SZ)"
DROPBOX_DIR="$HOME/Library/CloudStorage/Dropbox/Software/NSP - Temporary Files/Post94 Cross-Tool Status"
if [ ! -d "$DROPBOX_DIR" ]; then
  DROPBOX_DIR="$HOME/Dropbox/Software/NSP - Temporary Files/Post94 Cross-Tool Status"
fi
if [ ! -d "$DROPBOX_DIR" ]; then
  DROPBOX_DIR="$HOME/Downloads"
fi
/bin/mkdir -p "$DROPBOX_DIR"
LOG="$DROPBOX_DIR/DGER_PR18_PYRUNWAY_QUALIFICATION_${STAMP}.log"
exec > >(/usr/bin/tee -a "$LOG") 2>&1

WORK="$(/usr/bin/mktemp -d "/private/tmp/dger-pr18-qual.XXXXXX")"
finish() {
  rc=$?
  trap - EXIT INT TERM HUP
  /bin/rm -rf "$WORK" 2>/dev/null || true
  if [ "$rc" -eq 0 ]; then
    echo 'DGER_PR18_PYRUNWAY_QUALIFICATION_PASS'
  else
    echo "DGER_PR18_PYRUNWAY_QUALIFICATION_FAIL rc=$rc"
  fi
  echo "RESULT_LOG=$LOG"
  exit "$rc"
}
trap finish EXIT INT TERM HUP

echo "START_UTC=$STAMP"
echo "EXPECTED_MAIN=$EXPECTED_MAIN"
echo "EXPECTED_CANDIDATE=$EXPECTED_CANDIDATE"
echo "EXPECTED_TREE=$EXPECTED_TREE"
echo "CANDIDATE_BRANCH=$CANDIDATE_BRANCH"
echo 'CLAIM_SCOPE=BUILDER_SOURCE_ASSURANCE_ONLY'
echo 'SOURCE_PUBLICATION_DEPLOYMENT_ACTIVATION_RUNTIME_REGISTRY=NOT_CLAIMED'

[ -x "$PYRUNWAY" ] || { echo 'PYRUNWAY_ENVIRONMENT_UNAVAILABLE'; exit 69; }
DESC="$("$PYRUNWAY" --describe)" || { echo 'PYRUNWAY_ENVIRONMENT_UNAVAILABLE'; exit 69; }
CONTRACT="$("$PYRUNWAY" --contract)" || { echo 'PYRUNWAY_ENVIRONMENT_UNAVAILABLE'; exit 69; }
printf '%s\n' "$DESC" | /usr/bin/grep -F '"name":"pyrunway"' >/dev/null || { echo 'PYRUNWAY_ENVIRONMENT_UNAVAILABLE'; exit 69; }
printf '%s\n' "$DESC" | /usr/bin/grep -F '"version":"1.2"' >/dev/null || { echo 'PYRUNWAY_ENVIRONMENT_UNAVAILABLE'; exit 69; }
printf '%s\n' "$CONTRACT" | /usr/bin/grep -F '"standalone-isolated"' >/dev/null || { echo 'PYRUNWAY_ENVIRONMENT_UNAVAILABLE'; exit 69; }
printf '%s\n' "$CONTRACT" | /usr/bin/grep -F '"ambient_python_fallback": false' >/dev/null || { echo 'PYRUNWAY_ENVIRONMENT_UNAVAILABLE'; exit 69; }
echo "PYRUNWAY_DESCRIBE=$DESC"
echo 'PYRUNWAY_RUNTIME_BINDING=PASS'

/bin/mkdir -p "$WORK/repo"
/usr/bin/git -C "$WORK/repo" init -q
/usr/bin/git -C "$WORK/repo" remote add origin "$REPO_URL"
/usr/bin/git -C "$WORK/repo" fetch -q --no-tags --depth=100 origin \
  '+refs/heads/main:refs/remotes/origin/main' \
  "+refs/heads/$CANDIDATE_BRANCH:refs/remotes/origin/candidate"

OBSERVED_MAIN="$(/usr/bin/git -C "$WORK/repo" rev-parse refs/remotes/origin/main)"
OBSERVED_CANDIDATE="$(/usr/bin/git -C "$WORK/repo" rev-parse refs/remotes/origin/candidate)"
[ "$OBSERVED_MAIN" = "$EXPECTED_MAIN" ] || { echo "DGER_MAIN_MOVED_REASSESS observed=$OBSERVED_MAIN"; exit 75; }
[ "$OBSERVED_CANDIDATE" = "$EXPECTED_CANDIDATE" ] || { echo "DGER_CANDIDATE_MOVED_REASSESS observed=$OBSERVED_CANDIDATE"; exit 75; }

OBSERVED_TREE="$(/usr/bin/git -C "$WORK/repo" rev-parse "$OBSERVED_CANDIDATE^{tree}")"
[ "$OBSERVED_TREE" = "$EXPECTED_TREE" ] || { echo "DGER_CANDIDATE_TREE_MISMATCH observed=$OBSERVED_TREE"; exit 75; }
/usr/bin/git -C "$WORK/repo" merge-base --is-ancestor "$EXPECTED_MAIN" "$EXPECTED_CANDIDATE" || { echo 'DGER_CANDIDATE_ANCESTRY_FAIL'; exit 75; }

/usr/bin/git -C "$WORK/repo" checkout -q --detach "$EXPECTED_CANDIDATE"
/usr/bin/git -C "$WORK/repo" diff --check "$EXPECTED_MAIN..$EXPECTED_CANDIDATE"

OBSERVED_FILES="$(/usr/bin/git -C "$WORK/repo" diff --name-only "$EXPECTED_MAIN..$EXPECTED_CANDIDATE")"
[ "$OBSERVED_FILES" = "$EXPECTED_FILES" ] || {
  echo 'DGER_CHANGED_FILE_SET_MISMATCH'
  echo 'EXPECTED_FILES:'
  printf '%s\n' "$EXPECTED_FILES"
  echo 'OBSERVED_FILES:'
  printf '%s\n' "$OBSERVED_FILES"
  exit 75
}

echo "OBSERVED_MAIN=$OBSERVED_MAIN"
echo "OBSERVED_CANDIDATE=$OBSERVED_CANDIDATE"
echo "OBSERVED_TREE=$OBSERVED_TREE"
echo 'CANDIDATE_IDENTITY_DIFF_AND_ANCESTRY=PASS'

cat > "$WORK/compile_candidate.py" <<'PY'
from pathlib import Path
import compileall
import sys
root = Path(sys.argv[1]).resolve()
for name in ("src", "tests", "tools"):
    if not compileall.compile_dir(root / name, quiet=1, force=True):
        raise SystemExit(f"COMPILEALL_FAIL:{name}")
print("DGER_COMPILEALL_PASS")
PY
/bin/chmod 600 "$WORK/compile_candidate.py"

"$PYRUNWAY" --standalone "$WORK/compile_candidate.py" "$WORK/repo"
echo 'GOVERNED_COMPILEALL=PASS'

(
  cd "$WORK/repo"
  "$PYRUNWAY" --standalone "$WORK/repo/tests/run_gen4_assurance.py"
)
echo 'GOVERNED_GEN4_ASSURANCE=PASS'
echo "END_UTC=$(/bin/date -u +%Y%m%dT%H%M%SZ)"
