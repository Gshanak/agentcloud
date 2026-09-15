// News Curator PWA — main app logic
// Vanilla JS, no build step. Talks to the AutoGPT Platform REST API.

(function () {
  "use strict";

  // ---- State ----
  let baseUrl = localStorage.getItem("agentcloud_base_url") || "";
  let apiToken = localStorage.getItem("agentcloud_token") || "";
  let deferredInstall = null;

  // ---- DOM refs ----
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);
  const briefingEl = $("#briefing-content");
  const historyEl = $("#history-list");
  const refreshBtn = $("#refresh-btn");
  const serverUrlInput = $("#server-url");
  const apiTokenInput = $("#api-token");
  const saveUrlBtn = $("#save-url");
  const pushBtn = $("#push-sub-btn");
  const pushStatus = $("#push-status");

  // ---- Navigation ----
  $$(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });
  $("#settings-btn").addEventListener("click", () => switchView("settings"));

  function switchView(name) {
    $$(".view").forEach((v) => v.classList.remove("active"));
    $("#" + name).classList.add("active");
    $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    if (name === "history") loadHistory();
  }

  // ---- API ----
  async function apiGet(path) {
    // Empty baseUrl = same-origin (the PWA is served by the server itself).
    const res = await fetch((baseUrl ? baseUrl.replace(/\/$/, "") : "") + path, {
      credentials: "include",
      headers: Object.assign(
        { Accept: "application/json" },
        apiToken ? { Authorization: "Bearer " + apiToken } : {}
      ),
    });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error("HTTP " + res.status + ": " + (await res.text()));
    return res.json();
  }

  // ---- Latest briefing ----
  async function loadLatest() {
    briefingEl.innerHTML = '<div class="loading">Loading…</div>';
    try {
      const data = await apiGet("/api/briefings");
      if (!data) {
        briefingEl.innerHTML =
          '<div class="loading">No briefing yet. The first scheduled run at 7:00 AM IST will produce one.</div>';
        return;
      }
      renderBriefing(briefingEl, data);
    } catch (e) {
      briefingEl.innerHTML = '<div class="error-msg">' + esc(e.message) + "</div>";
    }
  }

  function renderBriefing(container, data) {
    const date = data.created_at ? new Date(data.created_at).toLocaleString("en-IN", {
      day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    }) : "";
    container.innerHTML =
      '<h3>' + esc(data.title || "Daily News Briefing") + "</h3>" +
      '<div class="briefing-meta">' + date + (data.article_count != null ? " · " + data.article_count + " articles" : "") + "</div>" +
      '<div class="briefing-text">' + esc(data.briefing || "") + "</div>";
  }

  // ---- History ----
  async function loadHistory() {
    historyEl.innerHTML = '<div class="loading">Loading…</div>';
    try {
      const items = await apiGet("/api/briefings/history");
      if (!items || items.length === 0) {
        historyEl.innerHTML = '<div class="loading">No past briefings yet.</div>';
        return;
      }
      historyEl.innerHTML = items.map(function (item) {
        var date = item.created_at ? new Date(item.created_at).toLocaleDateString("en-IN", {
          day: "numeric", month: "short", year: "numeric",
        }) : "";
        var preview = (item.briefing || "").slice(0, 120) + "…";
        return (
          '<div class="history-item" data-id="' + esc(item.id) + '">' +
          "<h4>" + esc(item.title || "Briefing") + "</h4>" +
          '<div class="date">' + date + "</div>" +
          '<div class="preview">' + esc(preview) + "</div>" +
          "</div>"
        );
      }).join("");
      // Click to expand
      $$(".history-item").forEach(function (el) {
        el.addEventListener("click", function () {
          var id = el.dataset.id;
          var item = items.find(function (i) { return i.id === id; });
          if (item) {
            briefingEl.innerHTML = "";
            renderBriefing(briefingEl, item);
            switchView("latest");
          }
        });
      });
    } catch (e) {
      historyEl.innerHTML = '<div class="error-msg">' + esc(e.message) + "</div>";
    }
  }

  // ---- Refresh ----
  refreshBtn.addEventListener("click", loadLatest);

  // ---- Settings: server URL ----
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
    if (baseUrl || apiToken) loadLatest();
  });

  // ---- Push notifications ----
  pushBtn.addEventListener("click", togglePush);

  async function togglePush() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      pushStatus.textContent = "Push not supported on this browser";
      return;
    }
    if (!baseUrl) {
      pushStatus.textContent = "Set the server URL first";
      return;
    }

    try {
      var reg = await navigator.serviceWorker.ready;
      var existing = await reg.pushManager.getSubscription();
      if (existing) {
        await existing.unsubscribe();
        // Also tell the server
        await fetch(baseUrl.replace(/\/$/, "") + "/api/push/unsubscribe", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: existing.endpoint }),
        }).catch(function () {});
        pushStatus.textContent = "Unsubscribed";
        pushBtn.textContent = "Enable Notifications";
        return;
      }

      // Get VAPID public key from the platform
      var keyRes = await fetch(baseUrl.replace(/\/$/, "") + "/api/push/vapid-key", {
        credentials: "include",
        headers: apiToken ? { Authorization: "Bearer " + apiToken } : {},
      });
      if (!keyRes.ok) throw new Error("Could not fetch VAPID key");
      var keyData = await keyRes.json();
      var vapidKey = urlBase64ToUint8Array(keyData.public_key);

      var subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: vapidKey,
      });

      // Send subscription to the platform
      await fetch(baseUrl.replace(/\/$/, "") + "/api/push/subscribe", {
        method: "POST",
        credentials: "include",
        headers: Object.assign(
          { "Content-Type": "application/json" },
          apiToken ? { Authorization: "Bearer " + apiToken } : {}
        ),
        body: JSON.stringify({
          endpoint: subscription.endpoint,
          keys: {
            p256dh: arrayBufferToBase64(subscription.getKey("p256dh")),
            auth: arrayBufferToBase64(subscription.getKey("auth")),
          },
        }),
      });

      pushStatus.textContent = "Subscribed — you'll be notified when new briefings arrive";
      pushBtn.textContent = "Disable Notifications";
    } catch (e) {
      pushStatus.textContent = "Error: " + e.message;
    }
  }

  async function checkPushSubscription() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
    try {
      var reg = await navigator.serviceWorker.ready;
      var sub = await reg.pushManager.getSubscription();
      if (sub) {
        pushStatus.textContent = "Subscribed";
        pushBtn.textContent = "Disable Notifications";
      }
    } catch (e) {}
  }

  // ---- PWA install prompt ----
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferredInstall = e;
    showInstallBanner();
  });

  function showInstallBanner() {
    if (!deferredInstall) return;
    var banner = document.createElement("div");
    banner.className = "install-banner";
    banner.innerHTML = "Install News Curator for quick access <button>Install</button>";
    banner.querySelector("button").addEventListener("click", async function () {
      banner.remove();
      deferredInstall.prompt();
      var choice = await deferredInstall.userChoice;
      deferredInstall = null;
    });
    document.body.appendChild(banner);
  }

  // ---- Service Worker registration ----
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("sw.js").then(checkPushSubscription).catch(function (e) {
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

  function urlBase64ToUint8Array(base64String) {
    var padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    var base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    var raw = atob(base64);
    var arr = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
    return arr;
  }

  function arrayBufferToBase64(buf) {
    if (!buf) return "";
    var arr = new Uint8Array(buf);
    var binary = "";
    for (var i = 0; i < arr.length; i++) binary += String.fromCharCode(arr[i]);
    return btoa(binary);
  }

  // ---- Init ----
  if (baseUrl || apiToken) loadLatest();
  else briefingEl.innerHTML = '<div class="loading">Open ⚙ Settings to set your server URL.</div>';
})();
