# Data contract — Lab Day 10

Contract này mô tả raw export `data/raw/policy_export_dirty.csv`, cleaned CSV và các policy quarantine/publish cho collection `day10_kb`.

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Số dòng raw | Failure mode chính | Metric / alert |
|-------|-------------------|-------------|--------------------|----------------|
| `policy_refund_v4` | CSV export từ policy system | 33 | stale refund window `14 ngày làm việc`; duplicate; noise marker | `refund_no_stale_14d_window`, `hits_forbidden` trên `q_refund_window` |
| `sla_p1_2026` | CSV export từ SLA catalog | 31 | P1/P2 context lẫn nhau; retrieval top-k thiếu chunk escalation/update | `required_grading_sources_present`, eval `q_p1_escalation` |
| `it_helpdesk_faq` | CSV export từ FAQ system | 26 | duplicate/noise; metadata cũ | eval `q_it_lockout`, `q_vpn_device_limit` |
| `hr_leave_policy` | CSV export từ HR policy | 40 | HR 2025 `10 ngày phép năm` lẫn HR 2026 `12 ngày phép năm` | `hr_leave_no_stale_10d_annual`, `hits_forbidden` trên HR |
| `access_control_sop` | CSV export từ SOP system | 8 | baseline allowlist thiếu source hợp lệ | `required_grading_sources_present`, grading `gq_d10_10` |
| `invalid_doc_*`, `legacy_catalog_*`, `security_policy`, `data_privacy_guideline` | CSV export nhiễu / ngoài phạm vi | 109 | source chưa đăng ký hoặc không phục vụ grading | quarantine reason `unknown_doc_id` |

Run tham chiếu:

```text
run_id=after-fix-sprint3
raw_records=247
cleaned_records=35
quarantine_records=212
```

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| `chunk_id` | string | Có | ID ổn định để upsert/prune trong Chroma; format `doc_id_seq_hash` |
| `doc_id` | string | Có | Phải thuộc allowlist publish |
| `chunk_text` | string | Có | Nội dung đã normalize, không rỗng, không còn marker export nhiễu |
| `effective_date` | date string | Có | ISO `YYYY-MM-DD` sau parser |
| `exported_at` | datetime string | Có | Timestamp export; dùng cho manifest/freshness |

Allowlist publish:

```text
policy_refund_v4
sla_p1_2026
it_helpdesk_faq
hr_leave_policy
access_control_sop
```

---

## 3. Quy tắc quarantine vs drop

Pipeline không xóa im lặng record lỗi. Record bị loại khỏi cleaned được ghi vào `artifacts/quarantine/quarantine_<run_id>.csv` kèm `reason`.

Các reason chính:

| Reason | Ý nghĩa |
|--------|---------|
| `unknown_doc_id` | `doc_id` không thuộc allowlist publish |
| `missing_effective_date` | thiếu ngày hiệu lực |
| `invalid_effective_date_format` | không parse được ngày |
| `stale_hr_policy_effective_date` | HR policy trước cutoff 2026 |
| `stale_hr_policy_content_marker` | HR 2025 lọt với ngày mới nhưng content vẫn stale |
| `missing_chunk_text` | text rỗng hoặc chỉ còn marker sau normalize |
| `duplicate_chunk_text` | duplicate nội dung |
| `out_of_scope_sla_p2_for_p1_eval` | chunk P2 làm nhiễu eval P1 trong lab snapshot |

Policy: quarantine không được embed. Nếu SME xác nhận record hợp lệ, cần sửa source/cutoff/allowlist rồi rerun pipeline; không sửa trực tiếp trong cleaned CSV.

---

## 4. Phiên bản & canonical

Canonical documents:

| doc_id | Source of truth | Version rule |
|--------|-----------------|--------------|
| `policy_refund_v4` | `data/docs/policy_refund_v4.txt` | Current window là `7 ngày làm việc`; `14 ngày làm việc` là stale |
| `sla_p1_2026` | `data/docs/sla_p1_2026.txt` | P1 response 15 phút, resolution 4 giờ, escalation 10 phút |
| `it_helpdesk_faq` | `data/docs/it_helpdesk_faq.txt` | FAQ IT nội bộ |
| `hr_leave_policy` | `data/docs/hr_leave_policy.txt` | HR 2026: dưới 3 năm = 12 ngày phép năm |
| `access_control_sop` | `data/docs/access_control_sop.txt` | Level 4 Admin Access cần IT Manager và CISO |

Cutoff hiện tại cho HR:

```text
hr_leave_min_effective_date=2026-01-01
```

Ghi chú production: cutoff và required sources nên chuyển sang `contracts/data_contract.yaml` để tránh hard-code trong code.

---

## 5. Quality expectations

| Expectation | Severity | Mục đích |
|-------------|----------|----------|
| `min_one_row` | halt | Không publish collection rỗng |
| `no_empty_doc_id` | halt | Không có source rỗng |
| `refund_no_stale_14d_window` | halt | Chặn refund stale 14 ngày |
| `effective_date_iso_yyyy_mm_dd` | halt | Đảm bảo date canonical |
| `hr_leave_no_stale_10d_annual` | halt | Chặn HR 2025 |
| `cleaned_doc_ids_in_allowlist` | halt | Không publish source lạ |
| `required_grading_sources_present` | halt | Không quarantine nhầm source hợp lệ |
| `chunk_min_length_8` | warn | Cảnh báo chunk quá ngắn |
| `no_export_noise_markers` | warn | Cảnh báo marker nhiễu lọt vào cleaned |
