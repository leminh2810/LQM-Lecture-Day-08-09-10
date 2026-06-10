#!/usr/bin/env python3
"""Local dashboard for Day 10 pipeline demos.

Run:
  python dashboard_server.py

Open:
  http://127.0.0.1:8765
"""

from __future__ import annotations

import csv
import cgi
import json
import os
import subprocess
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts"


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _latest(pattern: str) -> Path | None:
    files = list(ROOT.glob(pattern))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _read_log(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    data: dict[str, object] = {"path": _rel(path), "lines": path.read_text(encoding="utf-8").splitlines()}
    for line in data["lines"]:
        if "=" in line and not line.startswith("expectation["):
            key, value = line.split("=", 1)
            if key in {"run_id", "raw_records", "cleaned_records", "quarantine_records", "cleaned_csv", "quarantine_csv"}:
                data[key] = value
    expectations = []
    for line in data["lines"]:
        if line.startswith("expectation["):
            name = line.split("]", 1)[0].replace("expectation[", "")
            state = "FAIL" if " FAIL " in line else "OK"
            severity = "halt" if "(halt)" in line else "warn"
            detail = line.split("::", 1)[1].strip() if "::" in line else ""
            expectations.append({"name": name, "state": state, "severity": severity, "detail": detail})
    data["expectations"] = expectations
    data["pipeline_ok"] = any(line == "PIPELINE_OK" for line in data["lines"])
    data["pipeline_halt"] = any("PIPELINE_HALT" in line for line in data["lines"])
    return data


def _summarize_eval(path: Path | None) -> dict:
    if not path or not path.exists():
        return {"path": "", "rows": [], "summary": {}}
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    contains = sum(1 for r in rows if r.get("contains_expected") in {"yes", "true", "True"})
    forbidden = sum(1 for r in rows if r.get("hits_forbidden") in {"yes", "true", "True"})
    top1 = sum(1 for r in rows if r.get("top1_doc_expected", "") in {"yes", ""})
    return {
        "path": _rel(path),
        "rows": rows,
        "summary": {
            "total": len(rows),
            "contains_pass": contains,
            "forbidden_hits": forbidden,
            "top1_pass": top1,
        },
    }


def _summarize_grading(path: Path | None) -> dict:
    if not path or not path.exists():
        return {"path": "", "rows": [], "summary": {}}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    contains = sum(1 for r in rows if r.get("contains_expected") is True)
    forbidden_ok = sum(1 for r in rows if r.get("hits_forbidden") is False)
    top1 = sum(1 for r in rows if r.get("top1_doc_matches") in {True, None})
    return {
        "path": _rel(path),
        "rows": rows,
        "summary": {
            "total": len(rows),
            "contains_pass": contains,
            "forbidden_ok": forbidden_ok,
            "top1_pass": top1,
        },
    }


def _raw_summary() -> dict:
    raw = ROOT / "data" / "raw" / "policy_export_dirty.csv"
    if not raw.exists():
        return {}
    counts: dict[str, int] = {}
    rows = list(csv.DictReader(raw.open(encoding="utf-8")))
    for row in rows:
        doc_id = row.get("doc_id", "")
        counts[doc_id] = counts.get(doc_id, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    return {"path": _rel(raw), "records": len(rows), "unique_doc_ids": len(counts), "top_doc_ids": top}


def _read_csv_rows(path: Path | None, limit: int = 8) -> list[dict[str, str]]:
    if not path or not path.exists():
        return []
    return list(csv.DictReader(path.open(encoding="utf-8")))[:limit]


def _find_csv_row(path: Path | None, key: str, value: str) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    for row in csv.DictReader(path.open(encoding="utf-8")):
        if row.get(key) == value:
            return row
    return {}


def _example_rows(manifest: dict) -> dict:
    raw_path = ROOT / "data" / "raw" / "policy_export_dirty.csv"
    raw_rows = list(csv.DictReader(raw_path.open(encoding="utf-8"))) if raw_path.exists() else []

    def first_raw(predicate) -> dict[str, str]:
        return next((row for row in raw_rows if predicate(row)), {})

    cleaned_path = ROOT / str(manifest.get("cleaned_csv", "")) if manifest.get("cleaned_csv") else _latest("artifacts/cleaned/cleaned_*.csv")
    quarantine_name = ""
    run_id = manifest.get("run_id", "")
    if run_id:
        quarantine_name = f"artifacts/quarantine/quarantine_{str(run_id).replace(':', '-')}.csv"
    quarantine_path = ROOT / quarantine_name if quarantine_name else _latest("artifacts/quarantine/quarantine_*.csv")

    return {
        "raw_refund_stale": first_raw(lambda r: r.get("doc_id") == "policy_refund_v4" and "14 ngày" in r.get("chunk_text", "")),
        "raw_hr_stale": first_raw(lambda r: r.get("doc_id") == "hr_leave_policy" and "10 ngày phép năm" in r.get("chunk_text", "")),
        "raw_access_control": first_raw(lambda r: r.get("doc_id") == "access_control_sop"),
        "cleaned_rows": _read_csv_rows(cleaned_path, limit=6),
        "quarantine_rows": _read_csv_rows(quarantine_path, limit=8),
        "refund_bad": _find_csv_row(ROOT / "artifacts" / "eval" / "after_inject_bad.csv", "question_id", "q_refund_window"),
        "refund_good": _find_csv_row(ROOT / "artifacts" / "eval" / "after_fix_sprint3.csv", "question_id", "q_refund_window"),
        "hr_good": _find_csv_row(ROOT / "artifacts" / "eval" / "after_fix_sprint3.csv", "question_id", "q_hr_annual_leave_under3"),
        "sla_good": _find_csv_row(ROOT / "artifacts" / "eval" / "after_fix_sprint3.csv", "question_id", "q_p1_escalation"),
    }


def _status() -> dict:
    latest_log = _latest("artifacts/logs/run_*.log")
    latest_manifest = _latest("artifacts/manifests/manifest_*.json")
    manifest = {}
    if latest_manifest and latest_manifest.exists():
        manifest = json.loads(latest_manifest.read_text(encoding="utf-8"))
        manifest["_path"] = _rel(latest_manifest)
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "raw": _raw_summary(),
        "log": _read_log(latest_log),
        "manifest": manifest,
        "eval_after_fix": _summarize_eval(ROOT / "artifacts" / "eval" / "eval_after_fix.csv"),
        "after_inject_bad": _summarize_eval(ROOT / "artifacts" / "eval" / "after_inject_bad.csv"),
        "after_fix_sprint3": _summarize_eval(ROOT / "artifacts" / "eval" / "after_fix_sprint3.csv"),
        "grading": _summarize_grading(ROOT / "artifacts" / "eval" / "grading_run.jsonl"),
        "examples": _example_rows(manifest),
    }


ACTIONS: dict[str, list[str]] = {
    "pipeline": [sys.executable, "etl_pipeline.py", "run"],
    "inject": [sys.executable, "etl_pipeline.py", "run", "--run-id", "inject-bad", "--no-refund-fix", "--skip-validate"],
    "restore": [sys.executable, "etl_pipeline.py", "run", "--run-id", "after-fix-dashboard"],
    "eval": [sys.executable, "eval_retrieval.py", "--out", "artifacts/eval/eval_after_fix.csv"],
    "eval_bad": [sys.executable, "eval_retrieval.py", "--out", "artifacts/eval/after_inject_bad.csv"],
    "eval_good": [sys.executable, "eval_retrieval.py", "--out", "artifacts/eval/after_fix_sprint3.csv"],
    "grading": [sys.executable, "grading_run.py", "--out", "artifacts/eval/grading_run.jsonl"],
}


def _safe_upload_name(name: str) -> str:
    stem = Path(name or "uploaded.csv").name
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in stem)
    if not cleaned.lower().endswith(".csv"):
        cleaned += ".csv"
    return cleaned


def _run_uploaded_csv(file_name: str, data: bytes) -> dict:
    if not data:
        return {"ok": False, "error": "Uploaded file is empty."}
    upload_dir = ART / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    saved = upload_dir / f"{stamp}_{_safe_upload_name(file_name)}"
    saved.write_bytes(data)

    run_id = f"upload-{stamp}"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("HF_HUB_OFFLINE", "1")
    cmd = [sys.executable, "etl_pipeline.py", "run", "--run-id", run_id, "--raw", str(saved)]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "run_id": run_id,
        "uploaded_path": _rel(saved),
        "output": proc.stdout,
    }


def _run_action(action: str) -> dict:
    if action not in ACTIONS:
        return {"ok": False, "error": f"Unknown action: {action}"}
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("HF_HUB_OFFLINE", "1")
    proc = subprocess.run(
        ACTIONS[action],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
    )
    return {"ok": proc.returncode == 0, "returncode": proc.returncode, "output": proc.stdout}


def _query_question(question: str, top_k: int = 5) -> dict:
    question = (question or "").strip()
    if not question:
        return {"ok": False, "error": "Question is empty."}
    top_k = max(1, min(int(top_k or 5), 10))
    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        return {"ok": False, "error": "Missing chromadb/sentence-transformers. Run pip install -r requirements.txt."}

    env = os.environ.copy()
    env.setdefault("HF_HUB_OFFLINE", "1")
    db_path = os.environ.get("CHROMA_DB_PATH", str(ROOT / "chroma_db"))
    collection_name = os.environ.get("CHROMA_COLLECTION", "day10_kb")
    model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    try:
        client = chromadb.PersistentClient(path=db_path)
        emb = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
        col = client.get_collection(name=collection_name, embedding_function=emb)
        res = col.query(query_texts=[question], n_results=top_k)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    ids = (res.get("ids") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]
    results = []
    for idx, doc in enumerate(docs):
        meta = metas[idx] if idx < len(metas) else {}
        distance = distances[idx] if idx < len(distances) else None
        results.append(
            {
                "rank": idx + 1,
                "id": ids[idx] if idx < len(ids) else "",
                "doc_id": meta.get("doc_id", ""),
                "effective_date": meta.get("effective_date", ""),
                "run_id": meta.get("run_id", ""),
                "distance": distance,
                "document": doc,
                "signals": {
                    "has_7_ngay": "7 ngày" in doc.lower(),
                    "has_14_ngay": "14 ngày" in doc.lower(),
                    "has_10_phut": "10 phút" in doc.lower(),
                    "has_12_ngay": "12 ngày" in doc.lower(),
                    "has_10_ngay_phep": "10 ngày phép" in doc.lower(),
                    "has_access_approver": "it manager" in doc.lower() or "ciso" in doc.lower(),
                },
            }
        )

    top = results[0] if results else {}
    return {
        "ok": True,
        "question": question,
        "top_k": top_k,
        "collection": collection_name,
        "model": model_name,
        "top1_doc_id": top.get("doc_id", ""),
        "results": results,
        "processing": [
            {"step": "1. Query", "detail": "Câu hỏi được gửi tới embedding model để tạo query vector."},
            {"step": "2. Vector search", "detail": f"Chroma collection `{collection_name}` trả về top-{top_k} chunk gần nhất."},
            {"step": "3. Metadata check", "detail": "Mỗi chunk hiển thị doc_id, effective_date, run_id để trace về pipeline run."},
            {"step": "4. Evidence scan", "detail": "App đánh dấu các tín hiệu như 7 ngày, 14 ngày, 10 phút, 12 ngày, IT Manager/CISO."},
        ],
    }


HTML = r"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Day 10 Pipeline Dashboard</title>
  <style>
    :root { --bg:#f6f7f9; --ink:#1f2328; --muted:#667085; --line:#d7dce2; --blue:#2e548a; --red:#c83538; --green:#1f8f62; --amber:#b7791f; --teal:#0d7377; --card:#fff; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--ink); font-family:Segoe UI, Arial, sans-serif; }
    header { background:#fff; border-bottom:1px solid var(--line); padding:18px 24px; position:sticky; top:0; z-index:2; }
    h1 { margin:0; font-size:22px; }
    main { padding:20px 24px 40px; max-width:1400px; margin:auto; }
    .grid { display:grid; gap:14px; }
    .cols4 { grid-template-columns:repeat(4, minmax(0, 1fr)); }
    .cols2 { grid-template-columns:1fr 1fr; }
    .card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:16px; box-shadow:0 1px 2px rgba(0,0,0,.03); }
    .hero { display:grid; grid-template-columns:1.25fr .75fr; gap:14px; align-items:stretch; }
    .heroPanel { background:linear-gradient(135deg, #1a3355, #0d7377); color:white; border:0; }
    .heroPanel .small { color:rgba(255,255,255,.78); }
    .heroTitle { font-size:28px; font-weight:800; margin-bottom:10px; }
    .heroCopy { max-width:820px; color:rgba(255,255,255,.86); line-height:1.45; }
    .metric b { display:block; font-size:28px; margin-top:6px; }
    .metric span, .small { color:var(--muted); font-size:13px; }
    button { border:1px solid var(--blue); background:var(--blue); color:white; border-radius:6px; padding:9px 11px; font-weight:650; cursor:pointer; }
    button.secondary { background:white; color:var(--blue); }
    button.warn { border-color:var(--amber); background:var(--amber); }
    button:disabled { opacity:.55; cursor:wait; }
    .actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
    .pillRow { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }
    .pill { display:inline-flex; align-items:center; border-radius:999px; padding:6px 10px; background:#eef4fb; color:#1a3355; font-size:12px; font-weight:700; border:1px solid #d8e5f3; }
    .pill.red { background:#fff1f1; border-color:#ffd1d1; color:#9b1c1c; }
    .pill.green { background:#ecfdf3; border-color:#c7f0d7; color:#166534; }
    .pill.amber { background:#fff8e6; border-color:#f4d48b; color:#8a5a00; }
    .pipeline { display:grid; grid-template-columns:repeat(5, 1fr); gap:10px; align-items:stretch; }
    .step { border:1px solid var(--line); border-radius:8px; padding:12px; background:#fbfcfd; min-height:92px; }
    .step strong { display:block; margin-bottom:8px; }
    .ok { color:var(--green); font-weight:700; }
    .fail { color:var(--red); font-weight:700; }
    .warnText { color:var(--amber); font-weight:700; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th, td { border-bottom:1px solid var(--line); padding:8px 7px; text-align:left; vertical-align:top; }
    th { color:#344054; background:#f8fafc; position:sticky; top:63px; }
    .scroll { max-height:360px; overflow:auto; border:1px solid var(--line); border-radius:8px; }
    pre { white-space:pre-wrap; word-break:break-word; background:#111827; color:#e5e7eb; padding:12px; border-radius:8px; max-height:340px; overflow:auto; }
    .bar { height:10px; background:#e5e7eb; border-radius:999px; overflow:hidden; margin-top:8px; }
    .bar > div { height:100%; background:var(--green); }
    .barStack { display:flex; height:16px; border-radius:999px; overflow:hidden; background:#e5e7eb; margin-top:10px; }
    .barClean { background:var(--green); }
    .barQuar { background:var(--amber); }
    .scenarioGrid { display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; }
    .scenario { border:1px solid var(--line); border-radius:8px; padding:12px; background:#fbfcfd; cursor:pointer; min-height:126px; }
    .scenario:hover { border-color:var(--blue); box-shadow:0 2px 8px rgba(46,84,138,.12); }
    .scenario b { display:block; margin-bottom:8px; }
    .exampleGrid { display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; }
    .example { border:1px solid var(--line); border-radius:8px; padding:12px; background:#fff; }
    .example h3 { margin:0 0 8px; font-size:15px; }
    .mono { font-family:Consolas, monospace; font-size:12px; line-height:1.45; white-space:pre-wrap; word-break:break-word; color:#344054; }
    .compareCards { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:10px; }
    .badCard { border-left:5px solid var(--red); }
    .goodCard { border-left:5px solid var(--green); }
    .queryBox { display:grid; grid-template-columns:1fr 90px auto; gap:8px; margin-top:12px; }
    .uploadBox { display:grid; grid-template-columns:1fr auto; gap:8px; margin-top:12px; }
    input, select { border:1px solid var(--line); border-radius:6px; padding:10px; font:inherit; min-width:0; }
    input[type=file] { background:#fff; }
    .resultCard { border:1px solid var(--line); border-radius:8px; padding:12px; margin-top:10px; background:#fff; }
    .rank { display:inline-flex; width:28px; height:28px; align-items:center; justify-content:center; border-radius:50%; background:var(--blue); color:#fff; font-weight:800; margin-right:8px; }
    .signal { display:inline-flex; padding:4px 8px; border-radius:999px; font-size:12px; margin:4px 4px 0 0; background:#eef4fb; color:#1a3355; border:1px solid #d8e5f3; }
    .signal.hit { background:#ecfdf3; border-color:#c7f0d7; color:#166534; }
    .signal.bad { background:#fff1f1; border-color:#ffd1d1; color:#9b1c1c; }
    @media (max-width: 900px) { .cols4, .cols2, .pipeline, .hero, .scenarioGrid, .exampleGrid, .compareCards { grid-template-columns:1fr; } th { position:static; } }
  </style>
</head>
<body>
  <header>
    <h1>Day 10 Data Pipeline Dashboard</h1>
    <div class="small" id="stamp">Đang tải...</div>
  </header>
  <main class="grid">
    <section class="hero">
      <div class="card heroPanel">
        <div class="small">AI in Action · Day 10</div>
        <div class="heroTitle">Data pipeline observability lab</div>
        <div class="heroCopy">Theo dõi raw export, cleaning, quarantine, expectation halt, Chroma embed và before/after retrieval trong một màn hình. Dùng các nút bên dưới để demo lỗi dữ liệu xấu rồi restore dữ liệu sạch.</div>
        <div class="pillRow">
          <span class="pill green">clean → validate → embed</span>
          <span class="pill amber">inject corruption</span>
          <span class="pill">grading 10 câu</span>
        </div>
      </div>
      <div class="card">
        <strong>Kịch bản xem nhanh</strong>
        <div class="small">Bấm một thẻ để xem ví dụ nổi bật trong phần evidence.</div>
        <div class="pillRow">
          <span class="pill red">Refund 14→7 ngày</span>
          <span class="pill">HR 10→12 ngày</span>
          <span class="pill">Access source missing</span>
          <span class="pill">Freshness FAIL</span>
        </div>
      </div>
    </section>

    <section class="card">
      <strong>Chạy thử các bước</strong>
      <div class="actions">
        <button onclick="runAction('pipeline')">Run pipeline</button>
        <button class="warn" onclick="runAction('inject')">Inject bad</button>
        <button class="secondary" onclick="runAction('eval_bad')">Eval bad</button>
        <button onclick="runAction('restore')">Restore clean</button>
        <button class="secondary" onclick="runAction('eval_good')">Eval good</button>
        <button class="secondary" onclick="runAction('eval')">Eval after fix</button>
        <button onclick="runAction('grading')">Grading</button>
        <button class="secondary" onclick="loadStatus()">Refresh</button>
      </div>
    </section>

    <section class="card">
      <strong>Chèn file raw CSV và chạy pipeline</strong>
      <div class="small">Chọn CSV có schema giống `policy_export_dirty.csv`. App sẽ lưu file vào `artifacts/uploads/`, chạy `etl_pipeline.py run --raw ...`, rồi cập nhật metrics/log mới nhất.</div>
      <div class="uploadBox">
        <input id="uploadInput" type="file" accept=".csv,text/csv">
        <button onclick="uploadAndRun()">Upload + run</button>
      </div>
      <div id="uploadStatus" class="small"></div>
    </section>

    <section class="grid cols4">
      <div class="card metric"><span>Raw records</span><b id="rawRecords">-</b><span id="rawPath"></span></div>
      <div class="card metric"><span>Cleaned records</span><b id="cleanedRecords">-</b><span>latest run</span></div>
      <div class="card metric"><span>Quarantine records</span><b id="quarantineRecords">-</b><span>latest run</span></div>
      <div class="card metric"><span>Grading</span><b id="gradingMetric">-</b><span>contains + forbidden</span></div>
    </section>

    <section class="card">
      <strong>Pipeline flow</strong>
      <div id="ratio"></div>
      <div class="pipeline" id="flow"></div>
    </section>

    <section class="card">
      <strong>Ví dụ để xem</strong>
      <div class="scenarioGrid" id="scenarios"></div>
    </section>

    <section class="card">
      <strong>Test 1 câu hỏi trực tiếp</strong>
      <div class="small">Nhập câu hỏi, app sẽ query Chroma và hiển thị top-k chunk cùng metadata trace.</div>
      <div class="queryBox">
        <input id="questionInput" value="Theo chính sách hoàn tiền hiện hành, khách hàng có tối đa bao nhiêu ngày làm việc để gửi yêu cầu hoàn tiền sau khi đơn được xác nhận?">
        <select id="topKInput">
          <option value="3">top-3</option>
          <option value="5" selected>top-5</option>
          <option value="10">top-10</option>
        </select>
        <button onclick="runQuery()">Test query</button>
      </div>
      <div class="actions">
        <button class="secondary" onclick="setQuestion('Theo chính sách hoàn tiền hiện hành, khách hàng có tối đa bao nhiêu ngày làm việc để gửi yêu cầu hoàn tiền sau khi đơn được xác nhận?')">Ví dụ refund</button>
        <button class="secondary" onclick="setQuestion('Nhân viên dưới 3 năm kinh nghiệm được bao nhiêu ngày phép năm theo HR 2026?')">Ví dụ HR</button>
        <button class="secondary" onclick="setQuestion('Nếu không có phản hồi với ticket P1 sau bao lâu thì hệ thống auto escalate?')">Ví dụ SLA</button>
        <button class="secondary" onclick="setQuestion('Level 4 Admin Access yêu cầu phê duyệt bởi ai?')">Ví dụ access</button>
      </div>
      <div id="queryResult"></div>
    </section>

    <section class="card">
      <strong>Raw → cleaned / quarantine examples</strong>
      <div class="exampleGrid" id="examples"></div>
    </section>

    <section class="grid cols2">
      <div class="card">
        <strong>Expectations</strong>
        <div class="scroll"><table id="expectations"></table></div>
      </div>
      <div class="card">
        <strong>Raw doc_id distribution</strong>
        <div class="scroll"><table id="rawDist"></table></div>
      </div>
    </section>

    <section class="grid cols2">
      <div class="card">
        <strong>Before / after evidence</strong>
        <div id="comparison"></div>
        <div id="spotlight"></div>
      </div>
      <div class="card">
        <strong>Latest command output</strong>
        <pre id="output">Chưa chạy lệnh trong dashboard.</pre>
      </div>
    </section>

    <section class="card">
      <strong>Grading results</strong>
      <div class="scroll"><table id="gradingTable"></table></div>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    let busy = false;

    function yesNo(ok) { return ok ? '<span class="ok">PASS</span>' : '<span class="fail">FAIL</span>'; }
    function esc(v) {
      return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    function rowText(row, fields) {
      if (!row || Object.keys(row).length === 0) return 'Chưa có dữ liệu.';
      return fields.map(f => `${f}: ${row[f] ?? ''}`).join('\n');
    }

    async function loadStatus() {
      const res = await fetch('/api/status');
      const data = await res.json();
      render(data);
    }

    async function runAction(action) {
      if (busy) return;
      busy = true;
      [...document.querySelectorAll('button')].forEach(b => b.disabled = true);
      $('output').textContent = 'Running ' + action + '...';
      try {
        const res = await fetch('/api/run', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action})});
        const data = await res.json();
        $('output').textContent = (data.ok ? 'OK' : 'FAILED') + ' rc=' + data.returncode + '\n\n' + (data.output || data.error || '');
        await loadStatus();
      } catch (err) {
        $('output').textContent = String(err);
      } finally {
        busy = false;
        [...document.querySelectorAll('button')].forEach(b => b.disabled = false);
      }
    }

    async function uploadAndRun() {
      const file = $('uploadInput').files[0];
      if (!file) {
        $('uploadStatus').innerHTML = '<span class="fail">Hãy chọn một file CSV trước.</span>';
        return;
      }
      const fd = new FormData();
      fd.append('file', file);
      $('uploadStatus').textContent = 'Đang upload và chạy pipeline...';
      $('output').textContent = 'Upload + run: ' + file.name;
      [...document.querySelectorAll('button')].forEach(b => b.disabled = true);
      try {
        const res = await fetch('/api/upload-run', {method:'POST', body:fd});
        const data = await res.json();
        $('uploadStatus').innerHTML = data.ok
          ? `<span class="ok">OK</span> run_id=${esc(data.run_id)} · file=${esc(data.uploaded_path)}`
          : `<span class="fail">FAILED</span> ${esc(data.error || ('rc=' + data.returncode))}`;
        $('output').textContent = (data.ok ? 'OK' : 'FAILED') + ' rc=' + data.returncode + '\nrun_id=' + (data.run_id || '') + '\nfile=' + (data.uploaded_path || '') + '\n\n' + (data.output || data.error || '');
        await loadStatus();
      } catch (err) {
        $('uploadStatus').innerHTML = `<span class="fail">${esc(err)}</span>`;
      } finally {
        [...document.querySelectorAll('button')].forEach(b => b.disabled = false);
      }
    }

    function setQuestion(q) {
      $('questionInput').value = q;
      runQuery();
    }

    async function runQuery() {
      const question = $('questionInput').value;
      const top_k = Number($('topKInput').value || 5);
      $('queryResult').innerHTML = '<div class="small">Đang query vector store...</div>';
      try {
        const res = await fetch('/api/query', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({question, top_k})});
        const data = await res.json();
        renderQuery(data);
      } catch (err) {
        $('queryResult').innerHTML = `<div class="fail">${esc(err)}</div>`;
      }
    }

    function renderQuery(data) {
      if (!data.ok) {
        $('queryResult').innerHTML = `<div class="fail">${esc(data.error || 'Query failed')}</div>`;
        return;
      }
      const steps = (data.processing || []).map(s => `<div class="step"><strong>${esc(s.step)}</strong><div class="small">${esc(s.detail)}</div></div>`).join('');
      const cards = (data.results || []).map(r => {
        const sig = r.signals || {};
        const signals = [
          ['7 ngày', sig.has_7_ngay, false],
          ['14 ngày', sig.has_14_ngay, true],
          ['10 phút', sig.has_10_phut, false],
          ['12 ngày', sig.has_12_ngay, false],
          ['10 ngày phép', sig.has_10_ngay_phep, true],
          ['IT Manager/CISO', sig.has_access_approver, false],
        ].map(([name, hit, bad]) => `<span class="signal ${hit ? (bad ? 'bad' : 'hit') : ''}">${esc(name)} ${hit ? '✓' : ''}</span>`).join('');
        const dist = typeof r.distance === 'number' ? r.distance.toFixed(4) : '-';
        return `<div class="resultCard">
          <div><span class="rank">${r.rank}</span><b>${esc(r.doc_id)}</b> <span class="small">distance=${dist} · effective=${esc(r.effective_date)} · run=${esc(r.run_id)}</span></div>
          <div class="pillRow"><span class="pill">chunk_id: ${esc(r.id)}</span></div>
          <div class="mono">${esc(r.document)}</div>
          <div>${signals}</div>
        </div>`;
      }).join('');
      $('queryResult').innerHTML = `
        <div class="pillRow"><span class="pill green">Top-1: ${esc(data.top1_doc_id)}</span><span class="pill">Collection: ${esc(data.collection)}</span><span class="pill">Model: ${esc(data.model)}</span></div>
        <div class="pipeline" style="margin-top:12px">${steps}</div>
        <div>${cards}</div>`;
    }

    function render(data) {
      $('stamp').textContent = 'Cập nhật: ' + data.timestamp;
      $('rawRecords').textContent = data.raw.records ?? '-';
      $('rawPath').textContent = (data.raw.unique_doc_ids ?? '-') + ' unique doc_id · ' + (data.raw.path || '');
      $('cleanedRecords').textContent = data.log.cleaned_records ?? '-';
      $('quarantineRecords').textContent = data.log.quarantine_records ?? '-';

      const gs = data.grading.summary || {};
      $('gradingMetric').textContent = gs.total ? `${gs.contains_pass}/${gs.total}` : '-';
      const rawCount = Number(data.log.raw_records || data.raw.records || 0);
      const cleanCount = Number(data.log.cleaned_records || 0);
      const quarCount = Number(data.log.quarantine_records || 0);
      const cleanPct = rawCount ? Math.round(cleanCount * 100 / rawCount) : 0;
      const quarPct = rawCount ? Math.round(quarCount * 100 / rawCount) : 0;
      $('ratio').innerHTML = `
        <div class="small">Tỉ lệ latest run: cleaned ${cleanPct}% · quarantine ${quarPct}%</div>
        <div class="barStack"><div class="barClean" style="width:${cleanPct}%"></div><div class="barQuar" style="width:${quarPct}%"></div></div>
        <div class="pillRow"><span class="pill green">cleaned ${cleanCount}</span><span class="pill amber">quarantine ${quarCount}</span><span class="pill">raw ${rawCount}</span></div>`;

      const okPipe = data.log.pipeline_ok;
      const freshness = data.log.lines?.find(x => x.startsWith('freshness_check=')) || 'freshness_check=NA';
      $('flow').innerHTML = [
        ['Ingest', `${data.log.raw_records || '-'} raw records`, true],
        ['Clean', `${data.log.cleaned_records || '-'} cleaned`, true],
        ['Quarantine', `${data.log.quarantine_records || '-'} flagged`, true],
        ['Validate', `${(data.log.expectations || []).filter(e => e.state === 'OK').length}/${(data.log.expectations || []).length} OK`, !data.log.pipeline_halt],
        ['Embed / Publish', okPipe ? 'PIPELINE_OK' : 'not published', okPipe],
      ].map(s => `<div class="step"><strong>${s[0]}</strong><div>${s[1]}</div><div>${yesNo(s[2])}</div><div class="small">${s[0] === 'Embed / Publish' ? freshness : ''}</div></div>`).join('');

      $('expectations').innerHTML = '<tr><th>Name</th><th>Severity</th><th>Status</th><th>Detail</th></tr>' +
        (data.log.expectations || []).map(e => `<tr><td>${e.name}</td><td>${e.severity}</td><td>${e.state === 'OK' ? '<span class="ok">OK</span>' : '<span class="fail">FAIL</span>'}</td><td>${e.detail}</td></tr>`).join('');

      $('rawDist').innerHTML = '<tr><th>doc_id</th><th>records</th></tr>' +
        (data.raw.top_doc_ids || []).map(([k,v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');

      const ex = data.examples || {};
      const scenarioData = [
        ['Refund stale', 'Raw có 14 ngày; after fix phải còn 7 ngày và forbidden=0.', ex.refund_good?.top1_preview || ''],
        ['HR versioning', 'Raw có HR 2025 10 ngày; cleaned giữ HR 2026 12 ngày.', ex.hr_good?.top1_preview || ''],
        ['Access control', 'access_control_sop từng thiếu allowlist; grading cần Level 4.', rowText(ex.raw_access_control, ['doc_id','chunk_text','effective_date'])],
        ['SLA P1', 'Escalation P1 phải trả lời 10 phút trong top-k.', ex.sla_good?.top1_preview || ''],
      ];
      $('scenarios').innerHTML = scenarioData.map(([title, desc, detail], idx) => `
        <div class="scenario" onclick="$('output').textContent=${JSON.stringify('Example: ' + title + '\n\n' + detail)}">
          <b>${esc(title)}</b>
          <div class="small">${esc(desc)}</div>
          <div class="pillRow"><span class="pill">${idx === 0 ? 'before/after' : idx === 1 ? 'version' : idx === 2 ? 'allowlist' : 'retrieval'}</span></div>
        </div>`).join('');

      $('examples').innerHTML = [
        ['Raw refund stale', rowText(ex.raw_refund_stale, ['row_id','doc_id','chunk_text','effective_date'])],
        ['Raw HR stale', rowText(ex.raw_hr_stale, ['row_id','doc_id','chunk_text','effective_date'])],
        ['Raw access source', rowText(ex.raw_access_control, ['row_id','doc_id','chunk_text','effective_date'])],
        ['Cleaned sample', (ex.cleaned_rows || []).slice(0,3).map(r => rowText(r, ['doc_id','chunk_text','effective_date'])).join('\n\n---\n\n')],
        ['Quarantine sample', (ex.quarantine_rows || []).slice(0,3).map(r => rowText(r, ['doc_id','chunk_text','effective_date','reason'])).join('\n\n---\n\n')],
        ['Latest manifest', rowText(data.manifest || {}, ['run_id','raw_records','cleaned_records','quarantine_records','latest_exported_at','chroma_collection'])],
      ].map(([title, body]) => `<div class="example"><h3>${esc(title)}</h3><div class="mono">${esc(body)}</div></div>`).join('');

      const bad = data.after_inject_bad.summary || {};
      const good = data.after_fix_sprint3.summary || {};
      $('comparison').innerHTML = `
        <table>
          <tr><th>Artifact</th><th>Rows</th><th>contains pass</th><th>forbidden hits</th></tr>
          <tr><td>${data.after_inject_bad.path || 'after_inject_bad.csv'}</td><td>${bad.total ?? '-'}</td><td>${bad.contains_pass ?? '-'}</td><td>${bad.forbidden_hits ?? '-'}</td></tr>
          <tr><td>${data.after_fix_sprint3.path || 'after_fix_sprint3.csv'}</td><td>${good.total ?? '-'}</td><td>${good.contains_pass ?? '-'}</td><td>${good.forbidden_hits ?? '-'}</td></tr>
        </table>
        <div class="small">Sprint 3 evidence: forbidden hit phải giảm sau restore clean.</div>`;
      $('spotlight').innerHTML = `
        <div class="compareCards">
          <div class="example badCard"><h3>Inject bad: q_refund_window</h3><div class="mono">${esc(rowText(ex.refund_bad, ['question_id','top1_doc_id','top1_preview','contains_expected','hits_forbidden']))}</div></div>
          <div class="example goodCard"><h3>After fix: q_refund_window</h3><div class="mono">${esc(rowText(ex.refund_good, ['question_id','top1_doc_id','top1_preview','contains_expected','hits_forbidden']))}</div></div>
        </div>`;

      $('gradingTable').innerHTML = '<tr><th>ID</th><th>Top-1</th><th>Expected</th><th>Forbidden</th><th>Top1 match</th></tr>' +
        (data.grading.rows || []).map(r => `<tr><td>${r.id}</td><td>${r.top1_doc_id}</td><td>${yesNo(r.contains_expected)}</td><td>${r.hits_forbidden ? '<span class="fail">HIT</span>' : '<span class="ok">NO</span>'}</td><td>${yesNo(r.top1_doc_matches === true || r.top1_doc_matches === null)}</td></tr>`).join('');
    }

    loadStatus();
    setTimeout(() => runQuery(), 300);
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/status":
            self._send(200, json.dumps(_status(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/upload-run":
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                },
            )
            field = form["file"] if "file" in form else None
            if field is None or not getattr(field, "file", None):
                result = {"ok": False, "error": "Missing file field."}
            else:
                result = _run_uploaded_csv(getattr(field, "filename", "uploaded.csv"), field.file.read())
            self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path == "/api/query":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            result = _query_question(str(payload.get("question", "")), int(payload.get("top_k", 5)))
            self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path != "/api/run":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        result = _run_action(str(payload.get("action", "")))
        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[dashboard] {self.address_string()} {fmt % args}")


def main() -> int:
    port = int(os.environ.get("DAY10_DASHBOARD_PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Dashboard: http://127.0.0.1:{port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
