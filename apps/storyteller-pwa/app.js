// Storyteller PWA — main app logic
// Vanilla JS, no build step. Talks to the AutoGPT Platform REST API
// (/api/stories) and uses the browser's speechSynthesis for narration.

(function () {
  "use strict";

  // ---- State ----
  let baseUrl = localStorage.getItem("agentcloud_base_url") || "";
  let apiToken = localStorage.getItem("agentcloud_token") || "";
  let currentStory = null;
  let pollTimer = null;
  let deferredInstall = null;

  // ---- DOM refs ----
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);
  const topicInput = $("#topic-input");
  const languageSelect = $("#language-select");
  const styleInput = $("#style-input");
  const generateBtn = $("#generate-btn");
  const generateStatus = $("#generate-status");
  const storyListEl = $("#story-list");
  const readerEl = $("#reader-content");
  const backBtn = $("#back-btn");
  const serverUrlInput = $("#server-url");
  const apiTokenInput = $("#api-token");
  const saveUrlBtn = $("#save-url");

  // ---- Navigation ----
  $$(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });
  $("#settings-btn").addEventListener("click", () => switchView("settings"));
  backBtn.addEventListener("click", () => switchView("library"));

  function switchView(name) {
    $$(".view").forEach((v) => v.classList.remove("active"));
    $("#" + name).classList.add("active");
    $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    // The reader hides the bottom nav (immersive reading); back arrow appears.
    var immersive = name === "reader";
    document.querySelector(".bottomnav").classList.toggle("hidden", immersive);
    backBtn.classList.toggle("hidden", !immersive);
    if (name === "library") loadLibrary();
  }

  // ---- API ----
  function apiUrl(path) {
    // Empty baseUrl = same-origin (the PWA is served by the server itself).
    return (baseUrl ? baseUrl.replace(/\/$/, "") : "") + path;
  }

  function authHeaders(extra) {
    return Object.assign(
      extra || {},
      apiToken ? { Authorization: "Bearer " + apiToken } : {}
    );
  }

  async function apiGet(path) {
    const res = await fetch(apiUrl(path), {
      credentials: "include",
      headers: authHeaders({ Accept: "application/json" }),
    });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error("HTTP " + res.status + ": " + (await res.text()));
    return res.json();
  }

  async function apiPost(path, body) {
    const res = await fetch(apiUrl(path), {
      method: "POST",
      credentials: "include",
      headers: authHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let detail = await res.text();
      try { detail = JSON.parse(detail).detail || detail; } catch (e) { /* raw text */ }
      throw new Error("HTTP " + res.status + ": " + detail);
    }
    return res.json();
  }

  // ---- Generate a story ----
  generateBtn.addEventListener("click", startGeneration);

  async function startGeneration() {
    var topic = topicInput.value.trim();
    var language = languageSelect.value;
    var style = styleInput.value.trim();

    if (!baseUrl && !apiToken) {
      generateStatus.textContent = "Set the server URL in ⚙ Settings first.";
      return;
    }
    if (topic.length < 3) {
      generateStatus.textContent = "Give the story a topic (at least 3 characters).";
      return;
    }

    generateBtn.disabled = true;
    try {
      var resp = await apiPost("/api/stories/generate", {
        topic: topic,
        language: language,
        style: style,
      });
      generateStatus.textContent = "✨ Writing your story… this takes 30-60 seconds.";
      pollUntilReady(resp.id);
    } catch (e) {
      generateStatus.textContent = "Error: " + e.message;
      generateBtn.disabled = false;
    }
  }

  function pollUntilReady(storyId) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async function () {
      try {
        var story = await apiGet("/api/stories/" + storyId);
        if (!story) { stopPolling("Story not found."); return; }
        if (story.status === "ready") {
          stopPolling(null);
          currentStory = story;
          renderReader(story);
          switchView("reader");
        } else if (story.status === "failed") {
          stopPolling("Generation failed: " + (story.error || "unknown error"));
        }
      } catch (e) {
        stopPolling("Error while polling: " + e.message);
      }
    }, 3000);
  }

  function stopPolling(message) {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    generateBtn.disabled = false;
    if (message) generateStatus.textContent = message;
    else generateStatus.textContent = "";
  }

  // ---- Library ----
  async function loadLibrary() {
    storyListEl.innerHTML = '<div class="loading">Loading…</div>';
    try {
      var stories = await apiGet("/api/stories");
      if (!stories || stories.length === 0) {
        storyListEl.innerHTML =
          '<div class="loading">No stories yet. Create one from the ✨ Create tab.</div>';
        return;
      }
      storyListEl.innerHTML = stories.map(function (s) {
        var date = s.created_at ? new Date(s.created_at).toLocaleDateString("en-IN", {
          day: "numeric", month: "short",
        }) : "";
        var img = s.image_url
          ? '<img class="story-thumb" loading="lazy" src="' + escAttr(s.image_url) + '" alt="">'
          : "";
        var statusBadge = s.status !== "ready"
          ? '<span class="badge">' + esc(s.status) + "</span>"
          : "";
        return (
          '<div class="story-item" data-id="' + escAttr(s.id) + '">' +
          img +
          '<div class="story-meta">' +
          "<h4>" + esc(s.title || s.topic) + "</h4>" +
          '<div class="sub">' + esc(s.language) + " · " + date + " " + statusBadge + "</div>" +
          "</div></div>"
        );
      }).join("");

      $$(".story-item").forEach(function (el) {
        el.addEventListener("click", function () {
          var story = stories.find(function (s) { return s.id === el.dataset.id; });
          if (story && story.status === "ready") {
            currentStory = story;
            renderReader(story);
            switchView("reader");
          }
        });
      });
    } catch (e) {
      storyListEl.innerHTML = '<div class="error-msg">' + esc(e.message) + "</div>";
    }
  }

  // ---- Reader + speech synthesis ----
  function renderReader(story) {
    var langCode = getLangCode(story.language);
    readerEl.innerHTML =
      '<article class="story-card">' +
      (story.image_url
        ? '<img class="cover" src="' + escAttr(story.image_url) + '" alt="Story illustration">'
        : "") +
      "<h2>" + esc(story.title) + "</h2>" +
      '<div class="story-meta-row">' + esc(story.language) +
      (story.topic ? " · about: " + esc(story.topic) : "") + "</div>" +
      '<div class="story-text">' + esc(story.story) + "</div>" +
      '<div class="tts-controls">' +
      '<button id="tts-play" class="tts-btn">▶ Read Aloud</button>' +
      '<button id="tts-stop" class="tts-btn subtle">■ Stop</button>' +
      '<label class="rate-label">Speed <input type="range" id="tts-rate" min="0.5" max="1.5" step="0.1" value="0.9"></label>' +
      "</div>" +
      "</article>";

    $("#tts-play").addEventListener("click", function () {
      speak(story.story, langCode);
    });
    $("#tts-stop").addEventListener("click", stopSpeech);
    $("#tts-rate").addEventListener("input", function () {
      // Restart speech at the new rate if currently speaking.
      if (window.speechSynthesis && window.speechSynthesis.speaking) {
        stopSpeech();
        speak(story.story, langCode);
      }
    });
  }

  function getLangCode(languageName) {
    var opt = languageSelect.querySelector(
      'option[value="' + (languageName || "").replace(/"/g, '\\"') + '"]'
    );
    return (opt && opt.dataset.langCode) || "en-IN";
  }

  function speak(text, langCode) {
    if (!("speechSynthesis" in window)) {
      alert("Speech synthesis is not supported in this browser.");
      return;
    }
    stopSpeech();
    var rate = parseFloat(($("#tts-rate") || {}).value || "0.9");
    // Split into chunks: some browsers cut off long utterances.
    var chunks = chunkText(text, 220);
    chunks.forEach(function (chunk) {
      var u = new SpeechSynthesisUtterance(chunk);
      u.lang = langCode;
      u.rate = rate;
      u.pitch = 1.0;
      window.speechSynthesis.speak(u);
    });
  }

  function stopSpeech() {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  }

  function chunkText(text, maxLen) {
    var parts = [];
    var paragraphs = (text || "").split(/\n+/);
    var buf = "";
    paragraphs.forEach(function (p) {
      if ((buf + " " + p).length > maxLen && buf) {
        parts.push(buf.trim());
        buf = p;
      } else {
        buf = buf ? buf + "\n" + p : p;
      }
    });
    if (buf.trim()) parts.push(buf.trim());
    return parts;
  }

  // ---- Settings: server URL + token (shared keys with the News Curator) ----
  serverUrlInput.value = baseUrl;
  apiTokenInput.value = apiToken;
  saveUrlBtn.addEventListener("click", function () {
    var url = serverUrlInput.value.trim();
    if (url && !url.startsWith("http")) {
      url = "https://" + url;
      serverUrlInput.value = url;
    }
    baseUrl = url.replace(/\/$/, "");
    apiToken = apiTokenInput.value.trim();
    localStorage.setItem("agentcloud_base_url", baseUrl);
    localStorage.setItem("agentcloud_token", apiToken);
    saveUrlBtn.textContent = "Saved!";
    setTimeout(function () { saveUrlBtn.textContent = "Save"; }, 1500);
  });

  // ---- PWA install prompt ----
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferredInstall = e;
    var banner = document.createElement("div");
    banner.className = "install-banner";
    banner.innerHTML = "Install Storyteller for quick access <button>Install</button>";
    banner.querySelector("button").addEventListener("click", async function () {
      banner.remove();
      deferredInstall.prompt();
      await deferredInstall.userChoice;
      deferredInstall = null;
    });
    document.body.appendChild(banner);
  });

  // ---- Service Worker ----
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("sw.js").catch(function (e) {
        console.warn("SW registration failed:", e);
      });
    });
  }

  // ---- Utilities ----
  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }
  function escAttr(s) {
    return esc(s).replace(/"/g, "&quot;");
  }

  // ---- Init ----
  if (!baseUrl && !apiToken) {
    generateStatus.textContent = "Open ⚙ Settings to set your server URL first.";
  }
})();
