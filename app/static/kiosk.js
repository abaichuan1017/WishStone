import {artFor} from "./art.js";
import {HoldRecorder} from "./recorder.js";
import {api, post, writeAndVerify} from "./nfc.js";

const $ = id => document.getElementById(id);
const state = {venues: [], venue: null, session: null, busy: false, nfc: null, design: null, actionBusy: false};
let recordingTimer, recordingStarted, actionController;

function message(text, error = false) {
  $("status").textContent = text; $("status").hidden = !text; $("status").classList.toggle("error", error);
}
function busy(value, label = "正在安放心愿…") {
  state.busy = value;
  $("recordBtn").disabled = value || !state.venue;
  $("submitBtn").disabled = value;
  $("venueSelect").disabled = value;
  $("resetBtn").disabled = value;
  $("submitBtn").textContent = value ? label : "安放心愿 ↗";
}
function renderGallery() {
  $("souvenirGrid").replaceChildren();
  state.venue.souvenirs.forEach((item, index) => {
    const card = document.createElement("article"); card.className = "souvenir-card";
    card.classList.toggle("is-selected", state.session?.selected_souvenir?.sku === item.sku);
    const visual = document.createElement("div"); visual.className = "souvenir-visual"; visual.setAttribute("aria-hidden", "true"); visual.innerHTML = artFor(item.motif, "collection-" + index);
    const number = document.createElement("span"); number.className = "souvenir-number"; number.textContent = `NO. 0${index + 1}`;
    const category = document.createElement("span"); category.className = "souvenir-category"; category.textContent = item.intents.join(" · "); visual.append(number, category);
    const info = document.createElement("div"); info.className = "souvenir-info";
    const text = document.createElement("div"), title = document.createElement("h3"), subtitle = document.createElement("p"); title.textContent = item.name; subtitle.textContent = item.subtitle; text.append(title, subtitle);
    const choose = document.createElement("button"); choose.className = "souvenir-choose"; choose.textContent = "↗"; choose.setAttribute("aria-label", "选择" + item.name);
    choose.addEventListener("click", async () => {
      if (!state.session) { $("textEntry").open = true; $("wishInput").focus(); message("先说出或写下心愿，再挑选一件纪念品。"); return; }
      if (state.busy || state.actionBusy) return;
      busy(true);
      try { const data = await post(`/api/sessions/${state.session.slug}/souvenir`, {souvenir_sku: item.sku}); renderSession(data.session); message("已为你更换纪念品。"); }
      catch (error) { message(error.message, true); }
      finally { busy(false); }
    });
    info.append(text, choose); card.append(visual, info); $("souvenirGrid").append(card);
  });
}
function reset() {
  recorder.cancel(); actionController?.abort();
  state.session = null; state.nfc = null; state.design = null;
  $("result").hidden = true; $("nfcPanel").hidden = true; $("designPanel").hidden = true;
  $("wishInput").value = ""; $("charCount").textContent = "0 / 1000";
  $("actionStatus").textContent = ""; message(""); renderGallery();
}
function renderVenue() {
  reset(); $("venueTheme").textContent = state.venue.theme; $("venueDescription").textContent = state.venue.description;
  $("heroArt").innerHTML = artFor(state.venue.souvenirs[0].motif, "hero");
}
function renderSession(session) {
  actionController?.abort(); state.session = session; state.nfc = null; state.design = null;
  $("result").hidden = false; $("nfcPanel").hidden = true; $("designPanel").hidden = true; $("actionStatus").textContent = "";
  $("recognizedWish").textContent = session.asr.text;
  $("wishInput").value = session.asr.text; $("charCount").textContent = `${session.asr.text.length} / 1000`;
  $("replyText").textContent = session.ai_reply_text; $("blessingLink").href = session.blessing_page_url;
  $("intentTags").replaceChildren(...session.intent.labels.map(item => { const tag = document.createElement("span"); tag.className = "tag"; tag.textContent = item.label; return tag; }));
  $("classificationHint").textContent = session.intent.needs_confirmation ? "这份心愿有多种理解，你可以按自己的心意更换纪念品。" : "从你的话语中，找到这些心愿的线索。";
  const selected = session.selected_souvenir;
  $("selectedArt").innerHTML = artFor(selected.motif, "selected"); $("selectedName").textContent = selected.name; $("selectedReason").textContent = selected.reason;
  $("designBtn").disabled = !selected.customizable;
  $("designBtn").textContent = selected.customizable ? "3D 定制设计任务" : "此款暂不支持定制";
  renderGallery();
}
async function createWish(audio) {
  if (state.busy || !state.venue || recorder.phase !== "idle") return;
  const text = $("wishInput").value.trim();
  if (!audio && !text) { message("先写下你的心愿吧。", true); return; }
  busy(true); message(audio ? "正在听懂你的心愿，请稍候…" : "正在为心愿寻找一份合适的纪念…");
  try {
    let data;
    if (audio) {
      const form = new FormData(); form.append("venue_id", state.venue.id); form.append("device_id", state.venue.device_id);
      const extension = audio.type.includes("mp4") ? "m4a" : audio.type.includes("ogg") ? "ogg" : "webm";
      form.append("audio", audio, "wish." + extension);
      data = await api("/api/sessions", {method: "POST", body: form});
    } else data = await post("/api/sessions", {venue_id: state.venue.id, device_id: state.venue.device_id, user_text: text});
    renderSession(data.session); message(""); $("result").scrollIntoView({behavior: "smooth", block: "start"}); $("result").focus({preventScroll: true});
  } catch (error) { message(error.message, true); if (audio) $("textEntry").open = true; }
  finally { busy(false); }
}
const recorder = new HoldRecorder({
  onState(phase) {
    const active = phase === "recording";
    $("recordBtn").classList.toggle("is-recording", active); $("recordBtn").setAttribute("aria-pressed", String(active));
    $("waveform").hidden = !active; $("recordTimer").hidden = !active;
    $("recordLabel").textContent = active ? "正在聆听，松开完成" : phase === "requesting" ? "请允许麦克风访问" : "按住，说出心愿";
    $("venueSelect").disabled = phase !== "idle" || state.busy;
    clearInterval(recordingTimer);
    if (active) { recordingStarted = performance.now(); $("recordTimer").textContent = "00:00"; recordingTimer = setInterval(() => { $("recordTimer").textContent = "00:" + String(Math.min(60, Math.floor((performance.now() - recordingStarted) / 1000))).padStart(2, "0"); }, 200); }
  },
  onAudio: blob => createWish(blob), onError: error => message(error.message, true)
});
$("recordBtn").addEventListener("pointerdown", event => { if (state.busy || event.button !== 0) return; event.preventDefault(); $("recordBtn").setPointerCapture(event.pointerId); recorder.start(); });
$("recordBtn").addEventListener("pointerup", event => { event.preventDefault(); recorder.stop(); });
$("recordBtn").addEventListener("pointercancel", () => recorder.cancel());
$("recordBtn").addEventListener("lostpointercapture", () => { if (recorder.holding) recorder.cancel(); });
$("recordBtn").addEventListener("contextmenu", event => event.preventDefault());
$("recordBtn").addEventListener("keydown", event => { if ([" ", "Enter"].includes(event.key)) { event.preventDefault(); if (!event.repeat && !state.busy) recorder.start(); } });
$("recordBtn").addEventListener("keyup", event => { if ([" ", "Enter"].includes(event.key)) { event.preventDefault(); recorder.stop(); } });
window.addEventListener("blur", () => recorder.cancel());
document.addEventListener("visibilitychange", () => { if (document.hidden) { recorder.cancel(); actionController?.abort(); } });
window.addEventListener("pagehide", () => { recorder.cancel(); actionController?.abort(); });
$("wishForm").addEventListener("submit", event => { event.preventDefault(); createWish(); });
$("wishInput").addEventListener("input", () => { $("charCount").textContent = `${$("wishInput").value.length} / 1000`; });
$("resetBtn").addEventListener("click", () => { reset(); $("experience").scrollIntoView(); });
$("venueSelect").addEventListener("change", () => { state.venue = state.venues.find(v => v.id === $("venueSelect").value); renderVenue(); });

async function action(button, work) {
  if (state.actionBusy || state.busy) return;
  state.actionBusy = true; busy(true); button.disabled = true;
  try { await work(); } catch (error) { $("actionStatus").textContent = error.message; }
  finally { state.actionBusy = false; button.disabled = false; busy(false); }
}
$("nfcBtn").addEventListener("click", () => action($("nfcBtn"), async () => {
  const data = await api(`/api/sessions/${state.session.slug}/nfc`); state.nfc = data.nfc;
  $("nfcPanel").hidden = false; $("nfcUrl").value = data.nfc.url;
  $("nfcNotice").textContent = data.nfc.public_url_configured ? "已准备好专属链接。写入纪念品的 NTAG215 后，轻触即可重访心愿。" : "本地预览链接已准备好。给纪念品写入前，请先配置手机可访问的纪念页地址。";
  $("writeNfcBtn").hidden = !("NDEFReader" in window) || !data.nfc.public_url_configured;
  $("actionStatus").textContent = "已准备写入内容，尚未写入标签。";
}));
$("copyNfcBtn").addEventListener("click", () => action($("copyNfcBtn"), async () => {
  await navigator.clipboard.writeText($("nfcUrl").value); $("actionStatus").textContent = "链接已复制，可交给 NFC 读写器写入。";
}));
$("writeNfcBtn").addEventListener("click", () => action($("writeNfcBtn"), async () => {
  actionController = new AbortController();
  $("cancelNfcBtn").hidden = false;
  try {
    const data = await writeAndVerify(state.nfc, state.session, text => { $("actionStatus").textContent = text; }, actionController.signal);
    $("actionStatus").textContent = data.binding.verification;
  } finally { $("cancelNfcBtn").hidden = true; }
}));
$("cancelNfcBtn").addEventListener("click", () => actionController?.abort());
$("nfcRegisterForm").addEventListener("submit", event => { event.preventDefault(); action($("registerBtn"), async () => {
  const data = await post("/api/nfc/bind", {blessing_session_id: state.session.id, souvenir_sku: state.session.selected_souvenir.sku, nfc_uid: $("nfcUid").value.trim()});
  $("actionStatus").textContent = data.binding.verification;
}); });
$("designBtn").addEventListener("click", () => action($("designBtn"), async () => {
  const data = await post("/api/design-jobs", {slug: state.session.slug}); state.design = data.job;
  $("designPanel").hidden = false; $("designPrompt").textContent = data.job.prompt; $("designNotice").textContent = data.job.notice;
  $("actionStatus").textContent = "设计任务已准备，可下载并交给 3D 生成或建模服务。";
}));
$("downloadDesignBtn").addEventListener("click", () => {
  if (!state.design) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(state.design, null, 2)], {type: "application/json"}));
  const link = document.createElement("a"); link.href = url; link.download = state.design.id + ".json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
async function init() {
  try {
    const [catalog, health] = await Promise.all([api("/api/venues"), api("/api/health")]);
    if (!catalog.venues.length) throw new Error("没有可用场景，请检查场景配置。");
    state.venues = catalog.venues; state.venue = state.venues[0];
    $("venueSelect").replaceChildren(...state.venues.map(v => { const option = document.createElement("option"); option.value = v.id; option.textContent = v.name; return option; }));
    renderVenue(); busy(false);
    $("deviceStatus").textContent = `版本 ${health.version} · 转写：${health.asr === "configured" ? "已配置服务，待实际录音验证" : "待配置 SenseVoice 服务"} · 分类：本地规则 · 3D：设计任务 · NFC：待连接读写器。`;
    if (health.asr !== "configured") $("recordHint").textContent = "语音服务待连接 · 本地体验可先写下心愿";
  } catch (error) { message(error.message || "场景加载失败，请刷新后重试。", true); $("deviceStatus").textContent = "未能连接场景服务"; }
}
init();
