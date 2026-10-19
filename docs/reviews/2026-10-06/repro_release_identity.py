"""Execute a review copy of release-server.sh with fake docker/curl/git only.

Requires an already-running Ubuntu WSL distribution; refuses to start a stopped one.
All generated files/backups are synthetic and stay inside this review directory.
No real Docker, curl, Git mutation, database or model service is invoked.
"""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
running = subprocess.run(["wsl.exe", "--list", "--running", "--quiet"], capture_output=True, check=False)
if running.returncode:
    blocked = {"reviewed_commit": "fd7a532", "status": "not_dynamically_reproduced",
               "reason": "WSL child-process inventory failed with Wsl/E_ACCESSDENIED",
               "returncode": running.returncode,
               "runs": [], "real_services_invoked": False,
               "conclusion_source": "source confirmation only: release-server.sh lines 39,59,63,177-178",
               "limit": "Do not count this artifact as a successful dynamic release reproduction"}
    (OUT / "release-identity-repro-result.json").write_text(json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(blocked, ensure_ascii=False, indent=2))
    raise SystemExit(2)
names = running.stdout.decode("utf-16-le", errors="ignore").replace("\x00", "").split()
if "Ubuntu" not in names:
    raise SystemExit("Ubuntu is not already running; refusing to start it for a review")
MOCK = Path(tempfile.mkdtemp(prefix="release-mock-", dir=OUT))
def linux(path: Path) -> str:
    resolved = path.resolve()
    if OUT != resolved and OUT not in resolved.parents:
        raise ValueError("review artifact escaped intended directory")
    return "/mnt/" + resolved.drive[0].lower() + resolved.as_posix()[2:]

scripts = MOCK / "scripts/deploy"
scripts.mkdir(parents=True)
script = scripts / "release-server.sh"
script.write_text((ROOT / "scripts/deploy/release-server.sh").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
fakebin = MOCK / "fakebin"
fakebin.mkdir()
for name in ("docker-compose.yml", "docker-compose.server.yml"):
    (MOCK / name).write_text("# synthetic review config; fake docker does not parse it\n", encoding="utf-8")
(MOCK / ".env").write_text("YBT_RELEASE_TAG=synthetic-initial\nYBT_BACKUP_ROOT=" + linux(MOCK / "backups") + "\n", encoding="utf-8")
git = r'''#!/bin/bash
if [[ "$1" == rev-parse ]]; then
  cat "$(dirname "$0")/../synthetic-head.txt"
elif [[ "$1" == diff ]]; then
  exit 0
else
  echo "unsupported fake git call" >&2
  exit 91
fi
'''
docker = r'''#!/bin/bash
printf 'args=%s|APP_COMMIT=%s|BUILD_TIME=%s|YBT_RELEASE_TAG=%s\n' "$*" "$APP_COMMIT" "$BUILD_TIME" "$YBT_RELEASE_TAG" >> "$FAKE_TRACE"
if [[ "$1" == images ]]; then
  printf 'synthetic:initial synthetic-image-id synthetic-time\n'
elif [[ "$*" == *pg_restore* ]]; then
  for item in $(seq 1 120); do printf '%s; synthetic entry\n' "$item"; done
elif [[ "$*" == *'cat /tmp/release.dump'* ]]; then
  printf 'synthetic review dump bytes\n'
elif [[ "$*" == *'exec -T worker python'* ]]; then
  printf 'worker\n'
elif [[ "$*" == *'exec -T beat python'* ]]; then
  printf 'beat\n'
fi
exit 0
'''
curl = r'''#!/bin/bash
if [[ "$*" == *'/version'* ]]; then
  printf '{"component":"api","app_commit":"%s","build_time":"%s","schema_head":"202610050002"}\n' "$APP_COMMIT" "$BUILD_TIME"
elif [[ "$*" == *'/health/ready'* ]]; then
  printf '{"status":"ready"}\n'
else
  printf 'frontend HTTP 200\n'
fi
'''
for name, content in {"git": git, "docker": docker, "curl": curl}.items():
    (fakebin / name).write_text(content, encoding="utf-8", newline="\n")
subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "chmod", "+x", *[linux(fakebin / n) for n in ("git", "docker", "curl")]], check=True)

trace = MOCK / "fake-command-trace.log"
results = {"reviewed_commit": "fd7a532", "scope": "copied real release script; fake docker/curl/git; clean process environment; synthetic files only",
           "mock_directory": str(MOCK), "runs": []}
for label, commit in (("A", "a" * 40), ("B", "b" * 40)):
    (MOCK / "synthetic-head.txt").write_text(commit + "\n", encoding="utf-8")
    executed = subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "env", "-i",
        "PATH=" + linux(fakebin) + ":/usr/bin:/bin", "FAKE_TRACE=" + linux(trace),
        "/bin/bash", linux(script), "synthetic-release-" + label], capture_output=True, text=True)
    (MOCK / ("release-" + label + ".log")).write_text(executed.stdout + executed.stderr, encoding="utf-8")
    persisted = dict(line.split("=", 1) for line in (MOCK / ".env").read_text(encoding="utf-8").splitlines() if "=" in line)
    results["runs"].append({"release": label, "synthetic_git_head": commit, "returncode": executed.returncode,
                            "persisted_app_commit": persisted.get("APP_COMMIT"),
                            "persisted_build_time": persisted.get("BUILD_TIME"),
                            "persisted_release_tag": persisted.get("YBT_RELEASE_TAG"),
                            "declared_success": "发布完成" in executed.stdout})
results["build_invocations"] = [line for line in trace.read_text(encoding="utf-8").splitlines() if line.startswith("args=build ")]
results["second_release_reused_first_commit"] = results["runs"][1]["persisted_app_commit"] == results["runs"][0]["synthetic_git_head"]
results["tag_not_persisted"] = all(row["persisted_release_tag"] == "synthetic-initial" for row in results["runs"])
results["limit"] = "Offline script logic reproduction, not a real server deployment"
(OUT / "release-identity-repro-result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=2))
