const pathParts = window.location.pathname.split("/");
const slug = pathParts[pathParts.length - 1];

const venueTitle = document.getElementById("venueTitle");
const wishText = document.getElementById("wishText");
const wishAudio = document.getElementById("wishAudio");
const roleTitle = document.getElementById("roleTitle");
const replyText = document.getElementById("replyText");
const replyAudio = document.getElementById("replyAudio");
const nfcUid = document.getElementById("nfcUid");
const sku = document.getElementById("sku");
const bindBtn = document.getElementById("bindBtn");
const bindResult = document.getElementById("bindResult");

let currentSessionId = "";

async function loadSession() {
  const res = await fetch(`/api/sessions/${slug}`);
  const data = await res.json();
  if (!res.ok) {
    venueTitle.textContent = "记录不存在";
    return;
  }

  const session = data.session;
  currentSessionId = session.id;
  venueTitle.textContent = `${session.venue_name} · ${new Date(session.created_at).toLocaleString()}`;
  roleTitle.textContent = `${session.role_name}回应`;
  wishText.textContent = session.asr_text;
  replyText.textContent = session.ai_reply_text;

  if (session.user_audio_url) {
    wishAudio.src = session.user_audio_url;
    wishAudio.hidden = false;
  }

  if (session.ai_reply_audio_url) {
    replyAudio.src = session.ai_reply_audio_url;
  }
}

bindBtn.addEventListener("click", async () => {
  if (!currentSessionId) {
    bindResult.textContent = "当前记录不可绑定";
    return;
  }
  if (!nfcUid.value.trim()) {
    bindResult.textContent = "请先输入 NFC UID";
    return;
  }

  bindBtn.disabled = true;
  bindResult.textContent = "绑定中...";

  const res = await fetch("/api/nfc/bind", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      blessing_session_id: currentSessionId,
      nfc_uid: nfcUid.value.trim(),
      souvenir_sku: sku.value.trim(),
    }),
  });
  const data = await res.json();

  if (!res.ok) {
    bindResult.textContent = data.error || "绑定失败";
    bindBtn.disabled = false;
    return;
  }

  bindResult.textContent = `绑定成功: ${data.binding.id}`;
  bindBtn.disabled = false;
});

loadSession();
