#!/bin/bash -p
# Install exact governed PyRunway source bytes using explicit dependency locators.
PATH=/usr/bin:/bin
export PATH
IFS=$' \t\n'
unset BASH_ENV ENV CDPATH GLOBIGNORE 2>/dev/null || true
set -euo pipefail
umask 077

TOKEN="PYRUNWAY_ENVIRONMENT_UNAVAILABLE"
EX_UNAVAILABLE=69
RELEASE_ID="1.3.1"
fail() { printf '%s\n' "$TOKEN" >&2; exit "$EX_UNAVAILABLE"; }
usage() { printf 'usage: install.sh --prefix ABSOLUTE_PREFIX --uv ABSOLUTE_UV --python ABSOLUTE_PYTHON\n' >&2; exit 64; }

sha256_file() {
  local f="$1"
  if [ -x /usr/bin/sha256sum ]; then /usr/bin/sha256sum "$f" | /usr/bin/awk '{print $1}'
  elif [ -x /usr/bin/shasum ]; then /usr/bin/shasum -a 256 "$f" | /usr/bin/awk '{print $1}'
  else return 1; fi
}
resolve_physical_executable() {
  local p="$1" target dir i=0
  case "$p" in /*) ;; *) return 1 ;; esac
  while [ -L "$p" ]; do
    i=$((i + 1)); [ "$i" -le 40 ] || return 1
    target="$(/usr/bin/readlink "$p")" || return 1
    dir="$(cd -P "$(/usr/bin/dirname "$p")" 2>/dev/null && pwd -P)" || return 1
    case "$target" in /*) p="$target" ;; *) p="$dir/$target" ;; esac
  done
  dir="$(cd -P "$(/usr/bin/dirname "$p")" 2>/dev/null && pwd -P)" || return 1
  p="$dir/$(/usr/bin/basename "$p")"
  [ -f "$p" ] && [ ! -L "$p" ] && [ -x "$p" ] || return 1
  printf '%s\n' "$p"
}

self="${BASH_SOURCE[0]}"
[ -f "$self" ] && [ ! -L "$self" ] || fail
src_root="$(cd -P "$(/usr/bin/dirname "$self")/.." && pwd -P)" || fail
prefix=""; uv=""; standalone_python=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --prefix) [ "$#" -ge 2 ] || usage; prefix="$2"; shift 2 ;;
    --uv) [ "$#" -ge 2 ] || usage; uv="$2"; shift 2 ;;
    --python) [ "$#" -ge 2 ] || usage; standalone_python="$2"; shift 2 ;;
    *) usage ;;
  esac
done
case "$prefix" in /*) ;; *) usage ;; esac
case "$uv" in /*) ;; *) usage ;; esac
case "$standalone_python" in /*) ;; *) usage ;; esac

bash_phys="/bin/bash"
[ -f "$bash_phys" ] && [ ! -L "$bash_phys" ] && [ -x "$bash_phys" ] || fail
bash_sha="$(sha256_file "$bash_phys" 2>/dev/null || true)"; [ ${#bash_sha} -eq 64 ] || fail
uv_phys="$(resolve_physical_executable "$uv" 2>/dev/null || true)"; [ -n "$uv_phys" ] || fail
uv_sha="$(sha256_file "$uv_phys" 2>/dev/null || true)"; [ ${#uv_sha} -eq 64 ] || fail
uv_version="$($uv_phys --version 2>/dev/null | /usr/bin/head -n 1)" || fail
case "$uv_version" in uv\ *) ;; *) fail ;; esac
help="$($uv_phys run --help 2>/dev/null)" || fail
for flag in --isolated --no-project --no-config --offline --no-python-downloads --project --directory --no-sync --python; do
  printf '%s\n' "$help" | /usr/bin/grep -F -- "$flag" >/dev/null || fail
done
standalone_python_phys="$(resolve_physical_executable "$standalone_python" 2>/dev/null || true)"; [ -n "$standalone_python_phys" ] || fail
standalone_python_sha="$(sha256_file "$standalone_python_phys" 2>/dev/null || true)"; [ ${#standalone_python_sha} -eq 64 ] || fail

launcher="$src_root/launcher/pyrunway"
contract="$src_root/contract/pyrunway-contract.json"
describe="$src_root/contract/pyrunway-describe-v1.json"
[ -f "$launcher" ] && [ ! -L "$launcher" ] && [ -x "$launcher" ] || fail
[ -f "$contract" ] && [ ! -L "$contract" ] || fail
[ -f "$describe" ] && [ ! -L "$describe" ] || fail
contract_sha="$(sha256_file "$contract" 2>/dev/null || true)"; [ ${#contract_sha} -eq 64 ] || fail
describe_sha="$(sha256_file "$describe" 2>/dev/null || true)"; [ ${#describe_sha} -eq 64 ] || fail
expected_contract_sha="$(/usr/bin/grep '^EXPECTED_CONTRACT_SHA256=' "$launcher" | /usr/bin/head -n1 | /usr/bin/cut -d'"' -f2)"
expected_describe_sha="$(/usr/bin/grep '^EXPECTED_DESCRIBE_SHA256=' "$launcher" | /usr/bin/head -n1 | /usr/bin/cut -d'"' -f2)"
[ "$contract_sha" = "$expected_contract_sha" ] || fail
[ "$describe_sha" = "$expected_describe_sha" ] || fail

release_parent="$prefix/lib/pyrunway/releases"; release_dir="$release_parent/$RELEASE_ID"; bin_dir="$prefix/bin"
/bin/mkdir -p "$release_parent" "$bin_dir" || fail
[ -d "$release_parent" ] && [ ! -L "$release_parent" ] && [ -d "$bin_dir" ] && [ ! -L "$bin_dir" ] || fail
stage="$(/usr/bin/mktemp -d "$release_parent/.${RELEASE_ID}.stage.XXXXXX")" || fail
cleanup(){ rc=$?; [ -z "${stage:-}" ] || /bin/rm -rf "$stage" 2>/dev/null || true; exit "$rc"; }
trap cleanup EXIT INT TERM HUP
/bin/cp "$contract" "$stage/pyrunway-contract.json" || fail
/bin/cp "$describe" "$stage/pyrunway-describe-v1.json" || fail
/bin/cp "$launcher" "$stage/pyrunway" || fail
/bin/chmod 755 "$stage/pyrunway" || fail
printf '%s\n' \
  'schema=pyrunway-runtime-binding/v1' \
  "release_id=$RELEASE_ID" \
  "contract_sha256=$contract_sha" \
  "describe_sha256=$describe_sha" \
  "bash_path=$bash_phys" \
  "bash_sha256=$bash_sha" \
  "uv_path=$uv_phys" \
  "uv_sha256=$uv_sha" \
  "uv_version=$uv_version" \
  "standalone_python_path=$standalone_python_phys" \
  "standalone_python_sha256=$standalone_python_sha" > "$stage/runtime-binding.conf" || fail
/bin/chmod 644 "$stage/pyrunway-contract.json" "$stage/pyrunway-describe-v1.json" "$stage/runtime-binding.conf" || fail

# Source release bytes are immutable. Platform-local dependency bindings may be atomically rebound on reinstall.
if [ -e "$release_dir" ]; then
  [ -d "$release_dir" ] && [ ! -L "$release_dir" ] || fail
  /usr/bin/cmp -s "$stage/pyrunway-contract.json" "$release_dir/pyrunway-contract.json" || fail
  /usr/bin/cmp -s "$stage/pyrunway-describe-v1.json" "$release_dir/pyrunway-describe-v1.json" || fail
  /usr/bin/cmp -s "$stage/pyrunway" "$release_dir/pyrunway" || fail
  binding_tmp="$release_dir/.runtime-binding.$$.tmp"
  /bin/cp "$stage/runtime-binding.conf" "$binding_tmp" || fail
  /bin/chmod 644 "$binding_tmp" || fail
  /bin/mv "$binding_tmp" "$release_dir/runtime-binding.conf" || fail
else
  /bin/mv "$stage" "$release_dir" || fail
  stage=""
fi
launcher_tmp="$bin_dir/.pyrunway.$$.tmp"
/bin/cp "$launcher" "$launcher_tmp" || fail
/bin/chmod 755 "$launcher_tmp" || fail
"$launcher_tmp" --describe >/dev/null 2>&1 || fail
"$launcher_tmp" --contract >/dev/null 2>&1 || fail
/bin/mv "$launcher_tmp" "$bin_dir/pyrunway" || fail
[ -f "$bin_dir/pyrunway" ] && [ ! -L "$bin_dir/pyrunway" ] || fail
"$bin_dir/pyrunway" --describe >/dev/null 2>&1 || fail
"$bin_dir/pyrunway" --contract >/dev/null 2>&1 || fail
printf 'PYRUNWAY_INSTALL_OK\npath=%s\nrelease_id=%s\nlauncher_sha256=%s\ncontract_sha256=%s\ndescribe_sha256=%s\nbash_path=%s\nbash_sha256=%s\nuv_path=%s\nuv_sha256=%s\nstandalone_python_path=%s\nstandalone_python_sha256=%s\n' \
  "$bin_dir/pyrunway" "$RELEASE_ID" "$(sha256_file "$bin_dir/pyrunway")" "$contract_sha" "$describe_sha" "$bash_phys" "$bash_sha" "$uv_phys" "$uv_sha" "$standalone_python_phys" "$standalone_python_sha"
trap - EXIT INT TERM HUP
[ -z "$stage" ] || /bin/rm -rf "$stage"
