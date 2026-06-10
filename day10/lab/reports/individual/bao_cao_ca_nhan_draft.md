# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** ___________  
**Vai trò:** Cleaning / Quality Owner  
**Ngày nộp:** 2026-06-10  

---

## 1. Tôi phụ trách phần nào?

- Tôi phụ trách phần **raw analysis, cleaning rules và expectation suite**.
- Các file/module chính:
  - `data/raw/policy_export_dirty.csv`
  - `transform/cleaning_rules.py`
  - `quality/expectations.py`
  - `docs/quality_report.md`
- Logic end-to-end tôi xử lý:
  - raw CSV
  - ingest
  - clean / normalize
  - quarantine dữ liệu lỗi
  - validate bằng expectations
  - embed vào Chroma
  - eval retrieval / grading
- Tình huống ban đầu:
  - Pipeline chạy nhưng bị halt.
  - `run_id=2026-06-10T04-58Z`
  - `raw_records=247`
  - `cleaned_records=40`
  - `quarantine_records=207`
  - Lỗi chính: `expectation[hr_leave_no_stale_10d_annual] FAIL (halt) :: violations=2`
- Tôi cũng phát hiện pipeline baseline thiếu source hợp lệ `access_control_sop`, trong khi grading câu `gq_d10_10` cần source này.

---

## 2. Một quyết định kỹ thuật

- Quyết định chính: lỗi stale policy phải là **halt**, không chỉ `warn`.
- Lý do:
  - Nếu dữ liệu stale vẫn được embed, agent có thể trả lời sai dù model không lỗi.
  - Ví dụ: HR 2025 ghi `10 ngày phép năm`, nhưng HR 2026 đúng là `12 ngày phép năm`.
  - Refund policy cũ có `14 ngày làm việc`, nhưng policy hiện hành là `7 ngày làm việc`.
- Logic xử lý:
  - Dữ liệu nghi ngờ đi vào quarantine.
  - Chỉ cleaned data pass expectation mới được embed.
  - Vector store chỉ nhận snapshot sạch.
- Kỹ thuật đã dùng:
  - allowlist source bằng `ALLOWED_DOC_IDS`
  - content marker detection cho HR stale
  - expectation severity `halt/warn`
  - upsert theo `chunk_id`
  - prune vector id cũ để tránh stale chunk còn trong Chroma

---

## 3. Một lỗi hoặc anomaly đã xử lý

- Anomaly 1: **HR version conflict**
  - Raw có bản HR 2025: `10 ngày phép năm`.
  - Grading yêu cầu HR 2026: `12 ngày phép năm`.
  - Pipeline cũ chỉ check `effective_date < 2026-01-01`, nên còn 2 dòng HR stale lọt qua.
  - Cách xử lý:
    - thêm rule quarantine nếu `chunk_text` chứa `10 ngày phép năm` và `bản HR 2025`
    - giữ expectation `hr_leave_no_stale_10d_annual` ở mức `halt`

- Anomaly 2: **Source hợp lệ bị quarantine nhầm**
  - Raw có `access_control_sop: 8` records.
  - Baseline allowlist thiếu `access_control_sop`.
  - Grading `gq_d10_10` cần source này để trả lời Level 4 Admin Access.
  - Cách xử lý:
    - thêm `access_control_sop` vào `ALLOWED_DOC_IDS`
    - thêm expectation `required_grading_sources_present`

- Anomaly 3: **Noise và retrieval lệch**
  - Raw có marker `Nội dung không rõ ràng:` và `!!!`.
  - Query SLA P1 có thể lệch nếu chunk thiếu keyword `auto escalate`.
  - Cách xử lý:
    - normalize marker nhiễu
    - quarantine dòng rỗng sau normalize
    - enrich SLA P1 để top-k có context `10 phút`

---

## 4. Bằng chứng trước / sau

- Trước fix:

```text
run_id=2026-06-10T04-58Z
raw_records=247
cleaned_records=40
quarantine_records=207
expectation[hr_leave_no_stale_10d_annual] FAIL (halt) :: violations=2
PIPELINE_HALT: expectation suite failed (halt).
```

- Sau fix:

```text
run_id=after-fix-sprint3
raw_records=247
cleaned_records=35
quarantine_records=212
expectation[refund_no_stale_14d_window] OK (halt) :: violations=0
expectation[hr_leave_no_stale_10d_annual] OK (halt) :: violations=0
PIPELINE_OK
```

- Inject corruption:

```bash
python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate
```

- Kết quả inject:
  - `refund_no_stale_14d_window` fail với `violations=1`
  - `q_refund_window` có `hits_forbidden=yes`
  - top-1 preview chứa `14 ngày làm việc`

- Kết quả sau restore:
  - `after_fix_sprint3.csv` có `hits_forbidden=0`
  - `grading_run.jsonl` đạt 10/10 câu
  - tất cả grading đều:
    - `contains_expected=true`
    - `hits_forbidden=false`
    - `top1_doc_matches=true`

---

## 5. Cải tiến tiếp theo

- Nếu có thêm 2 giờ, tôi sẽ:
  - chuyển allowlist source sang `contracts/data_contract.yaml`
  - chuyển HR cutoff date sang contract
  - chuyển danh sách required grading sources sang contract
  - để `quality/expectations.py` đọc contract thay vì hard-code
- Lợi ích:
  - giảm rủi ro code và docs bị lệch
  - dễ thêm source mới
  - expectation suite rõ ràng hơn cho production
