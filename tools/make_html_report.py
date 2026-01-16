import argparse
import datetime as dt
import html
import os
from pathlib import Path

def file_inventory(root: Path, max_files: int = 300):
    if not root.exists():
        return {"root": str(root), "exists": False, "count": 0, "total_bytes": 0, "files": []}

    files = []
    total = 0
    for p in sorted(root.rglob("*")):
        if p.is_file():
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            rel = str(p.relative_to(root))
            files.append((rel, size))
            total += size

    shown = files[:max_files]
    return {
        "root": str(root),
        "exists": True,
        "count": len(files),
        "total_bytes": total,
        "files": shown,
        "truncated": len(files) > len(shown),
    }

def fmt_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(n)
    for u in units:
        if x < 1024.0:
            return f"{x:.2f} {u}"
        x /= 1024.0
    return f"{x:.2f} PB"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--materialx-dir", required=True)
    ap.add_argument("--mdl-dir", required=True)
    ap.add_argument("--test-log", required=True)

    ap.add_argument("--materialx-artifact-name", default="")
    ap.add_argument("--materialx-run-id", default="")
    ap.add_argument("--mdl-asset-name", default="")
    ap.add_argument("--mdl-release-tag", default="")

    ap.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    ap.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    ap.add_argument("--run-number", default=os.getenv("GITHUB_RUN_NUMBER", ""))

    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    generated_date_utc = now.strftime("%Y-%m-%d")
    generated_time_utc = now.strftime("%H:%M:%S")

    mx = file_inventory(Path(args.materialx_dir))
    mdl = file_inventory(Path(args.mdl_dir))

    log_path = Path(args.test_log)
    if log_path.exists():
        test_log_text = log_path.read_text(encoding="utf-8", errors="replace")
    else:
        test_log_text = f"(log not found: {log_path})"

    def esc(s): return html.escape(str(s))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    html_text = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Upstream Artifact Test Report</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; }}
    code, pre {{ background: #f6f8fa; padding: 8px 10px; border-radius: 6px; }}
    pre {{ overflow-x: auto; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 8px; font-size: 13px; }}
    th {{ background: #f0f0f0; text-align: left; }}
    .muted {{ color: #666; }}
  </style>
</head>
<body>
  <h1>Upstream Artifact Test Report</h1>

  <h2>Run metadata</h2>
  <ul>
    <li><b>Generated date (UTC):</b> <code>{esc(generated_date_utc)}</code></li>
    <li><b>Generated time (UTC):</b> <code>{esc(generated_time_utc)}</code></li>
    <li><b>Repo:</b> <code>{esc(args.repo)}</code></li>
    <li><b>GitHub run_id:</b> <code>{esc(args.run_id)}</code> (run_number <code>{esc(args.run_number)}</code>)</li>
  </ul>

  <h2>mx_codegen.py output</h2>
  <pre>{esc(test_log_text)}</pre>

  <h2>MaterialX</h2>
  <ul>
    <li><b>Artifact name:</b> <code>{esc(args.materialx_artifact_name)}</code></li>
    <li><b>Source run_id:</b> <code>{esc(args.materialx_run_id)}</code></li>
    <li><b>Downloaded to:</b> <code>{esc(mx["root"])}</code></li>
    <li><b>Files:</b> <code>{esc(mx["count"])}</code>, <b>Total:</b> <code>{esc(fmt_bytes(mx["total_bytes"]))}</code></li>
  </ul>

  <h3>MaterialX file sample</h3>
  <table>
    <tr><th>Path</th><th>Size</th></tr>
    {''.join(f"<tr><td><code>{esc(p)}</code></td><td><code>{esc(fmt_bytes(sz))}</code></td></tr>" for p, sz in mx.get("files", []))}
  </table>
  <p class="muted">{esc("Truncated list." if mx.get("truncated") else "")}</p>

  <h2>MDL SDK</h2>
  <ul>
    <li><b>Latest release tag:</b> <code>{esc(args.mdl_release_tag)}</code></li>
    <li><b>Downloaded asset:</b> <code>{esc(args.mdl_asset_name)}</code></li>
    <li><b>Downloaded to:</b> <code>{esc(mdl["root"])}</code></li>
    <li><b>Files:</b> <code>{esc(mdl["count"])}</code>, <b>Total:</b> <code>{esc(fmt_bytes(mdl["total_bytes"]))}</code></li>
  </ul>

</body>
</html>
"""
    out.write_text(html_text, encoding="utf-8")
    print(f"Wrote {out}")

if __name__ == "__main__":
    main()
