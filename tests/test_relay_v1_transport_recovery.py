from relay_v1_fixture import *
from relay_v1_fixture import RelayV1TestBase
import shutil


class RelayV1TransportRecoveryTests(RelayV1TestBase):
    def test_23_lost_execute_response_recovers_after_ingress_is_removed(self):
        eid = "lost-execute-no-ingress"
        self.gateway.lost_execute_once.add(eid)
        package = write_package(self.transport, eid)
        self.assertTrue(self.relay.process_one(package))
        self.assertEqual(self.state_for(eid)["phase"], "MOH_RECONCILE")
        shutil.rmtree(package)

        self.relay.scan_once()

        self.assertEqual(self.state_for(eid)["phase"], "DONE")
        self.assertEqual(self.gateway.execute_calls[eid], 1)
        self.assertGreaterEqual(self.gateway.status_calls[eid], 1)

    def test_24_chm_only_recovery_continues_after_ingress_is_removed(self):
        eid = "chm-pending-no-ingress"
        hid = handoff_for(eid)
        self.gateway.fail_chm_once.add(hid)
        package = write_package(self.transport, eid)
        self.assertTrue(self.relay.process_one(package))
        self.assertEqual(self.state_for(eid)["phase"], "CHM_PENDING")
        self.assertEqual(self.gateway.execute_calls[eid], 1)
        shutil.rmtree(package)

        self.relay.scan_once()

        self.assertEqual(self.state_for(eid)["phase"], "DONE")
        self.assertEqual(self.gateway.execute_calls[eid], 1)
        self.assertIn(hid, self.gateway.resolved)
