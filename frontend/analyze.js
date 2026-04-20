const caseTextInput = document.getElementById("caseText");
const submitBtn = document.getElementById("submitBtn");
const resetBtn = document.getElementById("resetBtn");
const chatTimeline = document.getElementById("chatTimeline");

let currentState = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function nl2br(value) {
  return escapeHtml(value).replaceAll("\n", "<br>");
}

function buildMessage(role, title, bodyHtml) {
  const row = document.createElement("article");
  row.className = `message-row ${role}`;
  row.innerHTML = `
    <div class="message-card">
      <div class="message-meta">
        <span class="avatar">${role === "user" ? "我" : "法"}</span>
        <strong>${escapeHtml(title)}</strong>
      </div>
      <div class="message-body">${bodyHtml}</div>
    </div>
  `;
  chatTimeline.appendChild(row);
  chatTimeline.scrollTop = chatTimeline.scrollHeight;
}

function addUserMessage(text) {
  buildMessage("user", "用户", nl2br(text));
}

function buildReferenceSection(result) {
  const laws = result.retrieval_results || [];
  const cases = result.case_results || [];

  return `
    <section class="message-section">
      <h3 class="section-title">相关法律与案例</h3>
      <div class="card-grid">
        ${
          laws.length
            ? laws.slice(0, 3).map((item) => `
                <article class="detail-card">
                  <h3>${escapeHtml(item.article_no || "相关法条")}</h3>
                  <p>${escapeHtml(item.full_path || "")}</p>
                  <p>${nl2br(item.content || "")}</p>
                </article>
              `).join("")
            : `<article class="mini-card"><strong>相似法律</strong><p>暂无</p></article>`
        }
        ${
          cases.length
            ? cases.slice(0, 2).map((item) => `
                <article class="detail-card">
                  <h3>${escapeHtml(item.title || "相关案例")}</h3>
                  <p>${escapeHtml(item.court || "")}</p>
                  <p>${nl2br(item.summary || "")}</p>
                </article>
              `).join("")
            : `<article class="mini-card"><strong>相关案例</strong><p>暂无</p></article>`
        }
      </div>
    </section>
  `;
}

function addAssistantMessage(result) {
  const message = result.response_text || result.analysis_result?.message || "已收到。";
  const bodyHtml = [
    `<p>${nl2br(message)}</p>`,
    result.status === "case_completed" ? buildReferenceSection(result) : "",
  ].join("");
  buildMessage("assistant", "总控 Agent", bodyHtml);
}

function addSystemMessage(text) {
  buildMessage("system", "系统", `<div class="error-box">${nl2br(text)}</div>`);
}

function updateState(result) {
  currentState = result.state || result.analysis_result?.state || currentState;
}

async function submitAnalyze() {
  const text = caseTextInput.value.trim();
  if (!text) {
    window.alert("请先输入内容。");
    return;
  }

  addUserMessage(text);
  caseTextInput.value = "";
  submitBtn.disabled = true;
  submitBtn.textContent = "发送中...";

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text,
        state: currentState,
        auto_load_kb: false,
        top_k: 5,
        enable_mqe: true,
        mqe_count: 3,
        enable_hyde: true,
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "请求失败");
    }

    updateState(data);
    addAssistantMessage(data);
  } catch (error) {
    addSystemMessage(`请求失败：${error.message}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "发送";
  }
}

function resetPage() {
  currentState = null;
  chatTimeline.innerHTML = "";
  caseTextInput.value = "";
  addAssistantMessage({
    status: "chat",
    analysis_result: {
      status: "chat",
      message: "你好，我会先和你正常对话；当你开始提供案情时，我会自动进入案件分析与法规查询。",
      state: null,
    },
    response_text: "你好，我会先和你正常对话；当你开始提供案情时，我会自动进入案件分析与法规查询。",
  });
}

submitBtn.addEventListener("click", submitAnalyze);
resetBtn.addEventListener("click", resetPage);
caseTextInput.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    submitAnalyze();
  }
});

resetPage();
