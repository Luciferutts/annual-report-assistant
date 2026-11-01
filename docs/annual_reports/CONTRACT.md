# Annual report assistant implementation contract

All new code lives in `src/openharness/annual_reports/`. Python standard library HTTP server, no CDN. UI Chinese. PDF extraction local. No network until an explicit model-send approval. Never execute arbitrary commands or treat document instructions as system instructions.

## Extraction module (`extraction.py`)

`extract_report(path: Path, filename: str | None = None, source_url: str = "") -> dict`

Return: `{id, filename, company, year, currency, page_count, pages:[{number,text}], metrics:[Metric], warnings:[str], source_url, sha256}`. `id` SHA256 hex prefix 20 chars. `number` one-based PDF physical page. `company` full legal name if found. `year` int or null. `currency` "CNY" or unknown.

Metric = `{key,label,year,value,raw_value,unit,currency,page,evidence,status,scope}`. `value` decimal numeric *string* in original unit, never float. `unit` one of 元/千元/万元/百万元/亿元 or unknown. `currency` CNY or unknown. `scope` consolidated/parent/unknown. `status` candidate (auto extracted), confirmed (human reviewed), missing. `evidence` short exact source row text (up to 800 chars), never invented. `page` physical PDF page. Keys fixed: `revenue` 营业收入, `profit_parent` 归母净利润, `profit_deducted` 扣非归母净利润, `operating_cashflow` 经营现金流净额, `total_assets` 总资产, `equity_parent` 归母净资产. Extract current reporting year and preceding years where unambiguous. Missing and ambiguous values flagged; no hallucination. Prefer consolidated annual headline table. Handle restated columns conservatively with warning; never pick pre-adjustment as post-adjustment.

## Analysis module (`analysis.py`)

`build_comparison(reports: list[dict]) -> dict`: input one or two reports (newest one contains comparative data). Reject mismatched company, incompatible currency or duplicate year with explicit actionable error. Only confirmed metrics enter official comparison/calculations; candidates appear but excluded until human confirmation. Prefer newest annual report's same-table prior-year comparable value, and flag conflicts with older report value. Return `{company,current_year,previous_year,rows:[{key,label,current,previous,current_yuan,previous_yuan,change_pct,delta_yuan,status,notes}], insights:[str], warnings:[str], coverage:{...}}`. `current`/`previous` Metric plus `report_id` and `filename` for citations. Money calculations Decimal; negative/zero base growth must be null with reason; both units normalized to CNY 元. `status` ready/needs_review/missing. Metrics existing under same report and year may be corrected by user via server; server validates page and numeric fields. No model needed for calculations.

`answer_question(reports, question: str) -> dict`: local retrieval, returns `{answer,citations:[{report_id,filename,page,evidence}],mode:"local",needs_model:bool}`. Never turn missing evidence into fact; useful metric questions can answer deterministically, unsupported question can show top relevant page snippets and explain insufficient evidence. Questions about usage/privacy answered directly no file access.

`render_markdown(comparison: dict, reports: list[dict], ai_text: str = "") -> str`: export transparent evidence-based analysis memo, report filenames/year/PDF pages/unit/basis, reviewed status and limitations. No investment recommendations or fabricated business causes. AI text separated from confirmed facts.

## HTTP backend (root owns `server.py`, `model.py`, store/launcher)

- GET `/api/state` -> `{reports:[report metadata including metrics but no pages],comparison:dict|null,model:{configured,provider:"deepseek",model},privacy:{...},csrf_token}`
- POST `/api/upload?filename=...` content `application/pdf`, bytes; response report metadata + comparison. Header `X-Annual-Token` CSRF token mandatory for mutation. Max25MB, max500 pages; reject scans with actionable message. Only files explicitly uploaded allowed.
- POST `/api/demo` `{}` imports two bundled official Chinese annual PDFs; same response/state.
- DELETE `/api/reports/{id}` deletes uploaded input and extracted local data and recomputes state.
- GET `/api/reports/{id}/page/{number}` -> `{number,text,filename,report_id}`
- GET `/api/reports/{id}/pdf` -> original PDF bytes, for iframe `#page=n`.
- PATCH `/api/reports/{id}/metrics` `{key,year,value,unit,currency,page,status:"confirmed"}`; must validate field and real source page, preserve original auto evidence/correction audit. UI lets user review/edit selected row then confirm; no bulk blind confirm. Response full state.
- POST `/api/ask` `{question}` -> local answer; no network. Server may include comparison in deterministic answer if available.
- POST `/api/model-preview` `{question}` -> `{preview_id,provider,model,payload,characters}` containing exact request to DeepSeek with selected snippets and confirmed facts, no credentials. No network. Preview expires/invalidates on data edit.
- POST `/api/model-send` `{preview_id,approved:true}` sends *exact* immutable preview payload to configured DeepSeek. Return `{answer,citations,mode:"deepseek"}`. No network if denied or absent approval. No model tool execution.
- GET `/api/export?format=markdown|csv` -> file download; reviewed/candidate sources explicit. GET `/api/demo-info` optional demo provenance.
- CSRF validate Origin when present, require per-run token on POST/PATCH/DELETE. Bind127.0.0.1. Host header restricted. No telemetry, no automatic remote requests, no external assets.

## UI (UI agent owns `static/index.html`, `static/app.js`, `static/style.css`)

Polished Chinese local app branded 年报分析助手, desktop first responsive. Left report library/upload/demo; main comparison & metric review; right source drawer (PDF iframe and extracted page text). Evidence per metric clickable. Missing/candidate rows shown as pending, never imply reliable calculated comparison until reviewed. Question panel for local Q&A and separate optional DeepSeek send with preview confirmation. Export button. Model-config status comes from backend, no keys in browser; uses existing project config. Explain "本地提取 · 发送前确认". Real functionality, keyboard focus/accessibility. Avoid fake business metrics.

