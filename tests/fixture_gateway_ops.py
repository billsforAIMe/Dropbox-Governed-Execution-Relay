from __future__ import annotations

import json

from fixture_gateway_core import CHM_TOOL_ID, MOH_TOOL_ID

class FakeGatewayOpsMixin:
    def invoke(self, tool_id: str, operation: str, arguments: dict):
        if tool_id == MOH_TOOL_ID:
            eid = arguments["execution_id"]
            if operation == "execute":
                self.execute_calls[eid] = self.execute_calls.get(eid, 0) + 1
                if eid in self.failed_ids:
                    state = "FAILED"
                elif eid in self.in_doubt_ids:
                    state = "IN_DOUBT"
                elif self.running_status_cycles.get(eid, 0) > 0:
                    state = "RUNNING"
                else:
                    state = "SUCCEEDED"
                response = self._moh_response(eid, state)
                self.moh[eid] = response
                if eid in self.lost_execute_once and eid not in self._lost_execute_done:
                    self._lost_execute_done.add(eid)
                    raise RuntimeError("simulated lost execute response")
                return self._inv({"ok": state not in {"FAILED", "IN_DOUBT"}, "state": state, "response_json": json.dumps(response, sort_keys=True, separators=(",", ":"))})
            if operation == "status":
                self.status_calls[eid] = self.status_calls.get(eid, 0) + 1
                current = self.moh.get(eid, self._moh_response(eid, "NOT_FOUND"))
                if current["state"] == "RUNNING":
                    remaining = self.running_status_cycles.get(eid, 0)
                    if remaining > 1:
                        self.running_status_cycles[eid] = remaining - 1
                    else:
                        self.running_status_cycles[eid] = 0
                        current = self._moh_response(eid, "SUCCEEDED")
                        self.moh[eid] = current
                return self._inv({"ok": current["state"] not in {"FAILED", "IN_DOUBT"}, "state": current["state"], "response_json": json.dumps(current, sort_keys=True, separators=(",", ":"))})
        if tool_id == CHM_TOOL_ID:
            hid = arguments["handoff_id"]
            if operation == "handoff_get":
                self.get_calls[hid] = self.get_calls.get(hid, 0) + 1
                state = self.handoff_states.get(hid, "STARTED")
                result = self.chm_results.get(hid)
                return self._inv({
                    "ok": True, "code": "HANDOFF_FOUND", "handoff_id": hid,
                    "state": "RESULT_AVAILABLE" if state == "STARTED" and result is not None else state,
                    **({"result": {"result": result}} if result is not None else {}),
                })
            if operation == "handoff_attach_result":
                self.attach_calls[hid] = self.attach_calls.get(hid, 0) + 1
                if hid in self.fail_chm_once and hid not in self._fail_chm_done:
                    self._fail_chm_done.add(hid)
                    raise RuntimeError("simulated CHM unavailable")
                proposed = arguments["result"]
                existing = self.chm_results.get(hid)
                if existing is not None and existing != proposed:
                    return self._inv({"ok": False, "code": "HANDOFF_RESULT_CONFLICT"})
                self.chm_results[hid] = proposed
                if hid in self.lost_attach_once and hid not in self._lost_attach_done:
                    self._lost_attach_done.add(hid)
                    raise RuntimeError("simulated lost attach response")
                return self._inv({"ok": True, "code": "HANDOFF_RESULT_ATTACHED", "handoff_id": hid})
            if operation == "handoff_resolve":
                self.resolve_calls[hid] = self.resolve_calls.get(hid, 0) + 1
                self.resolved.add(hid)
                return self._inv({"ok": True, "code": "HANDOFF_RESOLVED", "handoff_id": hid, "state": "RESOLVED"})
        raise AssertionError((tool_id, operation, arguments))

    def get_invocation(self, invocation_id: str):
        raise NotImplementedError
