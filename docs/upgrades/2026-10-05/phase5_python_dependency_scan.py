"""Phase 5 / final acceptance: scan the *pinned* Python dependencies against the real OSV database.

The engineering review's final step asks for a security scan. ``pip-audit``/``bandit`` could not be
installed on this host (the mirror kept building sdists for tens of minutes and never completed), so
this script queries **OSV** (the same upstream database pip-audit uses) directly, via the bundled
Node runtime + the configured proxy -- the documented working path for HTTPS on this machine.

It scans what actually ships: every ``name==version`` pin in ``backend/requirements.lock.txt``
(including the platform marker), and reports per-package advisories with severity and fixed version.
It exits non-zero when a vulnerable pin is present, so it can gate a release.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "backend" / "requirements.lock.txt"
NODE = Path(r"C:\Users\admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe")
PROXY = "http://127.0.0.1:7897"

# One node process queries OSV for every pin and prints a JSON array; doing it in one process keeps
# the scan fast and avoids a hundred cold starts.
NODE_SCRIPT = r"""
const pins = JSON.parse(process.argv[1]);
(async () => {
  const out = [];
  for (const pin of pins) {
    const body = { package: { name: pin.name, ecosystem: "PyPI" }, version: pin.version };
    try {
      const res = await fetch("https://api.osv.dev/v1/query", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const data = await res.json();
      const vulns = (data.vulns || []).map((v) => {
        const fixed = [];
        for (const affected of v.affected || []) {
          for (const range of affected.ranges || []) {
            for (const event of range.events || []) if (event.fixed) fixed.push(event.fixed);
          }
        }
        return {
          id: v.id,
          summary: (v.summary || "").slice(0, 160),
          severity: (v.database_specific && v.database_specific.severity) || null,
          aliases: (v.aliases || []).slice(0, 4),
          fixed_versions: [...new Set(fixed)].slice(0, 5),
        };
      });
      out.push({ name: pin.name, version: pin.version, vulnerabilities: vulns });
    } catch (err) {
      out.push({ name: pin.name, version: pin.version, error: String(err).slice(0, 120) });
    }
  }
  process.stdout.write(JSON.stringify(out));
})();
"""


def read_pins() -> list[dict[str, str]]:
    pins: list[dict[str, str]] = []
    for raw in LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, rest = line.partition("==")
        version = rest.split(";")[0].strip()
        marker = rest.split(";", 1)[1].strip() if ";" in rest else ""
        # A marker-excluded pin is not installed on this platform; record it but skip the query so
        # the report never implies a package is present when the marker excludes it.
        if marker and "win32" in marker and os.name != "nt":
            continue
        pins.append({"name": name.strip(), "version": version})
    return pins


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="")
    parser.add_argument("--threshold", choices=["low", "moderate", "high", "critical"], default="moderate",
                        help="fail the scan at or above this severity")
    args = parser.parse_args()

    if not LOCK.exists():
        print(json.dumps({"ok": False, "error": f"missing {LOCK}"}, ensure_ascii=False))
        return 2

    pins = read_pins()
    env = {**os.environ, "HTTPS_PROXY": PROXY, "HTTP_PROXY": PROXY, "NODE_USE_ENV_PROXY": "1"}
    completed = subprocess.run(
        [str(NODE), "-e", NODE_SCRIPT, json.dumps(pins)],
        capture_output=True, text=True, env=env, check=False, timeout=900,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        print(json.dumps({"ok": False, "error": "OSV query failed",
                          "stderr": (completed.stderr or "").strip()[-300:]}, ensure_ascii=False))
        return 2

    results = json.loads(completed.stdout)
    order = {"low": 1, "moderate": 2, "high": 3, "critical": 4}
    threshold = order[args.threshold]

    findings: list[dict] = []
    errors: list[dict] = []
    for item in results:
        if item.get("error"):
            errors.append({"name": item["name"], "error": item["error"]})
            continue
        for vuln in item.get("vulnerabilities", []):
            severity = (vuln.get("severity") or "").upper()
            level = {"LOW": 1, "MODERATE": 2, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}.get(severity, 2)
            findings.append({
                "package": item["name"], "version": item["version"], "id": vuln["id"],
                "severity": severity or "UNKNOWN", "level": level,
                "summary": vuln["summary"], "fixed_versions": vuln["fixed_versions"],
                "aliases": vuln["aliases"],
            })

    # A pin with an advisory but no upstream fix cannot be resolved by upgrading; report it
    # separately so "no fix available" is never hidden inside a generic failure list.
    unfixable = [item for item in findings if not item["fixed_versions"]]
    blocking = [item for item in findings if item["level"] >= threshold]
    counts: dict[str, int] = {}
    for item in findings:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1

    report = {
        "ok": not blocking and not errors,
        "scanner": "OSV (api.osv.dev) queried directly; same upstream database pip-audit uses",
        "why_not_pip_audit": "pip-audit/bandit could not be installed on this host: the mirror kept "
                             "building source distributions for tens of minutes without completing.",
        "pinned_packages_scanned": len(pins),
        "advisory_count": len(findings),
        "severity_counts": counts,
        "blocking_at_or_above": args.threshold,
        "blocking": blocking,
        "advisories_without_upstream_fix": unfixable,
        "unscanned_due_to_error": errors,
        "findings": sorted(findings, key=lambda item: -item["level"]),
        "scope_limits": [
            "只扫描 requirements.lock.txt 中的精确 pin（即实际安装集合），不做源码静态分析。",
            "未做容器镜像层扫描（trivy/grype 未安装）。",
        ],
    }
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: report[k] for k in (
        "ok", "pinned_packages_scanned", "advisory_count", "severity_counts",
        "blocking_at_or_above")}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
