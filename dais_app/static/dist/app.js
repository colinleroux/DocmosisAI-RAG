
const app = document.querySelector("#app");

app.innerHTML = `
  <main class="mx-auto grid min-h-screen w-full max-w-7xl grid-cols-1 gap-5 p-4 lg:grid-cols-[1.7fr_1fr]">
    <section class="panel grid min-h-[85vh] grid-rows-[auto_1fr_auto] overflow-hidden">
      <header class="border-b border-slate-800 bg-slate-900/95 px-5 py-4">
        <h1 class="text-lg font-bold">DaiS Chat</h1>
        <p class="mt-1 text-sm text-slate-400">No-auth documentation assistant with grounded evidence.</p>
      </header>

      <div id="messages" class="space-y-3 overflow-auto p-4"></div>

      <form id="chat-form" class="grid grid-cols-[1fr_auto] gap-3 border-t border-slate-800 bg-slate-900/95 p-4">
        <textarea id="message" class="field min-h-[56px] max-h-40 resize-y" placeholder="Ask something about your docs..." required></textarea>
        <button id="send" class="btn-primary" type="submit">Send</button>
      </form>
    </section>

    <aside class="panel min-h-[85vh] overflow-hidden">
      <header class="border-b border-slate-800 px-5 py-4">
        <h2 class="text-lg font-bold">Controls + Evidence</h2>
        <p class="mt-1 text-sm text-slate-400">Tune retrieval and inspect citation support.</p>
      </header>

      <div class="h-[calc(85vh-70px)] space-y-4 overflow-auto p-4">
        <label class="block text-xs uppercase tracking-wide text-slate-400">Session ID
          <input id="session-id" class="field mt-1" type="text" />
        </label>

        <label class="block text-xs uppercase tracking-wide text-slate-400">Top K <span id="top-k-value" class="ml-1 text-slate-200">5</span>
          <input id="top-k" class="mt-2 w-full accent-cyan-400" type="range" min="1" max="20" step="1" value="5" />
        </label>

        <label class="block text-xs uppercase tracking-wide text-slate-400">Max Sources <span id="max-sources-value" class="ml-1 text-slate-200">5</span>
          <input id="max-sources" class="mt-2 w-full accent-cyan-400" type="range" min="1" max="12" step="1" value="5" />
        </label>

        <label class="block text-xs uppercase tracking-wide text-slate-400">Min Score <span id="min-score-value" class="ml-1 text-slate-200">0.35</span>
          <input id="min-score" class="mt-2 w-full accent-cyan-400" type="range" min="0" max="1" step="0.01" value="0.35" />
        </label>

        <div class="rounded-xl border border-slate-800 p-3 text-sm">
          <div class="mb-2 font-semibold text-slate-300">Strictness</div>
          <label class="mb-1 block"><input type="radio" name="strictness" value="balanced" checked /> Balanced</label>
          <label class="block"><input type="radio" name="strictness" value="strict" /> Strict</label>
        </div>

        <div class="rounded-xl border border-slate-800 p-3 text-sm">
          <div class="mb-2 font-semibold text-slate-300">Answer Style</div>
          <label class="mb-1 block"><input type="radio" name="answer-style" value="auto" checked /> Auto</label>
          <label class="mb-1 block"><input type="radio" name="answer-style" value="concise" /> Concise</label>
          <label class="mb-1 block"><input type="radio" name="answer-style" value="detailed" /> Detailed</label>
          <label class="mb-1 block"><input type="radio" name="answer-style" value="steps" /> Step-by-step</label>
          <label class="block"><input type="radio" name="answer-style" value="parameters" /> Parameters</label>
        </div>

        <div class="rounded-xl border border-slate-800 p-3 text-sm">
          <div class="mb-2 font-semibold text-slate-300">Reasoning Mode</div>
          <label class="mb-1 block"><input type="radio" name="reasoning-mode" value="grounded" checked /> Grounded</label>
          <label class="block"><input type="radio" name="reasoning-mode" value="reasoned" /> Grounded + deduction</label>
        </div>

        <label class="flex items-center gap-2 text-sm"><input id="debug" type="checkbox" checked /> Include retrieved previews</label>

        <div class="grid grid-cols-2 gap-2">
          <button id="setup-models" class="btn-secondary" type="button">Setup Models</button>
          <button id="ingest" class="btn-primary" type="button">Ingest Docs</button>
        </div>

        <p id="status" class="text-sm text-slate-400">Ready</p>

        <div class="rounded-xl border border-slate-800 p-3">
          <div class="mb-2 flex items-center justify-between">
            <div class="text-sm font-semibold">Ingested Docs</div>
            <button id="refresh-docs" class="btn-secondary !px-2 !py-1 text-xs" type="button">Refresh</button>
          </div>
          <p id="doc-summary" class="text-xs text-slate-400">Loading...</p>
          <div id="doc-list" class="mt-2 space-y-2"></div>
        </div>

        <div id="sources" class="space-y-2"></div>
      </div>
    </aside>
  </main>
`;

const form = document.getElementById("chat-form");
const msgInput = document.getElementById("message");
const sendBtn = document.getElementById("send");
const topKInput = document.getElementById("top-k");
const topKValue = document.getElementById("top-k-value");
const maxSourcesInput = document.getElementById("max-sources");
const maxSourcesValue = document.getElementById("max-sources-value");
const minScoreInput = document.getElementById("min-score");
const minScoreValue = document.getElementById("min-score-value");
const debugInput = document.getElementById("debug");
const setupModelsBtn = document.getElementById("setup-models");
const ingestBtn = document.getElementById("ingest");
const refreshDocsBtn = document.getElementById("refresh-docs");
const sessionInput = document.getElementById("session-id");
const messagesEl = document.getElementById("messages");
const sourcesEl = document.getElementById("sources");
const docSummaryEl = document.getElementById("doc-summary");
const docListEl = document.getElementById("doc-list");
const statusEl = document.getElementById("status");

function appendMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role === "user" ? "msg-user" : "msg-bot"}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function selectedRadio(name, fallback) {
  const el = document.querySelector(`input[name="${name}"]:checked`);
  return el ? el.value : fallback;
}

function refreshControlLabels() {
  topKValue.textContent = String(topKInput.value);
  maxSourcesValue.textContent = String(maxSourcesInput.value);
  minScoreValue.textContent = Number(minScoreInput.value).toFixed(2);
}

function renderSources(sources, citations, retrieved) {
  sourcesEl.innerHTML = "";
  const previews = new Map();
  (retrieved || []).forEach((item) => previews.set(item.citation, item.preview || ""));
  const sourceList = Array.isArray(sources) && sources.length > 0
    ? sources
    : [...new Set(citations || [])].map((c) => ({ citation: c, label: c, preview: previews.get(c) || "" }));

  if (sourceList.length === 0) {
    const empty = document.createElement("div");
    empty.className = "rounded-xl border border-slate-800 bg-slate-900 p-3 text-xs text-slate-400";
    empty.textContent = "No citations returned for this response.";
    sourcesEl.appendChild(empty);
    return;
  }

  sourceList.forEach((src, i) => {
    const card = document.createElement("article");
    card.className = "rounded-xl border border-slate-800 bg-slate-900 p-3 text-xs";
    card.innerHTML = `
      <div class="font-semibold text-slate-200">[${i + 1}] ${src.label || src.citation}</div>
      <div class="mt-1 text-slate-400">${src.page ? `Page ${src.page}` : "No page metadata"}</div>
      <div class="mt-2 text-slate-300">${src.preview || previews.get(src.citation) || "Preview unavailable for this citation."}</div>
      <div class="mt-2 break-all text-slate-500">Raw reference: ${src.citation}</div>
    `;
    sourcesEl.appendChild(card);
  });
}

function renderIngestedDocs(docs) {
  docListEl.innerHTML = "";
  if (!Array.isArray(docs) || docs.length === 0) {
    docListEl.innerHTML = '<div class="text-xs text-slate-500">No documents indexed yet.</div>';
    return;
  }

  docs.forEach((d) => {
    const item = document.createElement("article");
    item.className = "rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs";
    item.innerHTML = `
      <div class="font-medium text-slate-300">${d.source || "unknown"}</div>
      <div class="mt-1 text-slate-500">Pages: ${d.page_count || 0} | Chunks: ${d.chunks || 0}</div>
    `;
    docListEl.appendChild(item);
  });
}

async function sendMessage(message) {
  const payload = {
    message,
    session_id: sessionInput.value.trim() || null,
    top_k: Number(topKInput.value || 5),
    max_sources: Number(maxSourcesInput.value || 5),
    strictness: selectedRadio("strictness", "balanced"),
    min_semantic_score: Number(minScoreInput.value || 0.35),
    answer_style: selectedRadio("answer-style", "auto"),
    reasoning_mode: selectedRadio("reasoning-mode", "grounded"),
    debug: Boolean(debugInput.checked),
  };

  sendBtn.disabled = true;
  statusEl.textContent = "Asking DaiS...";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Request failed");

    if (data.session_id) sessionInput.value = data.session_id;
    appendMessage("bot", data.answer || "(empty response)");

    if (data.meta?.reasoning_mode_requested === "reasoned" && data.meta?.reasoning_applied === false) {
      appendMessage("bot", "Note: deduction mode requested, but evidence was weak so response stayed grounded.");
    }

    renderSources(data.sources || [], data.citations || [], data.retrieved || []);
    statusEl.textContent = "Complete";
  } catch (err) {
    appendMessage("bot", `Error: ${err.message}`);
    statusEl.textContent = "Failed";
  } finally {
    sendBtn.disabled = false;
    msgInput.focus();
  }
}

async function ingestDocs() {
  ingestBtn.disabled = true;
  statusEl.textContent = "Ingesting docs...";

  try {
    const res = await fetch("/api/ingest", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Ingest failed");

    appendMessage("bot", `Ingest complete: files=${data.files}, doc_units=${data.doc_units}, chunks=${data.chunks}, collection=${data.collection}`);
    statusEl.textContent = "Ingest complete";
    await loadIngestedDocs();
  } catch (err) {
    appendMessage("bot", `Ingest error: ${err.message}`);
    statusEl.textContent = "Ingest failed";
  } finally {
    ingestBtn.disabled = false;
  }
}

async function loadIngestedDocs() {
  refreshDocsBtn.disabled = true;
  try {
    const res = await fetch("/api/ingested-docs");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load ingested docs");

    docSummaryEl.textContent = `Collection: ${data.collection} | Indexed docs: ${data.count}`;
    renderIngestedDocs(data.docs || []);
  } catch (err) {
    docSummaryEl.textContent = `Could not load docs: ${err.message}`;
    docListEl.innerHTML = "";
  } finally {
    refreshDocsBtn.disabled = false;
  }
}

async function setupModels() {
  setupModelsBtn.disabled = true;
  statusEl.textContent = "Pulling models in Ollama...";

  try {
    const res = await fetch("/api/setup-models", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Model setup failed");

    appendMessage("bot", `Models ready: embed=${data.embed_model}, generation=${data.model_name}.`);
    statusEl.textContent = "Models ready";
  } catch (err) {
    appendMessage("bot", `Model setup error: ${err.message}`);
    statusEl.textContent = "Model setup failed";
  } finally {
    setupModelsBtn.disabled = false;
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = msgInput.value.trim();
  if (!text) return;

  appendMessage("user", text);
  msgInput.value = "";
  await sendMessage(text);
});

refreshControlLabels();
loadIngestedDocs();
appendMessage("bot", "DaiS is ready. Ask a question to begin.");

setupModelsBtn.addEventListener("click", setupModels);
ingestBtn.addEventListener("click", ingestDocs);
refreshDocsBtn.addEventListener("click", loadIngestedDocs);
topKInput.addEventListener("input", refreshControlLabels);
maxSourcesInput.addEventListener("input", refreshControlLabels);
minScoreInput.addEventListener("input", refreshControlLabels);
