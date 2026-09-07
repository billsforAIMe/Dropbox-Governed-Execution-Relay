#!/bin/bash -p
PATH=/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin
export PATH
IFS=$' \t\n'
unset BASH_ENV ENV CDPATH GLOBIGNORE 2>/dev/null || true
set -euo pipefail
umask 077

MAIN='66056fb7e5a545a6f9532ed00d13008ce0bd2db4'
CANDIDATE='2d3cde0eb07f76bdd59b14f7dbed18809e1c35fc'
TREE='7b320ecf5fcc1b74e9b7ca5ae89436275f764a76'
BRANCH='builder/gen4-runtime-composition'
REPO='https://github.com/billsforAIMe/Dropbox-Governed-Execution-Relay.git'
PYRUNWAY='/usr/local/bin/pyrunway'
STAMP="$(/bin/date -u +%Y%m%dT%H%M%SZ)"
OUT="$HOME/Library/CloudStorage/Dropbox/Software/NSP - Temporary Files/Post94 Cross-Tool Status"
[ -d "$OUT" ] || OUT="$HOME/Dropbox/Software/NSP - Temporary Files/Post94 Cross-Tool Status"
[ -d "$OUT" ] || OUT="$HOME/Downloads"
LOG="$OUT/DGER_PR18_PYRUNWAY_QUALIFICATION_${STAMP}.log"
WORK="$(/usr/bin/mktemp -d /private/tmp/dger-pr18-qual.XXXXXX)"
finish() {
  rc=$?
  trap - EXIT INT TERM HUP
  /bin/rm -rf "$WORK" 2>/dev/null || true
  if [ "$rc" -eq 0 ]; then echo 'DGER_PR18_PYRUNWAY_QUALIFICATION_PASS'; else echo "DGER_PR18_PYRUNWAY_QUALIFICATION_FAIL rc=$rc"; fi
  echo "RESULT_LOG=$LOG"
  exit "$rc"
}
trap finish EXIT INT TERM HUP
exec > >(/usr/bin/tee -a "$LOG") 2>&1

echo "START_UTC=$STAMP"
echo "EXPECTED_MAIN=$MAIN"
echo "QUALIFIED_CANDIDATE=$CANDIDATE"
echo "QUALIFIED_TREE=$TREE"
echo 'CLAIM_SCOPE=BUILDER_CHANGED_PROPOSITION_ASSURANCE_ONLY'
echo 'DEPLOYMENT_ACTIVATION_REGISTRY_RUNTIME=NOT_CLAIMED'

[ -x "$PYRUNWAY" ] || { echo 'PYRUNWAY_ENVIRONMENT_UNAVAILABLE'; exit 69; }
DESC="$($PYRUNWAY --describe)" || { echo 'PYRUNWAY_ENVIRONMENT_UNAVAILABLE'; exit 69; }
CONTRACT="$($PYRUNWAY --contract)" || { echo 'PYRUNWAY_ENVIRONMENT_UNAVAILABLE'; exit 69; }
printf '%s\n' "$DESC" | /usr/bin/grep -F '"name":"pyrunway"' >/dev/null
printf '%s\n' "$DESC" | /usr/bin/grep -F '"version":"1.2"' >/dev/null
printf '%s\n' "$CONTRACT" | /usr/bin/grep -F '"standalone-isolated"' >/dev/null
printf '%s\n' "$CONTRACT" | /usr/bin/grep -F '"ambient_python_fallback": false' >/dev/null
echo "PYRUNWAY_DESCRIBE=$DESC"
echo 'PYRUNWAY_RUNTIME_BINDING=PASS'

/bin/mkdir -p "$WORK/repo"
/usr/bin/git -C "$WORK/repo" init -q
/usr/bin/git -C "$WORK/repo" remote add origin "$REPO"
/usr/bin/git -C "$WORK/repo" fetch -q --no-tags --depth=100 origin \
  '+refs/heads/main:refs/remotes/origin/main' \
  "+refs/heads/$BRANCH:refs/remotes/origin/candidate-tip"
OBS_MAIN="$(/usr/bin/git -C "$WORK/repo" rev-parse refs/remotes/origin/main)"
OBS_TIP="$(/usr/bin/git -C "$WORK/repo" rev-parse refs/remotes/origin/candidate-tip)"
[ "$OBS_MAIN" = "$MAIN" ] || { echo "DGER_MAIN_MOVED_REASSESS observed=$OBS_MAIN"; exit 75; }
/usr/bin/git -C "$WORK/repo" cat-file -e "$CANDIDATE^{commit}"
OBS_TREE="$(/usr/bin/git -C "$WORK/repo" rev-parse "$CANDIDATE^{tree}")"
[ "$OBS_TREE" = "$TREE" ] || { echo "DGER_CANDIDATE_TREE_MISMATCH observed=$OBS_TREE"; exit 75; }
/usr/bin/git -C "$WORK/repo" merge-base --is-ancestor "$MAIN" "$CANDIDATE"
/usr/bin/git -C "$WORK/repo" merge-base --is-ancestor "$CANDIDATE" "$OBS_TIP"
TIP_TREE="$(/usr/bin/git -C "$WORK/repo" rev-parse "$OBS_TIP^{tree}")"
[ "$TIP_TREE" = "$TREE" ] || { echo "DGER_BRANCH_SOURCE_MOVED_REASSESS head=$OBS_TIP tree=$TIP_TREE"; exit 75; }
/usr/bin/git -C "$WORK/repo" checkout -q --detach "$CANDIDATE"
/usr/bin/git -C "$WORK/repo" diff --check "$MAIN..$CANDIDATE"
EXPECTED_FILES=$'GOVERNED_EFFECT_SURFACE_INVENTORY.json\nsrc/dger/gen4_runtime_peers.py\ntests/run_gen4_assurance.py\ntests/test_gen4_effect_surface_scan.py\ntests/test_gen4_runtime_peers.py\ntools/dger_execution_surface_scan.py\ntools/validate_gen4_effect_surface_inventory.py'
OBS_FILES="$(/usr/bin/git -C "$WORK/repo" diff --name-only "$MAIN..$CANDIDATE")"
[ "$OBS_FILES" = "$EXPECTED_FILES" ] || { echo 'DGER_CHANGED_FILE_SET_MISMATCH'; printf '%s\n' "$OBS_FILES"; exit 75; }
echo "OBSERVED_MAIN=$OBS_MAIN"
echo "OBSERVED_BRANCH_TIP=$OBS_TIP"
echo "OBSERVED_BRANCH_TIP_TREE=$TIP_TREE"
echo 'EXACT_REVIEWED_CANDIDATE_IDENTITY_ANCESTRY_DIFF=PASS'

cat > "$WORK/qualify.py" <<'PY'
from pathlib import Path
import compileall
import subprocess
import sys
import unittest
root = Path(sys.argv[1]).resolve()
for name in ("src", "tests", "tools"):
    if not compileall.compile_dir(root / name, quiet=1, force=True):
        raise SystemExit(f"COMPILEALL_FAIL:{name}")
print("DGER_COMPILEALL_PASS")
sys.path.insert(0, str(root / "src"))
sys.path.insert(0, str(root / "tests"))
suite = unittest.TestSuite()
for name in (
    "test_gen4_runtime_peers",
    "test_gen4_gep14_correlation",
    "test_gen4_provider_evidence",
    "test_gen4_delegation",
    "test_gen4_chm_relay_contract",
    "test_gen4_effect_surface_scan",
):
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    raise SystemExit(1)
for tool in ("validate_gen4_effect_surface_inventory.py", "validate_gen4_release.py"):
    subprocess.run([sys.executable, str(root / "tools" / tool)], cwd=root, check=True)
print("DGER_PR18_CHANGED_PROPOSITION_PASS")
PY
/bin/chmod 600 "$WORK/qualify.py"
"$PYRUNWAY" --standalone "$WORK/qualify.py" "$WORK/repo"
echo 'GOVERNED_CHANGED_PROPOSITION_ASSURANCE=PASS'
echo "END_UTC=$(/bin/date -u +%Y%m%dT%H%M%SZ)"
