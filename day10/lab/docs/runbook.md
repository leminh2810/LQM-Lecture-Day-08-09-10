# Runbook — Lab Day 10

Runbook này dùng cho incident khi agent/RAG trả lời sai do dữ liệu bẩn, stale hoặc vector index chưa được publish đúng.

---

## Symptom

Các triệu chứng thường gặp:

- Agent trả lời chính sách refund là `14 ngày` thay vì `7 ngày làm việc`.
- Agent trả lời HR annual leave là `10 ngày phép năm` thay vì `12 ngày phép năm`.
- Agent không trả lời được Level 4 Admin Access cần IT Manager/CISO vì source `access_control_sop` bị quarantine nhầm.
- Eval có `hits_forbidden=yes` hoặc `contains_expected=no`.
- Freshness báo `FAIL` dù pipeline quality pass.

Incident Sprint 3 đã tái hiện:

```text
run_id=inject-bad
expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1
WARN: expectation failed but --skip-validate → tiếp tục embed
```

---

## Detection

Luôn kiểm theo thứ tự:

1. Freshness/version.
2. Volume/errors.
3. Schema/contract.
4. Lineage/run_id.
5. Sau cùng mới debug model/prompt.

Lệnh kiểm tra nhanh:

```bash
python etl_pipeline.py run
python eval_retrieval.py --out artifacts/eval/eval_after_fix.csv
python grading_run.py --out artifacts/eval/grading_run.jsonl
```

Artifact cần mở:

- `artifacts/logs/run_<run_id>.log`
- `artifacts/manifests/manifest_<run_id>.json`
- `artifacts/quarantine/quarantine_<run_id>.csv`
- `artifacts/eval/eval_after_fix.csv`
- `artifacts/eval/grading_run.jsonl`

Ngưỡng pass cho grading:

```text
contains_expected=true
hits_forbidden=false
top1_doc_matches=true
```

---

## Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | Mở log run mới nhất | Có `run_id`, `raw_records`, `cleaned_records`, `quarantine_records` |
| 2 | Kiểm expectation fail | Halt nếu stale refund, HR 2025, missing required source |
| 3 | Mở quarantine CSV | Record lỗi có `reason`, không bị drop im lặng |
| 4 | Mở manifest | `cleaned_records` và `quarantine_records` khớp log |
| 5 | Chạy eval retrieval | `hits_forbidden=no` trên 21 câu self-eval |
| 6 | Chạy grading | 10 dòng JSONL, `gq_d10_01` đến `gq_d10_10` đều pass |

Ví dụ run sạch:

```text
run_id=after-fix-sprint3
raw_records=247
cleaned_records=35
quarantine_records=212
expectation[refund_no_stale_14d_window] OK (halt) :: violations=0
expectation[hr_leave_no_stale_10d_annual] OK (halt) :: violations=0
expectation[required_grading_sources_present] OK (halt) :: missing_doc_ids=[]
PIPELINE_OK
```

---

## Mitigation

Nếu expectation halt:

1. Không dùng `--skip-validate` cho production/demo cuối.
2. Sửa rule trong `transform/cleaning_rules.py` hoặc expectation trong `quality/expectations.py`.
3. Rerun pipeline chuẩn:

```bash
python etl_pipeline.py run
```

Nếu vector index đã bị inject dữ liệu xấu:

```bash
python etl_pipeline.py run --run-id after-fix-sprint3
python eval_retrieval.py --out artifacts/eval/after_fix_sprint3.csv
python grading_run.py --out artifacts/eval/grading_run.jsonl
```

Pipeline dùng upsert `chunk_id` và prune id cũ, nên rerun sạch sẽ thay snapshot trong Chroma collection `day10_kb`.

Nếu freshness fail nhưng quality pass:

- Không sửa prompt/model.
- Kiểm `latest_exported_at` trong manifest.
- Nếu đây là data mẫu lab cũ, ghi nhận trong report/runbook.
- Nếu là production, rerun ingest từ source mới hoặc bật cảnh báo “data đang cập nhật”.

---

## Freshness PASS / WARN / FAIL

Freshness được kiểm bằng:

```bash
python etl_pipeline.py freshness --manifest artifacts/manifests/manifest_after-fix-sprint3.json
```

Ý nghĩa:

| Status | Ý nghĩa | Hành động |
|--------|---------|-----------|
| PASS | `latest_exported_at` còn trong SLA | Có thể publish nếu expectations pass |
| WARN | Manifest thiếu timestamp hoặc không đủ dữ liệu để tính chắc chắn | Kiểm manifest/log, không bỏ qua nếu demo production |
| FAIL | Dữ liệu quá cũ so với `FRESHNESS_SLA_HOURS` | Rerun ingest hoặc ghi incident note |

Run hiện tại:

```text
freshness_check=FAIL
latest_exported_at=2026-04-10T00:00:00
sla_hours=24
reason=freshness_sla_exceeded
```

Giải thích: ngày chạy là 2026-06-10, trong khi CSV mẫu có export mới nhất 2026-04-10. Đây là expected FAIL cho lab snapshot.

---

## Prevention

Các guard đã thêm:

- `refund_no_stale_14d_window` chặn refund stale.
- `hr_leave_no_stale_10d_annual` chặn HR 2025.
- `cleaned_doc_ids_in_allowlist` chặn source lạ lọt vào publish.
- `required_grading_sources_present` chặn quarantine nhầm source hợp lệ như `access_control_sop`.
- `no_export_noise_markers` cảnh báo marker nhiễu còn trong cleaned.

Việc nên làm tiếp:

- Chuyển allowlist, HR cutoff và required sources sang `contracts/data_contract.yaml`.
- Thêm alert riêng cho freshness ở boundary ingest và publish.
- Thêm dashboard hoặc CI check chạy `instructor_quick_check.py` trước khi nộp.
