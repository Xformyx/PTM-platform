"""Capture a fresh browser run with live logs, exit status and input fingerprints.

This launches the existing browser verifier; it does not start servers, enqueue
analysis, install dependencies or change any production state.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from datetime import datetime, timezone
from urllib.request import urlopen


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(paths, root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths) if p.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:5173")
    parser.add_argument("--playwright-module", default=os.environ.get("PLAYWRIGHT_MODULE"), required=not os.environ.get("PLAYWRIGHT_MODULE"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    fixture = args.fixture_dir.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_paths = [p for p in (root / "frontend/src").rglob("*") if p.suffix in {".ts", ".tsx", ".css"}]
    source_paths += list((root / "frontend/tests").glob("scatter.browser.*"))
    source_paths += [root / p for p in ("scripts/validate_scatter_browser.mjs", "scripts/run_scatter_browser_validation.py",
        "scripts/build_scatter_fixture.py", "ptm_shared/scatter_overview.py", "api-server/app/api/vector_view.py",
        "frontend/package.json", "frontend/package-lock.json", "frontend/vite.config.ts")]
    before = fingerprint(source_paths, root)
    fixture_before = fingerprint(fixture.rglob("*"), fixture)
    command = ["node", "scripts/validate_scatter_browser.mjs", "--fixture-dir", str(fixture), "--output", str(output),
               "--browser", str(args.browser), "--url", args.url]
    manifest = {"schema_version": "scatter_browser_run.v1", "started_at": now(), "status": "preflight",
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip(),
        "source_sha256": before, "fixture_sha256": fixture_before, "command": command,
        "frontend_url": args.url, "synthetic_only": True, "full_login_order_e2e": False}
    def save():
        (output / "run-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    save()
    env = {**os.environ, "PLAYWRIGHT_MODULE": args.playwright_module}
    try:
        if not args.browser.is_file() or not os.access(args.browser, os.X_OK):
            raise ValueError("Chrome executable is unavailable")
        if not (Path(args.playwright_module) / "package.json").is_file():
            raise ValueError("PLAYWRIGHT_MODULE does not name an installed package")
        package = json.loads((Path(args.playwright_module) / "package.json").read_text())
        manifest["playwright_version"] = package["version"]
        with urlopen(args.url.rstrip("/") + "/tests/scatter.browser.html", timeout=10) as response:
            html = response.read()
            if b"scatter.browser.tsx" not in html or response.status != 200:
                raise ValueError("Frontend server is not serving the scatter test entry")
            manifest["served_html_sha256"] = hashlib.sha256(html).hexdigest()
        sys.path.insert(0, str(root))
        from ptm_shared.scatter_overview import read_scatter_overview
        checked = []
        for p in sorted(fixture.glob("*-*.json")):
            if p.name == "scale-result.json": continue
            name, axis = p.stem.rsplit("-", 1)
            if json.loads(p.read_text()) != read_scatter_overview(fixture / name, "_phospho", axis):
                raise ValueError(f"Fixture differs from current reader: {p.name}")
            checked.append(p.name)
        manifest.update(status="running", current_reader_fixtures_verified=checked)
        save()
        print(json.dumps({"event": "browser_start", "fixture_count": len(checked), "output": str(output)}), flush=True)
    except Exception as exc:
        manifest.update(status="preflight_failed", failure=str(exc), finished_at=now(), browser_exit_code=None)
        save()
        (output / "stderr.log").write_text(str(exc) + "\n")
        (output / "stdout.log").write_text("")
        (output / "exit-code.txt").write_text("2\n")
        print(str(exc), file=sys.stderr, flush=True)
        return 2

    with (output / "stdout.log").open("w") as stdout, (output / "stderr.log").open("w") as stderr:
        process = subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, bufsize=1)
        manifest["browser_runner_pid"] = process.pid
        save()
        def copy(stream, logfile, console):
            for line in stream:
                logfile.write(line); logfile.flush()
                console.write(line); console.flush()
        threads = [threading.Thread(target=copy, args=(process.stdout, stdout, sys.stdout)),
                   threading.Thread(target=copy, args=(process.stderr, stderr, sys.stderr))]
        for thread in threads: thread.start()
        try:
            code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try: code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); code = process.wait()
        for thread in threads: thread.join()
    (output / "exit-code.txt").write_text(f"{code}\n")
    after = fingerprint(source_paths, root)
    fixture_after = fingerprint(fixture.rglob("*"), fixture)
    result_exists = (output / "browser-result.json").is_file()
    unchanged = before == after and fixture_before == fixture_after
    manifest.update(status="passed" if code == 0 and result_exists and unchanged else "failed",
        browser_exit_code=code, finished_at=now(), source_unchanged=before == after,
        fixture_unchanged=fixture_before == fixture_after, browser_result_present=result_exists)
    manifest["artifact_sha256"] = fingerprint((p for p in output.iterdir() if p.name != "run-manifest.json"), output)
    save()
    print(json.dumps({"event": "browser_finished", "exit_code": code, "status": manifest["status"], "output": str(output)}), flush=True)
    return 0 if manifest["status"] == "passed" else code or 2


if __name__ == "__main__":
    raise SystemExit(main())
