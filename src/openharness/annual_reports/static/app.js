"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const metricLabels = {revenue:"营业收入",profit_parent:"归母净利润",profit_deducted:"扣非归母净利润",operating_cashflow:"经营现金流净额",total_assets:"总资产",equity_parent:"归母净资产"};
const app = {state:{reports:[],comparison:null,model:{}},csrf:"",review:null,preview:null,previewQuestion:"",sourceTab:"pdf",sourceSeq:0,toastTimer:null,busy:false,asking:false,previewing:false,sending:false,saving:false};

function reportById(id) { return app.state.reports.find(r => r.id === id); }
function showToast(message, error = false) {
  const box = $("#toast"); box.textContent = message; box.classList.toggle("error",error); box.hidden = false;
  clearTimeout(app.toastTimer); app.toastTimer = setTimeout(() => {box.hidden = true;},error ? 8500 : 4500);
}
function setBusy(active, title = "正在处理", detail = "请稍候") {
  app.busy = active; $("#busy-overlay").hidden = !active; $("#busy-title").textContent = title; $("#busy-detail").textContent = detail;
}
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.method && !["GET","HEAD"].includes(options.method.toUpperCase())) headers.set("X-Annual-Token",app.csrf);
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(),180000);
  try {
    const response = await fetch(path,{...options,headers,signal:controller.signal,credentials:"same-origin",cache:"no-store"});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : (data.message || `请求未完成（${response.status}），请重试。`));
    return data;
  } catch(error) {
    if (error.name === "AbortError") throw new Error("处理时间较长，请稍后刷新查看，或尝试更小的文字版 PDF。");
    if (error instanceof TypeError) throw new Error("暂时无法连接本地助手，请确认启动窗口仍在运行。");
    throw error;
  } finally { clearTimeout(timeout); }
}
function jsonOptions(method, body = {}) { return {method,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}; }
async function refresh() {
  const state = await api("/api/state"); app.state = state; app.csrf = state.csrf_token || app.csrf; app.preview = null; render(); return state;
}
function numberText(value) {
  if (value === null || value === undefined || value === "") return "—";
  const text = String(value).trim().replace(/[,，]/g, "");
  const match = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(text);
  if (!match || (!match[2] && !match[3])) return String(value);
  const integer = (match[2] || "0").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${match[1]}${integer}${match[3] === undefined ? "" : "." + match[3]}`;
}
function officialSource(url) {
  try {
    const parsed = new URL(String(url || ""));
    if (parsed.protocol !== "https:") return "";
    return `<a class="report-official" href="${escapeHTML(parsed.href)}" target="_blank" rel="noopener noreferrer">官方披露 ↗</a>`;
  } catch (_) { return ""; }
}

function percentText(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value); if (!Number.isFinite(number)) return "—";
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}
function metricCell(metric, row, period) {
  const year = period === "current" ? app.state.comparison.current_year : app.state.comparison.previous_year;
  const id = metric?.report_id || app.state.reports.slice().sort((a,b)=>(b.year||0)-(a.year||0))[0]?.id;
  if (!metric || metric.value === null || metric.value === undefined || metric.status === "missing") return `<button class="metric-value missing" type="button" data-review="${escapeHTML(row.key)}" data-report="${escapeHTML(id)}" data-year="${escapeHTML(year)}">未提取 · 手动补录 ↗</button><span class="metric-source">需要原文依据</span>`;
  const confirmed = metric.status === "confirmed";
  return `<button class="metric-value" type="button" title="查看原文并核对数值" data-review="${escapeHTML(row.key)}" data-report="${escapeHTML(id)}" data-year="${escapeHTML(year)}">${escapeHTML(numberText(metric.value))}<small>${escapeHTML(metric.unit || "单位待定")}</small></button><span class="metric-source ${confirmed?"confirmed":""}">${confirmed?"✓ 已核对":"待核对"}${metric.page?` · PDF 第 ${escapeHTML(metric.page)} 页`:" · 页码待定"}</span>`;
}
function render() {
  const {reports = [],comparison,comparison_error,model = {}} = app.state;
  $("#report-count").textContent = `${reports.length} / 2`;
  $("#report-list").innerHTML = reports.length ? reports.map(report => `<article class="report-card"><button type="button" class="report-open" data-open-report="${escapeHTML(report.id)}" title="查看年报原文"><h3>${escapeHTML(report.filename)}</h3><div class="report-meta"><span>${escapeHTML(report.year || "期间待识别")}</span><span>${escapeHTML(report.page_count || 0)} 页</span><span>${(report.metrics || []).filter(m=>m.status==="confirmed").length} 项已核对</span></div></button>${officialSource(report.source_url)}<button type="button" class="delete-report" data-delete-report="${escapeHTML(report.id)}" title="删除资料" aria-label="删除 ${escapeHTML(report.filename)}">×</button></article>`).join("") : '<p class="library-empty">尚未导入资料</p>';
  const modelStatus = $("#model-status"); modelStatus.textContent = model.configured ? "DeepSeek 已配置" : "DeepSeek 未配置"; modelStatus.classList.toggle("connected",Boolean(model.configured));
  $("#model-ask-button").title = model.configured ? "先预览请求，确认后才发送" : "请先在项目模型配置窗口中连接 DeepSeek；本地分析可正常使用";
  $("#empty-state").hidden = reports.length > 0; $("#workspace").hidden = reports.length === 0;
  $("#export-md").disabled = !comparison; $("#export-csv").disabled = !comparison;
  $("#file-input").disabled = reports.length >= 2;
  $("#upload-zone").classList.toggle("full",reports.length >= 2);
  $("#upload-zone").title = reports.length >= 2 ? "已导入两份年报，如需替换请先删除一份。" : "导入同一家公司的文字版 PDF 年报";
  const ready = comparison?.coverage?.ready ?? comparison?.rows?.filter(r=>r.status==="ready").length ?? 0;
  $$(".workflow li").forEach((li,i)=>{const step=reports.length===0?0:ready===6?2:1;li.classList.toggle("current",i===step);li.classList.toggle("done",i<step);});
  if (!reports.length) return;
  $("#company-name").textContent = comparison?.company || reports[0]?.company || "公司名称待识别";
  const currentYear = comparison?.current_year || Math.max(...reports.map(r=>r.year || 0)) || "待识别";
  const previousYear = comparison?.previous_year || (typeof currentYear==="number"?currentYear-1:"待识别");
  $("#company-period").innerHTML = `<span class="year-pill">${escapeHTML(currentYear)} 年</span><span>对比</span><span class="year-pill">${escapeHTML(previousYear)} 年</span><span>· ${reports.length} 份来源年报</span>`;
  const confirmedValues = comparison?.coverage?.confirmed_values ?? reports.reduce((n,r)=>n+(r.metrics||[]).filter(m=>m.status==="confirmed").length,0);
  const totalValues = comparison?.coverage?.total_values || 12;
  $("#review-progress").innerHTML = `<strong>${escapeHTML(confirmedValues)} <span class="progress-total">/ ${escapeHTML(totalValues)}</span></strong><span>对比数据已核对</span><progress class="progress-track" value="${Math.min(totalValues,Math.max(0,confirmedValues))}" max="${totalValues}" aria-label="数据复核进度"></progress>`;
  const warnings = [...(comparison?.warnings || []),...reports.flatMap(r=>(r.warnings || []).map(w=>`【${r.year ? r.year + " 年 · " : ""}${r.filename || "来源年报"}】${typeof w === "string" ? w : JSON.stringify(w)}`))];
  const uniqueWarnings = [...new Set(warnings.filter(Boolean).map(w=>typeof w==="string"?w:JSON.stringify(w)))];
  $("#alerts").innerHTML = (comparison_error ? `<div class="alert error"><span class="alert-title">暂时无法比较</span>${escapeHTML(comparison_error)}</div>` : "") + uniqueWarnings.slice(0,5).map(w=>`<div class="alert">${escapeHTML(w)}</div>`).join("");
  const rows = comparison?.rows || [];
  $("#current-year-header").textContent = `${currentYear} 年`;
  $("#previous-year-header").textContent = `${previousYear} 年`;
  $("#metric-coverage").textContent = `${ready} / 6 项可比较`;
  $("#metrics-body").innerHTML = comparison ? rows.map(row=>`<tr><td>${escapeHTML(row.label || metricLabels[row.key] || row.key)}</td><td>${metricCell(row.current,row,"current")}</td><td>${metricCell(row.previous,row,"previous")}</td><td><span class="metric-change ${row.status!=="ready"?"waiting":Number(row.change_pct)<0?"negative":""}" title="${escapeHTML(Array.isArray(row.notes) ? row.notes.join("；") : row.notes || "")}">${row.status==="ready"?escapeHTML(percentText(row.change_pct)):"—"}</span>${row.status==="ready"&&row.change_pct===null?'<span class="metric-source">基数不适用</span>':""}</td><td><span class="status-badge ${row.status==="ready"?"ready":row.status==="missing"?"missing":""}">${row.status==="ready"?"✓ 可比较":row.status==="missing"?"缺少数据":"待核对"}</span></td></tr>`).join("") : '<tr><td colspan="5">请先处理上方提示，再继续核对与对比。</td></tr>';
  $("#summary-grid").innerHTML = ["revenue","profit_parent","operating_cashflow"].map((key,index)=>{const row=rows.find(r=>r.key===key);const verified=row?.status==="ready"&&row.current_yuan!=null;return `<article class="summary-card"><div class="summary-title">${metricLabels[key]}<span class="summary-symbol" aria-hidden="true">${["↗","▥","≈"][index]}</span></div><div class="summary-value ${verified?"":"waiting"}">${verified?escapeHTML((Number(row.current_yuan)/1e8).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2}))+"<small>亿元</small>":"等待核对"}</div><div class="summary-change ${verified?"ready":""}">${verified?`同比 ${escapeHTML(percentText(row.change_pct))}`:"核对本期和上期数据后展示"}</div></article>`;}).join("");
  const insights = comparison?.insights || [];
  $("#insights-body").innerHTML = insights.length ? insights.map(item=>`<div class="insight-item"><span aria-hidden="true">↗</span><div>${escapeHTML(typeof item==="string"?item:item.text || item.message || JSON.stringify(item))}</div></div>`).join("") : '<div class="insight-placeholder">从上方指标开始逐项复核。确认两期数值后，这里会展示增长变化、现金流与利润等可验证的数据观察。</div>';
}

async function uploadFiles(files) {
  if (app.busy) return;
  const selected = Array.from(files || []); if (!selected.length) return;
  if (selected.length + app.state.reports.length > 2) return showToast("一次比较最多两份年报。请先删除不需要的资料。",true);
  for (const file of selected) {
    if (!/\.pdf$/i.test(file.name)) return showToast("请选择 PDF 格式的年报。",true);
    if (file.size > 25*1024*1024) return showToast(`${file.name} 超过 25 MB，请选择体积较小的文字版年报。`,true);
  }
  setBusy(true,"正在本地提取年报","识别期间与关键数据，整理原文页码；不会发送全文给模型。");
  try {for (const [index,file] of selected.entries()) {$("#busy-detail").textContent=`正在处理 ${index+1}/${selected.length}：${file.name}`;await api(`/api/upload?filename=${encodeURIComponent(file.name)}`,{method:"POST",headers:{"Content-Type":"application/pdf"},body:file});}await refresh();$("#answer-list").replaceChildren();showToast("年报已导入。请点击指标数值，核对原文后确认。");}
  catch(error) {await refresh().catch(()=>{});showToast(error.message,true);} finally {setBusy(false);$("#file-input").value="";}
}
async function loadDemo() {
  if (app.busy) return;
  if (app.state.reports.length) return showToast("请先删除当前资料，再加载两份公开示例年报。",true);
  setBusy(true,"正在准备公开年报示例","仅在本地提取 PDF。首次读取可能需要片刻。");
  try {await api("/api/demo",jsonOptions("POST"));await refresh();showToast("示例年报已准备好。点击数值即可回看原文并复核。");} catch(error){showToast(error.message,true);} finally {setBusy(false);}
}
async function deleteReport(id) {
  if(app.busy)return;
  const report=reportById(id); if(!report)return;
  if(!confirm(`删除“${report.filename}”？\n\n将移除本应用保存的 PDF、提取结果和复核记录。已下载的底稿不会删除。`))return;
  setBusy(true,"正在删除资料","清理本应用保存的原文和提取结果。");
  try {await api(`/api/reports/${encodeURIComponent(id)}`,jsonOptions("DELETE"));await refresh();$("#answer-list").replaceChildren();showToast("资料已删除。");} catch(error){showToast(error.message,true);} finally {setBusy(false);}
}
function closeDialog(id) {const dialog=document.getElementById(id);if(dialog?.open)dialog.close();}
function setSourceTab(tab) {app.sourceTab=tab;$("#source-frame").hidden=tab!=="pdf";$("#source-text").hidden=tab!=="text";$$("[data-source-tab]").forEach(button=>button.setAttribute("aria-selected",String(button.dataset.sourceTab===tab)));}
async function loadSourcePage() {
  const id=$("#source-report").value;const report=reportById(id);if(!report)return;
  const number=Math.max(1,Math.min(report.page_count||1,Number($("#source-page").value)||1));$("#source-page").value=String(number);$("#source-page").max=String(report.page_count||1);
  const seq=++app.sourceSeq;
  const url=`/api/reports/${encodeURIComponent(id)}/pdf#page=${number}&view=FitH`;
  $("#source-open").href=url;$("#source-text").textContent="正在读取这一页的文字…";
  const image=$("#source-image"); const imageStatus=$("#source-image-status");
  image.hidden=true; imageStatus.hidden=false; imageStatus.textContent=`正在本地渲染 PDF 第 ${number} 页…`;
  image.alt=`${report.filename}，PDF 第 ${number} 页原文`;
  image.onload=()=>{if(seq===app.sourceSeq){image.hidden=false;imageStatus.hidden=true;}};
  image.onerror=()=>{if(seq===app.sourceSeq){image.hidden=true;imageStatus.hidden=false;imageStatus.textContent="这一页暂时无法显示。可以切换“提取文字”，或点击“新窗口查看”打开 PDF 原文。";}};
  image.src=`/api/reports/${encodeURIComponent(id)}/image/${number}`;
  $("#source-frame").scrollTop=0;$("#source-frame").scrollLeft=0;
  if(app.review){app.review.reportId=id;$("#review-page").value=String(number);$("#review-page").max=String(report.page_count||1);}
  try{const data=await api(`/api/reports/${encodeURIComponent(id)}/page/${number}`);if(seq===app.sourceSeq)$("#source-text").textContent=data.text || "这一页未提取到可阅读文字，请查看 PDF 原文。";}catch(error){if(seq===app.sourceSeq)$("#source-text").textContent=error.message;}
}
function populateReview(id,key,year) {
  const report=reportById(id);if(!report)return;
  const metric=(report.metrics||[]).find(m=>m.key===key&&Number(m.year)===Number(year));
  app.review={reportId:id,key,year:Number(year)};
  $("#review-title").textContent=`${metricLabels[key] || key} · ${year}`;
  $("#review-description").textContent=metric?.value!=null?"请对照原文，确认该项数据的期间、单位与合并口径。":"未自动提取到数值，请在原文中找到依据后补录。";
  $("#review-year").value=String(year);$("#review-year").readOnly=true;
  $("#review-value").value=metric?.value??"";$("#review-unit").value=["元","千元","万元","百万元","亿元"].includes(metric?.unit)?metric.unit:"元";
  $("#review-currency").value=["CNY","USD","HKD"].includes(metric?.currency)?metric.currency:"unknown";
  $("#review-scope").value=metric?.scope || "unknown";
  $("#review-page").value=String(metric?.page || 1);$("#review-page").max=String(report.page_count||1);
  $("#review-evidence").textContent=metric?.evidence || "暂无自动提取依据。请在左侧查看原文，并填写数值所在的 PDF 页码。";
  $("#review-check").checked=false;$("#review-message").textContent="";
  $("#source-page").value=String(metric?.page || 1);$("#source-report").value=id;
}
async function openSource(id,page=1,reviewKey=null,year=null) {
  if(!reportById(id))return showToast("请先导入年报。",true);
  $("#source-report").innerHTML=app.state.reports.map(r=>`<option value="${escapeHTML(r.id)}">${escapeHTML(r.filename)}</option>`).join("");
  $("#source-report").value=id;$("#source-page").value=String(page||1);
  app.review=null;$("#review-form").hidden=!reviewKey;$("#source-only-note").hidden=Boolean(reviewKey);$("#review-message").textContent="";
  $("#review-title").textContent="查看来源";$("#review-description").textContent="核对原文中的期间、币种与单位。";
  if(reviewKey)populateReview(id,reviewKey,year);
  $("#source-title").textContent=reviewKey?"原文与数据复核":"年报原文";setSourceTab("pdf");
  if(!$("#source-dialog").open)$("#source-dialog").showModal();await loadSourcePage();
}
async function saveReview(event) {
  event.preventDefault();if(!app.review||app.saving)return;app.saving=true;
  const {reportId,key,year}=app.review;const value=$("#review-value").value.trim().replace(/[,，\s]/g,"");
  if(!/^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$/.test(value)){app.saving=false;return showToast("请填写原文中的有效数值，例如 123456.78。",true);}
  const payload={key,year,value,unit:$("#review-unit").value,currency:$("#review-currency").value,scope:$("#review-scope").value,page:Number($("#review-page").value),status:"confirmed"};
  const button=$("#review-submit");button.disabled=true;$("#review-message").textContent="正在保存复核记录…";
  try{await api(`/api/reports/${encodeURIComponent(reportId)}/metrics`,jsonOptions("PATCH",payload));await refresh();$("#answer-list").replaceChildren();$("#review-message").textContent="已保存复核记录。可关闭此窗口，继续核对下一项。";showToast("这项数据已核对。对比结果已更新。");$("#review-check").checked=false;}
  catch(error){$("#review-message").textContent=error.message;}finally{app.saving=false;button.disabled=false;}
}
function addAnswer(question,result) {
  const card=document.createElement("article");card.className="answer-card";
  const citations=result.citations||[];
  const seenPages=new Set();
  const displayedCitations=citations.map((citation,index)=>({citation,index})).filter(({citation})=>{const key=JSON.stringify([citation.report_id,String(citation.page)]);if(seenPages.has(key))return false;seenPages.add(key);return true;});
  const notice=Array.isArray(result.notice)?result.notice.filter(Boolean).join("；"):result.notice;
  card.innerHTML=`<div class="answer-question">${escapeHTML(question)}<span class="answer-mode">${result.mode==="deepseek"?"DeepSeek 解读":"本地查找"}</span></div><div class="answer-text">${escapeHTML(result.answer || "未获得回答。请尝试更具体的问题。")}</div>${notice?`<div class="answer-notice" role="note">${escapeHTML(notice)}</div>`:""}${displayedCitations.length?`<div class="citation-list">${displayedCitations.map(({citation:c,index})=>`<button class="citation-button" type="button" data-citation-index="${index}">${escapeHTML(c.filename || "来源资料")} · PDF 第 ${escapeHTML(c.page)} 页 ↗</button>`).join("")}</div>`:""}${result.mode==="deepseek"?'<div class="answer-followup">此段为模型解读，不改变已核对数据。请回看来源核实；导出底稿以本地数据为准。</div>':result.needs_model?'<div class="answer-followup">可以继续查阅来源；需要进一步解读时，选择 DeepSeek，并先检查发送预览。</div>':""}`;
  card.querySelectorAll("[data-citation-index]").forEach(button=>button.addEventListener("click",()=>{const c=citations[Number(button.dataset.citationIndex)];openSource(c.report_id,c.page);}));
  $("#answer-list").prepend(card);card.scrollIntoView({behavior:"smooth",block:"nearest"});
}
function getQuestion(){const question=$("#question").value.trim();if(!question){$("#question").focus();showToast("先输入你想了解的问题。");return null;}return question;}
async function askLocal(event){event?.preventDefault();if(app.asking||app.busy)return;const question=getQuestion();if(!question)return;const button=$("#local-ask-button");app.asking=true;button.disabled=true;button.textContent="正在查找…";try{const result=await api("/api/ask",jsonOptions("POST",{question}));addAnswer(question,result);}catch(error){showToast(error.message,true);}finally{app.asking=false;button.disabled=false;button.innerHTML='本地查找 <span aria-hidden="true">→</span>';}}
async function previewModel(){if(app.previewing||app.sending||app.busy)return;const question=getQuestion();if(!question)return;if(!app.state.model?.configured)return showToast("DeepSeek 尚未配置。请先打开项目的模型配置窗口；本地提取与查找可继续使用。",true);const button=$("#model-ask-button");app.previewing=true;button.disabled=true;try{const preview=await api("/api/model-preview",jsonOptions("POST",{question}));app.preview=preview;app.previewQuestion=question;$("#preview-meta").textContent=`服务：${preview.provider || "DeepSeek"} · 模型：${preview.model || "已配置模型"} · 预览约 ${preview.characters || JSON.stringify(preview.payload).length} 字符`;$("#preview-payload").textContent=typeof preview.payload==="string"?preview.payload:JSON.stringify(preview.payload,null,2);$("#model-approval").checked=false;$("#model-send-button").disabled=true;$("#model-dialog").showModal();}catch(error){showToast(error.message,true);}finally{app.previewing=false;button.disabled=false;}}
async function sendModel(){if(app.sending||!app.preview||!$("#model-approval").checked)return;app.sending=true;const button=$("#model-send-button");button.disabled=true;button.textContent="正在等待 DeepSeek…";try{const result=await api("/api/model-send",jsonOptions("POST",{preview_id:app.preview.preview_id,approved:true}));closeDialog("model-dialog");addAnswer(app.previewQuestion,result);app.preview=null;}catch(error){showToast(error.message,true);}finally{app.sending=false;button.disabled=!$("#model-approval").checked;button.textContent="确认发送并解读";}}

function setupEvents(){
  const scopeLabel=document.createElement("label");scopeLabel.innerHTML='报表口径<select id="review-scope"><option value="consolidated">合并口径</option><option value="parent">母公司口径</option><option value="unknown">待确认</option></select>';$("#review-page").closest("label").before(scopeLabel);
  $("#file-input").addEventListener("change",event=>uploadFiles(event.target.files));
  const zone=$("#upload-zone");zone.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();$("#file-input").click();}});
  ["dragenter","dragover"].forEach(type=>zone.addEventListener(type,event=>{event.preventDefault();zone.classList.add("dragover");}));["dragleave","drop"].forEach(type=>zone.addEventListener(type,event=>{event.preventDefault();zone.classList.remove("dragover");}));zone.addEventListener("drop",event=>uploadFiles(event.dataTransfer.files));
  $("#demo-main-button").addEventListener("click",loadDemo);$("#demo-side-button").addEventListener("click",loadDemo);$("#privacy-button").addEventListener("click",()=>$("#privacy-dialog").showModal());
  $("#report-list").addEventListener("click",event=>{const remove=event.target.closest("[data-delete-report]");if(remove)return deleteReport(remove.dataset.deleteReport);const open=event.target.closest("[data-open-report]");if(open)openSource(open.dataset.openReport);});
  $("#metrics-body").addEventListener("click",event=>{const button=event.target.closest("[data-review]");if(button)openSource(button.dataset.report,1,button.dataset.review,Number(button.dataset.year));});
  $$("[data-close]").forEach(button=>button.addEventListener("click",()=>closeDialog(button.dataset.close)));
  $$("dialog").forEach(dialog=>dialog.addEventListener("click",event=>{if(event.target===dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();}}));
  $$("[data-source-tab]").forEach(button=>button.addEventListener("click",()=>setSourceTab(button.dataset.sourceTab)));
  $("#source-go").addEventListener("click",loadSourcePage);$("#source-page").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();loadSourcePage();}});
  $("#source-report").addEventListener("change",()=>{if(app.review)populateReview($("#source-report").value,app.review.key,app.review.year);else $("#source-page").value="1";loadSourcePage();});
  $("#review-page").addEventListener("change",()=>{$("#source-page").value=$("#review-page").value;loadSourcePage();});$("#review-form").addEventListener("submit",saveReview);
  $("#question-form").addEventListener("submit",askLocal);$("#question").addEventListener("keydown",event=>{if(event.key==="Enter"&&(event.ctrlKey||event.metaKey)){event.preventDefault();askLocal();}});
  $$("[data-question]").forEach(button=>button.addEventListener("click",()=>{$("#question").value=button.dataset.question;$("#question").focus();}));
  $("#model-ask-button").addEventListener("click",previewModel);$("#model-approval").addEventListener("change",()=>{$("#model-send-button").disabled=app.sending||!$("#model-approval").checked;});$("#model-send-button").addEventListener("click",sendModel);
  $("#export-md").addEventListener("click",()=>{window.location.assign("/api/export?format=markdown");});$("#export-csv").addEventListener("click",()=>{window.location.assign("/api/export?format=csv");});
}
setupEvents();refresh().catch(error=>{showToast(error.message,true);$("#model-status").textContent="本地服务未连接";});
