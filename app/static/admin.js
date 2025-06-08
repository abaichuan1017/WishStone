const adminTokenInput = document.getElementById("adminToken");
const loadBtn = document.getElementById("loadBtn");
const statsEl = document.getElementById("stats");
const sessionsEl = document.getElementById("sessions");

const roleNameEl = document.getElementById("roleName");
const systemPromptEl = document.getElementById("systemPrompt");
const responseStyleEl = document.getElementById("responseStyle");
const forbiddenRulesEl = document.getElementById("forbiddenRules");
const savePromptBtn = document.getElementById("savePromptBtn");
const promptStatusEl = document.getElementById("promptStatus");

const VENUE_ID = "venue-liangzhu";

function adminHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Admin-Token": adminTokenInput.value.trim(),
  };
}

function formatSessionCard(s) {
  const createdAt = new Date(s.created_at).toLocaleString();
  const pageUrl = `/b/${s.blessing_page_slug}`;
  return `
    <article class="session-card" data-id="${s.id}">
      <p><strong>${s.venue_name}</strong> · ${createdAt}</p>
      <p>意图: ${s.intent}/${s.sub_intent} · 情绪: ${s.emotion} · 安全: ${s.safety}</p>
      <p>审核: <strong>${s.review_status}</strong></p>
      <p>用户: ${s.asr_text}</p>
      <p>回复: ${s.ai_reply_text}</p>
      <div class="row">
        <a class="btn" target="_blank" href="${pageUrl}">回听页</a>
        <button class="btn secondary" data-action="approve">通过</button>
        <button class="btn secondary" data-action="block">屏蔽</button>
        <button class="btn secondary" data-action="pending">待审</button>
      </div>
    </article>
  `;
}

async function fetchJSON(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

async function loadStats() {
  const data = await fetchJSON("/api/admin/stats", {
    headers: { "X-Admin-Token": adminTokenInput.value.trim() },
  });
  const stats = data.stats;
  const topIntents = stats.top_intents.map((x) => `${x.intent}:${x.count}`).join(" | ");
  statsEl.textContent = `总会话 ${stats.total_sessions}，安全通过 ${stats.safe_sessions}，拦截 ${stats.blocked_sessions}，已通过审核 ${stats.approved_sessions}，热门意图 ${topIntents || "暂无"}`;
}

async function loadPrompt() {
  const data = await fetchJSON(`/api/admin/prompts/${VENUE_ID}`, {
    headers: { "X-Admin-Token": adminTokenInput.value.trim() },
  });
  const p = data.prompt;
  roleNameEl.value = p.role_name;
  systemPromptEl.value = p.system_prompt;
  responseStyleEl.value = p.response_style;
  forbiddenRulesEl.value = p.forbidden_rules;
  promptStatusEl.textContent = `当前版本: ${p.version}`;
}

async function loadSessions() {
  const data = await fetchJSON("/api/admin/sessions?limit=30", {
    headers: { "X-Admin-Token": adminTokenInput.value.trim() },
  });
  const html = data.sessions.map(formatSessionCard).join("");
  sessionsEl.innerHTML = html || '<p class="meta">暂无会话</p>';
}

async function loadAll() {
  try {
    await Promise.all([loadStats(), loadPrompt(), loadSessions()]);
  } catch (err) {
    alert(err.message || "加载失败");
  }
}

savePromptBtn.addEventListener("click", async () => {
  try {
    const data = await fetchJSON(`/api/admin/prompts/${VENUE_ID}`, {
      method: "POST",
      headers: adminHeaders(),
      body: JSON.stringify({
        role_name: roleNameEl.value,
        system_prompt: systemPromptEl.value,
        response_style: responseStyleEl.value,
        forbidden_rules: forbiddenRulesEl.value,
      }),
    });
    promptStatusEl.textContent = `保存成功，新版本: ${data.version}`;
  } catch (err) {
    promptStatusEl.textContent = `保存失败: ${err.message}`;
  }
});

sessionsEl.addEventListener("click", async (event) => {
  const btn = event.target;
  if (!(btn instanceof HTMLElement)) return;
  const action = btn.getAttribute("data-action");
  if (!action) return;

  const card = btn.closest(".session-card");
  if (!card) return;
  const sessionId = card.getAttribute("data-id");
  if (!sessionId) return;

  const map = {
    approve: "approved",
    block: "blocked",
    pending: "pending",
  };
  const reviewStatus = map[action];

  try {
    await fetchJSON(`/api/admin/sessions/${sessionId}/review`, {
      method: "POST",
      headers: adminHeaders(),
      body: JSON.stringify({ review_status: reviewStatus }),
    });
    await loadSessions();
    await loadStats();
  } catch (err) {
    alert(err.message || "更新审核失败");
  }
});

loadBtn.addEventListener("click", loadAll);
