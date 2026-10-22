import {artFor} from "./art.js";
import {api} from "./nfc.js";
const $ = id => document.getElementById(id);
async function load() {
  try {
    const slug = window.location.pathname.split("/").filter(Boolean).pop();
    const {session} = await api(`/api/sessions/${encodeURIComponent(slug)}`);
    $("venueTitle").textContent = `${session.venue_name} · ${new Date(session.created_at).toLocaleDateString("zh-CN")}`;
    $("wishText").textContent = session.asr_text; $("replyText").textContent = session.ai_reply_text;
    $("memoryTags").replaceChildren(...session.intent.labels.map(item => { const tag = document.createElement("span"); tag.className = "tag"; tag.textContent = item.label; return tag; }));
    if (session.user_audio_url) { $("wishAudio").src = session.user_audio_url; $("wishAudio").hidden = false; }
    if (session.selected_souvenir) { $("memoryArt").innerHTML = artFor(session.selected_souvenir.motif, "memory"); $("souvenirName").textContent = session.selected_souvenir.name; }
    $("memoryContent").hidden = false;
  } catch (error) { $("venueTitle").textContent = error.message || "暂时无法打开这份心愿"; }
}
load();
