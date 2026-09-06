from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

REPO = "billsforAIMe/Dropbox-Governed-Execution-Relay"
REPO_ID = 1351496555
MAIN_REF = "refs/heads/main"
CANDIDATE_BRANCH = "builder/dger-gen4-fixed-dispatcher"
PREDECESSOR = "42543696c544d3bc287e65da78d07751db310e58"
PREDECESSOR_TREE = "228da8f1609beeda730a54cbcce1ebfe69a5ab9b"
CANDIDATE = "73f736d8ad4c1f11bb8ee51ff7497c74c2f41622"
CANDIDATE_TREE = "bebbc449d3c1319e2876774eec8dfef05b174ad9"
SG_REPO = "billsforAIMe/Software-Governance"
SG_COMMIT = "cffbbef934895c8c0e1e43eb4e65d77cf49293a6"
GITSTORAGE_REPO = "billsforAIMe/GitStorage"
GITSTORAGE_COMMIT = "52198fef90d5c4e7faf5a2b5a679d0ad38fbc8fb"
RULESET_ID = 21965737
PR_NUMBER = 11
SSH_REMOTE = "git@github.com:billsforAIMe/Dropbox-Governed-Execution-Relay.git"
GITHUB_ED25519_LINE = "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
GITHUB_ED25519_FP = "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"
STATE_ROOT = Path("/Users/brettmacpro/AI/State/Tools/Dropbox Governed Execution Relay")
EVIDENCE_ROOT = STATE_ROOT / "evidence" / "dger-gen4-source-publication"


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError(msg)


def plain_file(path: Path) -> bool:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(st.st_mode) and not path.is_symlink()


def find_exe(*names: str) -> str:
    for name in names:
        if "/" in name:
            p = Path(name)
            if plain_file(p) and os.access(p, os.X_OK):
                return str(p)
        else:
            p = shutil.which(name)
            if p and plain_file(Path(p)) and os.access(p, os.X_OK):
                return p
    raise RuntimeError("EXECUTABLE_NOT_FOUND:" + ",".join(names))


def run(args: list[str], *, env: dict[str, str] | None = None, input_text: str | None = None,
        timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(
        args, env=env, input=input_text, text=True,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False,
    )
    if check and cp.returncode != 0:
        raise RuntimeError(f"COMMAND_FAILED:{Path(args[0]).name}:{cp.returncode}:{cp.stderr[-800:]}")
    return cp


def gh_json(gh: str, path: str, *extra: str) -> object:
    cp = run([gh, "api", path, *extra], timeout=90)
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GH_NON_JSON:{path}") from exc


def gh_ref_sha(gh: str, repo: str, branch: str) -> str:
    obj = gh_json(gh, f"repos/{repo}/git/ref/heads/{branch}")
    require(isinstance(obj, dict), "GH_REF_NOT_OBJECT")
    node = obj.get("object")
    require(isinstance(node, dict) and isinstance(node.get("sha"), str), "GH_REF_SHA_MISSING")
    return node["sha"]


def validate_ruleset(obj: object) -> None:
    require(isinstance(obj, dict), "RULESET_NOT_OBJECT")
    require(obj.get("id") == RULESET_ID and obj.get("enforcement") == "active", "RULESET_ID_OR_STATE_MISMATCH")
    cond = obj.get("conditions")
    require(isinstance(cond, dict), "RULESET_CONDITIONS_MISSING")
    ref_name = cond.get("ref_name")
    require(isinstance(ref_name, dict), "RULESET_REF_CONDITION_MISSING")
    require("refs/heads/main" in ref_name.get("include", []), "RULESET_MAIN_NOT_INCLUDED")
    bypass = obj.get("bypass_actors")
    require(isinstance(bypass, list), "RULESET_BYPASS_MISSING")
    deploy = [x for x in bypass if isinstance(x, dict) and x.get("actor_type") == "DeployKey" and x.get("bypass_mode") == "always"]
    require(len(deploy) == 1, "RULESET_DEPLOYKEY_BYPASS_MISMATCH")
    rules = obj.get("rules")
    require(isinstance(rules, list), "RULESET_RULES_MISSING")
    kinds = {x.get("type") for x in rules if isinstance(x, dict)}
    require({"update", "deletion", "non_fast_forward"}.issubset(kinds), "RULESET_PROTECTIONS_MISSING")


def review_passes(comments: object) -> bool:
    if not isinstance(comments, list):
        return False
    required = (
        "REVIEW_PASS",
        "reviewer_role=NON_BUILDER_REVIEWER",
        f"candidate={CANDIDATE}",
        f"candidate_tree={CANDIDATE_TREE}",
        f"authoritative_predecessor={PREDECESSOR}",
        "blocking_findings=NONE",
    )
    for item in comments:
        if not isinstance(item, dict):
            continue
        body = item.get("body")
        if not isinstance(body, str):
            continue
        if body.lstrip().startswith("REVIEW_PASS") and all(token in body for token in required):
            return True
    return False


def parse_agent_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("SSH_AUTH_SOCK", "SSH_AGENT_PID"):
        m = re.search(rf"(?:^|\n){key}=([^;\n]+);", text)
        require(m is not None, f"SSH_AGENT_{key}_MISSING")
        out[key] = m.group(1)
    return out


def gs_json(gs: str, args: list[str], env: dict[str, str]) -> dict:
    cp = run([gs, *args], env=env, timeout=180, check=False)
    try:
        obj = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GITSTORAGE_NON_JSON:{args[0]}:{cp.stderr[-500:]}") from exc
    require(isinstance(obj, dict), f"GITSTORAGE_RESULT_NOT_OBJECT:{args[0]}")
    if cp.returncode != 0 or obj.get("ok") is not True:
        raise RuntimeError(f"GITSTORAGE_FAILED:{args[0]}:{json.dumps(obj, sort_keys=True)[:1000]}")
    return obj


def validate_publish_result(obj: dict) -> None:
    r = obj.get("result")
    require(isinstance(r, dict), "PUBLISH_RESULT_MISSING")
    require(r.get("published") is True, "PUBLISH_NOT_TRUE")
    require(r.get("branch") == "main", "PUBLISH_BRANCH_MISMATCH")
    require(r.get("expected_predecessor") == PREDECESSOR, "PUBLISH_EXPECTED_PREDECESSOR_MISMATCH")
    require(r.get("observed_predecessor") == PREDECESSOR, "PUBLISH_OBSERVED_PREDECESSOR_MISMATCH")
    require(r.get("candidate") == CANDIDATE, "PUBLISH_CANDIDATE_MISMATCH")
    require(r.get("resulting_remote") == CANDIDATE, "PUBLISH_REMOTE_MISMATCH")


def self_test() -> None:
    good_ruleset = {
        "id": RULESET_ID, "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "bypass_actors": [{"actor_type": "DeployKey", "bypass_mode": "always"}],
        "rules": [{"type": "update"}, {"type": "deletion"}, {"type": "non_fast_forward"}],
    }
    validate_ruleset(good_ruleset)
    bad = dict(good_ruleset)
    bad["bypass_actors"] = []
    try:
        validate_ruleset(bad)
    except RuntimeError:
        pass
    else:
        raise RuntimeError("SELFTEST_RULESET_FAIL_OPEN")
    comments = [{"body": "\n".join([
        "REVIEW_PASS",
        "reviewer_role=NON_BUILDER_REVIEWER",
        f"candidate={CANDIDATE}",
        f"candidate_tree={CANDIDATE_TREE}",
        f"authoritative_predecessor={PREDECESSOR}",
        "blocking_findings=NONE",
    ])}]
    require(review_passes(comments), "SELFTEST_REVIEW_REJECTED")
    require(not review_passes([{"body": comments[0]["body"].replace("blocking_findings=NONE", "blocking_findings=X")}]), "SELFTEST_REVIEW_FAIL_OPEN")
    env = parse_agent_env("SSH_AUTH_SOCK=/tmp/a.sock; export SSH_AUTH_SOCK;\nSSH_AGENT_PID=123; export SSH_AGENT_PID;\n")
    require(env == {"SSH_AUTH_SOCK": "/tmp/a.sock", "SSH_AGENT_PID": "123"}, "SELFTEST_AGENT_PARSE")
    validate_publish_result({"result": {
        "published": True, "branch": "main",
        "expected_predecessor": PREDECESSOR, "observed_predecessor": PREDECESSOR,
        "candidate": CANDIDATE, "resulting_remote": CANDIDATE,
    }})
    print("DGER_GEN4_SOURCE_PUBLISH_SELFTEST=PASS")


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    require(not sys.argv[1:], "UNEXPECTED_ARGUMENTS")
    old_umask = os.umask(0o077)
    run_id = f"dger-gen4-source-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    work = Path(tempfile.mkdtemp(prefix="dger-gen4-source-publish-"))
    evidence_dir = EVIDENCE_ROOT / run_id
    deploy_key_id: int | None = None
    agent_env: dict[str, str] = {}
    phase = "START"
    cleanup = {"deploy_key": "NOT_CREATED", "ssh_agent": "NOT_STARTED", "workdir": "PENDING"}
    result: dict[str, object] = {
        "schema": "dger-gen4-source-publication/v1",
        "run_id": run_id,
        "repository_id": REPO_ID,
        "predecessor": PREDECESSOR,
        "candidate": CANDIDATE,
        "candidate_tree": CANDIDATE_TREE,
        "sg_commit": SG_COMMIT,
        "gitstorage_commit": GITSTORAGE_COMMIT,
        "runtime_activation": "NOT_ATTEMPTED",
    }
    gh = gs = ssh_keygen = ssh_agent = ssh_add = ""
    try:
        phase = "RESOLVE_TOOLS"
        gh = find_exe("/opt/homebrew/bin/gh", "/usr/local/bin/gh", "gh")
        gs = find_exe("/usr/local/bin/gitstorage", "/opt/homebrew/bin/gitstorage", "gitstorage")
        ssh_keygen = find_exe("/usr/bin/ssh-keygen", "ssh-keygen")
        ssh_agent = find_exe("/usr/bin/ssh-agent", "ssh-agent")
        ssh_add = find_exe("/usr/bin/ssh-add", "ssh-add")
        result["gitstorage_executable"] = gs
        result["gitstorage_sha256"] = __import__("hashlib").sha256(Path(gs).read_bytes()).hexdigest()

        phase = "PRECHECK_AUTHORITIES"
        require(gh_ref_sha(gh, REPO, "main") == PREDECESSOR, "DGER_MAIN_MOVED")
        require(gh_ref_sha(gh, REPO, CANDIDATE_BRANCH) == CANDIDATE, "DGER_CANDIDATE_BRANCH_MOVED")
        require(gh_ref_sha(gh, SG_REPO, "main") == SG_COMMIT, "SG_MAIN_MOVED")
        require(gh_ref_sha(gh, GITSTORAGE_REPO, "main") == GITSTORAGE_COMMIT, "GITSTORAGE_MAIN_MOVED")
        commit = gh_json(gh, f"repos/{REPO}/git/commits/{CANDIDATE}")
        require(isinstance(commit, dict), "CANDIDATE_COMMIT_NOT_OBJECT")
        tree = commit.get("tree")
        require(isinstance(tree, dict) and tree.get("sha") == CANDIDATE_TREE, "CANDIDATE_TREE_MISMATCH")
        pr = gh_json(gh, f"repos/{REPO}/pulls/{PR_NUMBER}")
        require(isinstance(pr, dict), "PR_NOT_OBJECT")
        require(pr.get("state") == "open" and pr.get("merged") is False, "PR_STATE_UNEXPECTED")
        require(isinstance(pr.get("head"), dict) and pr["head"].get("sha") == CANDIDATE, "PR_HEAD_MISMATCH")
        require(isinstance(pr.get("base"), dict) and pr["base"].get("sha") == PREDECESSOR, "PR_BASE_MISMATCH")
        comments = gh_json(gh, f"repos/{REPO}/issues/{PR_NUMBER}/comments?per_page=100")
        require(review_passes(comments), "EXACT_REVIEW_PASS_NOT_FOUND")
        compare = gh_json(gh, f"repos/{REPO}/compare/{PREDECESSOR}...{CANDIDATE}")
        require(isinstance(compare, dict), "COMPARE_NOT_OBJECT")
        require(compare.get("behind_by") == 0, "CANDIDATE_BEHIND_PREDECESSOR")
        mb = compare.get("merge_base_commit")
        require(isinstance(mb, dict) and mb.get("sha") == PREDECESSOR, "MERGE_BASE_MISMATCH")
        ruleset = gh_json(gh, f"repos/{REPO}/rulesets/{RULESET_ID}")
        validate_ruleset(ruleset)
        print("prepublication_authority_review_ruleset=PASS")

        phase = "PIN_GITHUB_HOST"
        fp = run([ssh_keygen, "-lf", "-", "-E", "sha256"], input_text=GITHUB_ED25519_LINE + "\n", timeout=15)
        require(GITHUB_ED25519_FP in fp.stdout, "GITHUB_HOST_KEY_FINGERPRINT_MISMATCH")
        ssh_home = work / "ssh-home"
        ssh_dir = ssh_home / ".ssh"
        ssh_dir.mkdir(parents=True, mode=0o700)
        known_hosts = ssh_dir / "known_hosts"
        known_hosts.write_text(GITHUB_ED25519_LINE + "\n", encoding="utf-8")
        known_hosts.chmod(0o600)
        bin_dir = ssh_home / "bin"
        bin_dir.mkdir(mode=0o700)
        wrapper = bin_dir / "ssh"
        wrapper.write_text(
            "#!/bin/sh\n"
            'test -n "$DGER_PINNED_KNOWN_HOSTS" || exit 70\n'
            'exec /usr/bin/ssh -o BatchMode=yes '
            '-o UserKnownHostsFile="$DGER_PINNED_KNOWN_HOSTS" '
            '-o GlobalKnownHostsFile=/dev/null '
            '-o StrictHostKeyChecking=yes "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o700)

        phase = "CREATE_EPHEMERAL_DEPLOY_KEY"
        key = work / "dger-gen4-deploy-key"
        run([ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-C", f"{run_id}@temporary", "-f", str(key)], timeout=30)
        require(plain_file(key) and plain_file(Path(str(key) + ".pub")), "DEPLOY_KEY_FILES_INVALID")
        public_key = Path(str(key) + ".pub").read_text(encoding="utf-8").strip()
        created = gh_json(
            gh, f"repos/{REPO}/keys", "-X", "POST",
            "-f", f"title={run_id}", "-f", f"key={public_key}", "-F", "read_only=false",
        )
        require(isinstance(created, dict) and isinstance(created.get("id"), int), "DEPLOY_KEY_CREATE_RESPONSE_INVALID")
        deploy_key_id = created["id"]
        cleanup["deploy_key"] = "CREATED"
        print(f"deploy_key_created_id={deploy_key_id}")

        phase = "START_ISOLATED_AGENT"
        sock = work / "agent.sock"
        agent = run([ssh_agent, "-a", str(sock), "-s"], timeout=20)
        agent_env = parse_agent_env(agent.stdout)
        cleanup["ssh_agent"] = "STARTED"
        pub_env = os.environ.copy()
        pub_env.update(agent_env)
        run([ssh_add, str(key)], env=pub_env, timeout=20)
        listed = run([ssh_add, "-l"], env=pub_env, timeout=20)
        require(len([x for x in listed.stdout.splitlines() if x.strip()]) == 1, "SSH_AGENT_KEY_COUNT_NOT_ONE")

        phase = "GITSTORAGE_MATERIALIZE"
        gs_env = pub_env.copy()
        gs_env["HOME"] = str(ssh_home)
        gs_env["PATH"] = str(bin_dir) + os.pathsep + gs_env.get("PATH", os.defpath)
        gs_env["DGER_PINNED_KNOWN_HOSTS"] = str(known_hosts)
        repo_dir = work / "repo"
        gs_json(gs, ["clone", "--remote", SSH_REMOTE, "--destination", str(repo_dir)], gs_env)
        gs_json(gs, ["fetch", "--repo", str(repo_dir), "--remote", "origin"], gs_env)
        inspected = gs_json(gs, ["inspect-commit", "--repo", str(repo_dir), "--ref", CANDIDATE], gs_env)
        ir = inspected.get("result")
        require(isinstance(ir, dict) and ir.get("oid") == CANDIDATE and ir.get("tree") == CANDIDATE_TREE, "GITSTORAGE_CANDIDATE_IDENTITY_MISMATCH")
        anc = gs_json(gs, ["is-ancestor", "--repo", str(repo_dir), "--ancestor", PREDECESSOR, "--descendant", CANDIDATE], gs_env)
        require(isinstance(anc.get("result"), dict) and anc["result"].get("is_ancestor") is True, "GITSTORAGE_ANCESTRY_FAIL")
        rr = gs_json(gs, ["read-remote-ref", "--remote", SSH_REMOTE, "--ref", MAIN_REF], gs_env)
        require(isinstance(rr.get("result"), dict) and rr["result"].get("oid") == PREDECESSOR, "GITSTORAGE_PREPUBLISH_REMOTE_MOVED")
        print("gitstorage_prepublication=PASS")

        phase = "PUBLISH_EXACT_REVIEWED_CANDIDATE"
        pub = gs_json(gs, [
            "publish-if-predecessor", "--repo", str(repo_dir), "--remote", "origin",
            "--branch", "main", "--expected-predecessor", PREDECESSOR, "--candidate", CANDIDATE,
        ], gs_env)
        validate_publish_result(pub)
        rr2 = gs_json(gs, ["read-remote-ref", "--remote", SSH_REMOTE, "--ref", MAIN_REF], gs_env)
        require(isinstance(rr2.get("result"), dict) and rr2["result"].get("oid") == CANDIDATE, "GITSTORAGE_POSTPUBLISH_REMOTE_MISMATCH")
        require(gh_ref_sha(gh, REPO, "main") == CANDIDATE, "GITHUB_POSTPUBLISH_MAIN_MISMATCH")
        result["status"] = "PASS"
        result["authority_publication"] = "PASS"
        result["resulting_main"] = CANDIDATE
        print("authority_publication=PASS")
    except Exception as exc:
        result["status"] = "FAIL"
        result["phase"] = phase
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)[:2000]
        print(f"DGER_GEN4_SOURCE_PUBLICATION_FAIL phase={phase} error={type(exc).__name__}:{exc}", file=sys.stderr)
    finally:
        if deploy_key_id is not None and gh:
            try:
                run([gh, "api", f"repos/{REPO}/keys/{deploy_key_id}", "-X", "DELETE"], timeout=60)
                cleanup["deploy_key"] = "DELETED"
                print("deploy_key_cleanup=PASS")
            except Exception as exc:
                cleanup["deploy_key"] = f"DELETE_FAILED:{type(exc).__name__}"
                print(f"deploy_key_cleanup=FAIL:{exc}", file=sys.stderr)
                result["status"] = "FAIL"
                result.setdefault("error", "DEPLOY_KEY_CLEANUP_FAILED")
        if agent_env and ssh_agent:
            try:
                kill_env = os.environ.copy()
                kill_env.update(agent_env)
                run([ssh_agent, "-k"], env=kill_env, timeout=20)
                cleanup["ssh_agent"] = "KILLED"
                print("ssh_agent_cleanup=PASS")
            except Exception as exc:
                cleanup["ssh_agent"] = f"KILL_FAILED:{type(exc).__name__}"
                print(f"ssh_agent_cleanup=FAIL:{exc}", file=sys.stderr)
                result["status"] = "FAIL"
                result.setdefault("error", "SSH_AGENT_CLEANUP_FAILED")
        shutil.rmtree(work, ignore_errors=True)
        cleanup["workdir"] = "REMOVED"
        result["cleanup"] = cleanup
        result["completed_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            evidence_dir.mkdir(parents=True, exist_ok=False)
            evidence = evidence_dir / "RESULT.json"
            evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"evidence_path={evidence}")
        except Exception as exc:
            print(f"EVIDENCE_WRITE_FAIL:{type(exc).__name__}:{exc}", file=sys.stderr)
            result["status"] = "FAIL"
        os.umask(old_umask)
    if result.get("status") != "PASS":
        raise SystemExit(2)
    print("DGER_GEN4_SOURCE_PUBLICATION=PASS")


if __name__ == "__main__":
    main()
