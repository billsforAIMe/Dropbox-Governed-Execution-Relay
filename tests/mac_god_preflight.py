from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "deployment/dger_god_adapter.py"

if sys.platform != "darwin":
    raise SystemExit("MAC_GOD_PREFLIGHT_REQUIRES_DARWIN")

spec = importlib.util.spec_from_file_location("dger_god_adapter_mac", ADAPTER_PATH)
assert spec and spec.loader
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

context = {
    "schema_version": 1,
    "project_id": "dropbox-governed-execution-relay",
    "deployment_root": str(adapter.STATE),
    "state_root": str(adapter.STATE),
    "approved_commit": "0" * 40,
    "approved_tree": "0" * 40,
}

report = adapter.project_discover(context)
if report.get("discovery_complete") is not True:
    print(json.dumps({"status": "BLOCKED", "stage": "project_discover", "report": report}, sort_keys=True))
    raise SystemExit(1)
if report.get("discovered_runtime_ids") != [adapter.RUNTIME_ID]:
    print(json.dumps({"status": "BLOCKED", "stage": "runtime_inventory", "report": report}, sort_keys=True))
    raise SystemExit(1)
if not adapter._plain_dir(adapter.MOH_HOME):
    print(json.dumps({"status": "BLOCKED", "stage": "moh_home"}, sort_keys=True))
    raise SystemExit(1)
try:
    adapter._keychain_token()
except Exception as exc:
    print(json.dumps({"status": "BLOCKED", "stage": "gtg_keychain", "error": type(exc).__name__}, sort_keys=True))
    raise SystemExit(1)
if not adapter._gtg_ping():
    print(json.dumps({"status": "BLOCKED", "stage": "gtg_ping"}, sort_keys=True))
    raise SystemExit(1)

print(json.dumps({
    "status": "PASS",
    "operation": "dger_gen3_god_mac_preflight",
    "runtime_id": adapter.RUNTIME_ID,
    "active_runtime_ids": report.get("active_runtime_ids"),
    "moh_home": str(adapter.MOH_HOME),
    "gtg_endpoint": adapter.GTG_ENDPOINT,
    "credential_material_exposed": False,
}, sort_keys=True))
