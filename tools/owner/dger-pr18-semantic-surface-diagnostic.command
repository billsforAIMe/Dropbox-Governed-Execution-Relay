#!/bin/bash -p
PATH=/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin
export PATH
IFS=$' \t\n'
unset BASH_ENV ENV CDPATH GLOBIGNORE 2>/dev/null || true
set -euo pipefail
umask 077

MAIN='66056fb7e5a545a6f9532ed00d13008ce0bd2db4'
CANDIDATE='2eb46ce176b50e89db4831cc171b69274b9669b8'
TREE='470b9dbec9e04dd3a060ee0ab27046b9c648c2f9'
REPO='https://github.com/billsforAIMe/Dropbox-Governed-Execution-Relay.git'
PYRUNWAY='/usr/local/bin/pyrunway'
STAMP="$(/bin/date -u +%Y%m%dT%H%M%SZ)"
OUT="$HOME/Library/CloudStorage/Dropbox/Software/NSP - Temporary Files/Post94 Cross-Tool Status"
[ -d "$OUT" ] || OUT="$HOME/Dropbox/Software/NSP - Temporary Files/Post94 Cross-Tool Status"
[ -d "$OUT" ] || OUT="$HOME/Downloads"
LOG="$OUT/DGER_PR18_SEMANTIC_SURFACE_DIAGNOSTIC_${STAMP}.log"
WORK="$(/usr/bin/mktemp -d /private/tmp/dger-pr18-diag.XXXXXX)"
finish() {
  rc=$?
  trap - EXIT INT TERM HUP
  /bin/rm -rf "$WORK" 2>/dev/null || true
  echo "RESULT_LOG=$LOG"
  exit "$rc"
}
trap finish EXIT INT TERM HUP
exec > >(/usr/bin/tee -a "$LOG") 2>&1

[ -x "$PYRUNWAY" ] || { echo 'PYRUNWAY_ENVIRONMENT_UNAVAILABLE'; exit 69; }
/bin/mkdir -p "$WORK/repo"
/usr/bin/git -C "$WORK/repo" init -q
/usr/bin/git -C "$WORK/repo" remote add origin "$REPO"
/usr/bin/git -C "$WORK/repo" fetch -q --no-tags --depth=100 origin \
  '+refs/heads/main:refs/remotes/origin/main' \
  "$CANDIDATE"
OBS_MAIN="$(/usr/bin/git -C "$WORK/repo" rev-parse refs/remotes/origin/main)"
[ "$OBS_MAIN" = "$MAIN" ] || { echo "DGER_MAIN_MOVED_REASSESS observed=$OBS_MAIN"; exit 75; }
OBS_TREE="$(/usr/bin/git -C "$WORK/repo" rev-parse "$CANDIDATE^{tree}")"
[ "$OBS_TREE" = "$TREE" ] || { echo "DGER_CANDIDATE_TREE_MISMATCH observed=$OBS_TREE"; exit 75; }
/usr/bin/git -C "$WORK/repo" checkout -q --detach "$CANDIDATE"

cat > "$WORK/diag.py" <<'PY'
from pathlib import Path
import json
import sys
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / "tools"))
from dger_execution_surface_scan import SEMANTIC_EXECUTE_ALLOWLIST, scan_execution_call_sites
process_calls, semantic_calls = scan_execution_call_sites(root)
print("PROCESS_CALLS=" + json.dumps(process_calls, separators=(",", ":")))
print("SEMANTIC_CALLS=" + json.dumps(semantic_calls, separators=(",", ":")))
print("SEMANTIC_ALLOWLIST=" + json.dumps(sorted(SEMANTIC_EXECUTE_ALLOWLIST), separators=(",", ":")))
unexpected = [row for row in semantic_calls if tuple(row[:3]) not in SEMANTIC_EXECUTE_ALLOWLIST]
missing = [row for row in sorted(SEMANTIC_EXECUTE_ALLOWLIST) if row not in [tuple(x[:3]) for x in semantic_calls]]
print("UNEXPECTED_SEMANTIC_CALLS=" + json.dumps(unexpected, separators=(",", ":")))
print("MISSING_ALLOWLIST_CALLS=" + json.dumps(missing, separators=(",", ":")))
print("DGER_PR18_SEMANTIC_SURFACE_DIAGNOSTIC_PASS")
PY
"$PYRUNWAY" --standalone "$WORK/diag.py" "$WORK/repo"
