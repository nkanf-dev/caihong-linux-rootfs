"""Linux runtime filesystem/receipt fixtures; never starts Steam or a device."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import clean_gate as gate
from dual_mode import LaunchError
import runtime_backend as rb

class GateTests(unittest.TestCase):
    def fixture(self, root):
        settings = root / "steam/config/steamvr.vrsettings"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"driver_alvr_server":{"blocked_by_safe_mode":False},"sentinel":4}))
        return settings, root / "runtime", root / "launcher"

    def test_clean_normal_receipt_without_editing_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            settings, state, launch = self.fixture(Path(temp).resolve())
            before = settings.read_bytes()
            receipt = gate.prepare_clean(settings, state, launch, check_closed=lambda: None, now=100)
            self.assertTrue(receipt["clean_start"])
            self.assertEqual(receipt["attempts"],1)
            self.assertEqual(settings.read_bytes(), before)
            self.assertEqual((state/"retry-receipt.json").stat().st_mode & 0o777, 0o600)
            self.assertTrue((launch/"clean-start.json").is_file())
            self.assertFalse((state/"backups").exists())

    def test_marker_block_unknown_and_active_refused_without_mutation(self):
        for condition in ["marker", "blocked", "unknown", "active"]:
            with self.subTest(condition=condition), tempfile.TemporaryDirectory() as temp:
                settings, state, launch = self.fixture(Path(temp).resolve())
                if condition == "marker": settings.with_name("vrserver_crash_timestamp.txt").write_text("1 2 3")
                if condition in ("blocked", "unknown"):
                    settings.write_text(json.dumps({"driver_alvr_server":{"blocked_by_safe_mode":True}}) if condition=="blocked" else "{}")
                before=settings.read_bytes()
                def closed():
                    if condition=="active": raise RuntimeError("active")
                with self.assertRaises((LaunchError,RuntimeError)):
                    gate.prepare_clean(settings,state,launch,check_closed=closed,now=100)
                self.assertEqual(before,settings.read_bytes())
                self.assertFalse((state/"retry-receipt.json").exists())

    def test_existing_valid_receipt_not_renewed(self):
        with tempfile.TemporaryDirectory() as temp:
            settings,state,launch=self.fixture(Path(temp).resolve())
            gate.prepare_clean(settings,state,launch,check_closed=lambda:None,now=100)
            before=(state/"retry-receipt.json").read_bytes()
            gate.prepare_clean(settings,state,launch,check_closed=lambda:None,now=200)
            self.assertEqual(before,(state/"retry-receipt.json").read_bytes())
            with self.assertRaises(LaunchError):
                gate.prepare_clean(settings,state,launch,check_closed=lambda:None,now=701)

    def test_failed_attempt_requires_actual_review_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            settings,state,launch=self.fixture(Path(temp).resolve())
            launch.mkdir(mode=0o700)
            gate.write_private(launch/"status.json",{"event":"failed"})
            with self.assertRaises(LaunchError): gate.prepare_clean(settings,state,launch,check_closed=lambda:None,now=100)
            state.mkdir(mode=0o700)
            review=Path(temp).resolve()/"review.md"
            review.write_text("Reviewed fixture fault and one correction")
            receipt={"created_at":100,"attempts":1,"appid":250820,"fault_review":str(review)}
            gate.write_private(state/"retry-receipt.json",receipt)
            self.assertEqual(gate.prepare_clean(settings,state,launch,check_closed=lambda:None,now=110),receipt)

    def test_receipt_schema_rejects_nonobject_boolean_and_nonfinite_fields(self):
        cases=[None,[],True,{"appid":250820,"attempts":True,"created_at":100},
               {"appid":250820,"attempts":1,"created_at":True},
               {"appid":250820,"attempts":1,"created_at":float("nan")},
               {"appid":250820,"attempts":1,"created_at":float("inf")}]
        for receipt in cases:
            with self.subTest(receipt=receipt): self.assertFalse(gate.valid_receipt(receipt,110))

    def test_boolean_review_placeholder_cannot_bypass_failed_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            settings,state,launch=self.fixture(Path(temp).resolve())
            state.mkdir(mode=0o700)
            gate.write_private(launch/"status.json",{"event":"failed"})
            gate.write_private(state/"retry-receipt.json",{"appid":250820,"attempts":1,"created_at":100,"fault_review":True})
            with self.assertRaises(LaunchError):
                gate.prepare_clean(settings,state,launch,check_closed=lambda:None,now=110)

    def test_group_writable_ancestor_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp).resolve()
            ancestor=base/"unsafe"
            ancestor.mkdir(mode=0o770)
            ancestor.chmod(0o770)
            with self.assertRaises(LaunchError): gate.write_private(ancestor/"state/status.json",{"event":"test"})
            self.assertFalse((ancestor/"state/status.json").exists())

    def test_write_holds_parent_dirfd_when_checked_path_is_swapped(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp).resolve()
            state=base/"state";state.mkdir(mode=0o700)
            outside=base/"outside";outside.mkdir(mode=0o700)
            (outside/"status.json").write_text("outside sentinel")
            original=gate.os.open
            swapped=[]
            def swap_open(path,flags,*args,**kwargs):
                if str(path).endswith("status.json") and not swapped:
                    state.rename(base/"saved")
                    state.symlink_to(outside,target_is_directory=True)
                    swapped.append(True)
                return original(path,flags,*args,**kwargs)
            with patch.object(gate.os,"open",side_effect=swap_open):
                try: gate.write_private(state/"status.json",{"event":"new"})
                except LaunchError: pass
            self.assertEqual((outside/"status.json").read_text(),"outside sentinel")

    def test_private_lock_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()
            state=root/"state"
            with gate.private_lock(state,"launch.lock"):
                with self.assertRaises(LaunchError):
                    with gate.private_lock(state,"launch.lock"): pass
            state.chmod(0o755)
            with self.assertRaises(LaunchError):
                with gate.private_lock(state,"launch.lock"): pass

class BackendTests(unittest.TestCase):
    def test_log_same_pid_time_and_rotation(self):
        run=rb.Process(17,"vrserver",100,datetime(1970,1,1,0,16,40).timestamp())
        monitor=rb.Process(18,"vrmonitor",101,datetime(1970,1,1,0,16,41).timestamp())
        server="""Thu Jan 01 1970 00:16:40.000000 [Info] - FEX 2.17.10 startup with PID=17
Thu Jan 01 1970 00:16:41.000000 [Info] - Loaded server driver alvr_server (IServerTrackedDeviceProvider_004) from /private/driver_alvr_server.so
"""
        ready="""Thu Jan 01 1970 00:16:41.000000 [Info] - FEX 2.17.10 startup with PID=18
Thu Jan 01 1970 00:16:42.000000 [Info] - [System] Transition from 'SteamVRSystemState_Connecting' to 'SteamVRSystemState_Ready'
"""
        self.assertEqual(rb.log_proof([server,ready],[run,monitor]),(True,True))
        self.assertEqual(rb.log_proof([server.replace("PID=17","PID=99"),ready],[run,monitor]),(False,True))
        stale=server.replace("00:16:41.000000", "00:15:41.000000")
        self.assertEqual(rb.log_proof([stale,ready],[run,monitor]),(False,True))
        self.assertEqual(rb.log_proof(["Loaded server driver alvr_server", "SteamVRSystemState_Ready"],[run,monitor]),(False,False))

    def test_process_roles_real_basename_and_fex_not_argument_mentions(self):
        cases=[("FEXInterpreter",["/bin/FEXInterpreter","/game/vrserver"],"vrserver"),
               ("vrcompositor.re",["/bin/FEX","/game/vrcompositor.real"],"vrcompositor"),
               ("steam-reaper",["steam-reaper","/game/vrstartup.sh"],None),
               ("vrmonitor",["/game/vrmonitor"],"vrmonitor")]
        for comm,args,expected in cases:
            self.assertEqual(rb.process_role(comm,args),expected)

    def test_proc_ignores_same_role_fork_and_allows_helper_children(self):
        with tempfile.TemporaryDirectory() as temp:
            proc=Path(temp).resolve()
            (proc/"stat").write_text("btime 1000\n")
            (proc/"uptime").write_text(str(100/os.sysconf("SC_CLK_TCK")+0.5)+" 0\n")
            cases=[(900001,1,"FEX",["FEX","/vrserver"]),(900002,900001,"FEX",["FEX","/vrserver"]),
                   (900003,1,"FEX",["FEX","/vrwebhelper"]),(900004,900003,"FEX",["FEX","/vrwebhelper"])]
            for pid,ppid,comm,argv in cases:
                d=proc/str(pid);d.mkdir()
                (d/"comm").write_text(comm)
                (d/"cmdline").write_bytes(b"\0".join(a.encode() for a in argv))
                fields=["S",str(ppid)]+["0"]*17+["100"]
                (d/"stat").write_text(str(pid)+" (FEX) "+" ".join(fields))
            found,game=rb.processes(proc)
            self.assertFalse(game)
            self.assertEqual([(p.pid,p.role) for p in found],[(900001,"vrserver"),(900003,"vrwebhelper")])

    def test_persistent_fex_child_and_native_child_are_not_hidden(self):
        with tempfile.TemporaryDirectory() as temp:
            proc=Path(temp).resolve()
            (proc/"stat").write_text("btime 1000\n")
            (proc/"uptime").write_text("500 0\n")
            cases=[(900001,1,["FEX","/vrserver"]),(900002,900001,["FEX","/vrserver"]),
                   (900003,900001,["/native/vrserver"])]
            for pid,ppid,argv in cases:
                d=proc/str(pid);d.mkdir()
                (d/"comm").write_text("vrserver")
                (d/"cmdline").write_bytes(b"\0".join(a.encode() for a in argv))
                (d/"stat").write_text(str(pid)+" (vrserver) "+" ".join(["S",str(ppid)]+["0"]*17+["100"]))
            found,game=rb.processes(proc)
            self.assertEqual(len(found),3)

    def test_multiple_helpers_not_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve()
            (home/".local/share/Steam/config").mkdir(parents=True)
            (home/".local/share/Steam/config/steamvr.vrsettings").write_text('{"driver_alvr_server":{"blocked_by_safe_mode":false}}')
            (home/".config/alvr").mkdir(parents=True)
            (home/".config/alvr/session.json").write_text('{"client_connections":{"private-not-logged":{"trusted":true}}}')
            runtime=rb.Runtime({},home=home)
            live=[rb.Process(1,"vrserver",1,10),rb.Process(2,"vrwebhelper",2,10),rb.Process(3,"vrwebhelper",3,10)]
            with patch.object(rb,"processes",return_value=(live,False)):
                self.assertFalse(runtime.inspect().collision)

    def test_reviewed_pending_receipt_permits_one_start_and_is_not_starting(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve()
            runtime=rb.Runtime({},home=home)
            runtime.runtime_state.mkdir(mode=0o700,parents=True)
            review=home/"review.md"
            review.write_text("Reviewed fixture failure")
            gate.write_private(runtime.runtime_state/"retry-receipt.json",{"appid":250820,"attempts":1,"created_at":100,"fault_review":str(review)})
            with patch.object(rb.time,"time",return_value=110),patch.object(rb,"processes",return_value=([],False)):
                self.assertFalse(runtime._starting())
                self.assertTrue(runtime.prepare())
            self.assertEqual(runtime.receipt["created_at"],100)

    def test_reviewed_receipt_admits_only_one_native_steam_request(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve()
            runtime=rb.Runtime({},home=home)
            runtime.runtime_state.mkdir(mode=0o700,parents=True)
            review=home/"review.md";review.write_text("Reviewed one correction")
            receipt={"appid":250820,"attempts":1,"created_at":100,"fault_review":str(review)}
            gate.write_private(runtime.runtime_state/"retry-receipt.json",receipt)
            with patch.object(rb.time,"time",return_value=110),patch.object(rb,"processes",return_value=([],False)):
                self.assertTrue(runtime.prepare())
                self.assertTrue(runtime._starting())
                with self.assertRaisesRegex(LaunchError,"already"):
                    runtime.prepare()
                runtime.record("failed")
                with self.assertRaises(LaunchError): runtime._starting()
                receipt["created_at"]=111
                gate.write_private(runtime.runtime_state/"retry-receipt.json",receipt)
            with patch.object(rb.time,"time",return_value=112),patch.object(rb,"processes",return_value=([],False)):
                self.assertTrue(runtime.prepare())
            self.assertEqual(gate.read_private(runtime.runtime_state/"retry-receipt.json")["created_at"],111)

    def test_recent_old_runtime_launch_not_starting_without_live_admission_pid(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve()
            runtime=rb.Runtime({},home=home)
            runtime.runtime_state.mkdir(mode=0o700,parents=True)
            gate.write_private(runtime.runtime_state/"runtime-launch.json",{"time":100,"appid":250820})
            with patch.object(rb.time,"time",return_value=101):
                self.assertFalse(runtime._starting())

    def test_runtime_steam_request_uses_fixed_uri_and_sanitized_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve()
            runtime=rb.Runtime({"HOME":str(home),"SteamAppId":"438100","FEX_APP_CONFIG":"/private","DISPLAY":":0"},home=home)
            with patch.object(rb.subprocess,"Popen") as start:
                runtime.start()
            args,kw=start.call_args
            self.assertEqual(args[0],["/usr/bin/steam","steam://run/250820"])
            self.assertNotIn("SteamAppId",kw["env"])
            self.assertNotIn("FEX_APP_CONFIG",kw["env"])
            self.assertEqual(kw["env"]["DISPLAY"],":0")

if __name__=="__main__": unittest.main()
