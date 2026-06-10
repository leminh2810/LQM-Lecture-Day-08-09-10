# Quality report — Lab Day 10

**run_id bad:** `inject-bad`  
**run_id after fix:** `after-fix-sprint3`  
**Ngày:** 2026-06-10

---

## 1. Tóm tắt số liệu

| Chỉ số | Trước / inject bad | Sau fix | Ghi chú |
|--------|---------------------|---------|---------|
| raw_records | 247 | 247 | Cùng raw export `data/raw/policy_export_dirty.csv` |
| cleaned_records | 35 | 35 | Cùng số dòng, khác nội dung refund vì inject tắt rule fix |
| quarantine_records | 212 | 212 | Quarantine ổn định |
| Expectation halt? | Có: `refund_no_stale_14d_window` fail `violations=1` | Không | Inject dùng `--skip-validate` để cố ý embed dữ liệu xấu |
| embed_upsert | 35 | 35 | Chroma collection `day10_kb` |

Log chính:

```text
run_id=inject-bad
expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1
WARN: expectation failed but --skip-validate → tiếp tục embed (chỉ dùng cho demo Sprint 3).
PIPELINE_OK
```

```text
run_id=after-fix-sprint3
expectation[refund_no_stale_14d_window] OK (halt) :: violations=0
PIPELINE_OK
```

---

## 2. Before / after retrieval

Artifacts:

- Bad eval: `artifacts/eval/after_inject_bad.csv`
- Good eval: `artifacts/eval/after_fix_sprint3.csv`
- Grading final: `artifacts/eval/grading_run.jsonl`

Summary:

| File | Questions | contains_expected pass | hits_forbidden |
|------|-----------|------------------------|----------------|
| `after_inject_bad.csv` | 21 | 21/21 | 1 |
| `after_fix_sprint3.csv` | 21 | 21/21 | 0 |
| `grading_run.jsonl` | 10 | 10/10 | 0 |

**Câu hỏi then chốt: refund window (`q_refund_window`)**

Trước inject:

```csv
q_refund_window,...,top1_doc_id=policy_refund_v4,top1_preview="Yêu cầu hoàn tiền được chấp nhận trong vòng 14 ngày làm việc kể từ xác nhận đơn.",contains_expected=yes,hits_forbidden=yes,top1_doc_expected=yes
```

Sau fix:

```csv
q_refund_window,...,top1_doc_id=policy_refund_v4,top1_preview="Yêu cầu được gửi trong vòng 7 ngày làm việc làm việc kể từ thời điểm xác nhận đơn hàng.",contains_expected=yes,hits_forbidden=no,top1_doc_expected=yes
```

**Versioning HR (`q_hr_annual_leave_under3`)**

Trước inject và sau fix đều giữ đúng HR 2026 vì rule HR stale content marker vẫn bật:

```csv
q_hr_annual_leave_under3,...,top1_doc_id=hr_leave_policy,top1_preview="Nhân viên dưới 3 năm kinh nghiệm được 12 ngày phép năm theo chính sách 2026.",contains_expected=yes,hits_forbidden=no,top1_doc_expected=yes
```

---

## 3. Freshness & monitor

Freshness check hiện `FAIL` ở cả bad và good run:

```text
freshness_check=FAIL {"latest_exported_at": "2026-04-10T00:00:00", "age_hours": 1470.988, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
```

Giải thích: đây là CSV mẫu có `exported_at` cũ so với ngày chạy pipeline 2026-06-10. Kết quả `FAIL` là hợp lý cho freshness monitor và cần ghi trong runbook: pipeline quality pass không đồng nghĩa dữ liệu còn fresh theo SLA 24 giờ.

---

## 4. Corruption inject

Lệnh inject:

```bash
python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate
python eval_retrieval.py --out artifacts/eval/after_inject_bad.csv
```

Kiểu corruption: tắt rule sửa stale refund window `14 ngày làm việc` về `7 ngày làm việc`, sau đó bỏ qua validation để cố ý publish dữ liệu xấu vào vector store. Expectation phát hiện lỗi bằng `refund_no_stale_14d_window`, nhưng `--skip-validate` cho phép đo tác động retrieval.

Lệnh restore:

```bash
python etl_pipeline.py run --run-id after-fix-sprint3
python eval_retrieval.py --out artifacts/eval/after_fix_sprint3.csv
python grading_run.py --out artifacts/eval/grading_run.jsonl
```

Kết quả: trước fix có `hits_forbidden=yes` cho `q_refund_window`; sau fix không còn forbidden hit và grading chính thức 10/10 pass.

---

## 5. Hạn chế & việc chưa làm

- Self-eval `q_p1_update_frequency` vẫn có `top1_doc_expected=no`, dù `contains_expected=yes` và `hits_forbidden=no`; nếu cần tối ưu thêm thì nên cải thiện chunking/reranking cho các câu P1 operational.
- Freshness monitor đang fail do dữ liệu mẫu cũ; cần runbook giải thích rõ đây là cảnh báo vận hành, không phải lỗi cleaning.
