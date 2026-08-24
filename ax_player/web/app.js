"use strict";

const $ = (id) => document.getElementById(id);

// The channel connects a beat after DOMContentLoaded. Starting with a no-op
// stub means a click landing in that window is ignored rather than throwing.
const NOOP_BRIDGE = new Proxy({}, { get: () => () => {} });

const state = {
  bridge: NOOP_BRIDGE,
  items: [],
  playing: null,
  rowsByPath: new Map(), // path -> <li>, rebuilt on every renderPlaylist
  thumbsByPath: new Map(), // path -> <img>, rebuilt on every renderPlaylist
  activeRow: null,
};

/* ── playlist ─────────────────────────────────────────────── */
// Only ask for a thumbnail once its row is near the viewport. A folder with
// thousands of files would otherwise kick off thousands of mpv frame-grabs
// on open.
const thumbObserver = new IntersectionObserver(
  (entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const img = entry.target;
      thumbObserver.unobserve(img);
      state.bridge.requestThumbnail(img.dataset.path);
    }
  },
  { root: null, rootMargin: "300px 0px" }
);

function renderPlaylist(items) {
  const list = $("playlist");
  list.innerHTML = "";
  state.rowsByPath = new Map();
  state.thumbsByPath = new Map();
  state.activeRow = null;
  const hasItems = items.length > 0;
  list.classList.toggle("is-hidden", !hasItems);
  $("emptyState").classList.toggle("is-hidden", hasItems);

  const frag = document.createDocumentFragment();
  for (const item of items) {
    const li = document.createElement("li");
    li.className = "row";
    li.dataset.path = item.path;
    const img = document.createElement("img");
    img.alt = "";
    img.dataset.path = item.path;
    const thumb = document.createElement("div");
    thumb.className = "thumb";
    thumb.appendChild(img);
    const name = document.createElement("div");
    name.className = "row-name";
    name.textContent = item.name;
    li.append(thumb, name);
    li.addEventListener("click", () => state.bridge.play(item.path));
    frag.appendChild(li);
    state.rowsByPath.set(item.path, li);
    state.thumbsByPath.set(item.path, img);
    thumbObserver.observe(img);
  }
  list.appendChild(frag);
}

function setThumbnail(path, url) {
  const img = state.thumbsByPath.get(path);
  if (!img || !url) return;
  img.addEventListener("load", () => img.classList.add("is-loaded"), { once: true });
  img.src = url;
}

function markPlaying(path) {
  state.playing = path;
  if (state.activeRow) state.activeRow.classList.remove("is-playing");
  const row = state.rowsByPath.get(path);
  state.activeRow = row || null;
  if (row) {
    row.classList.add("is-playing");
    row.scrollIntoView({ block: "nearest" });
  }
}

/* ── stage geometry ───────────────────────────────────────── */
// #stage is empty on purpose: mpv is a native widget positioned to exactly
// cover it, and the web view is masked to a hole there (see app.py) so mouse
// input reaches mpv -- and therefore uosc -- directly instead of being
// swallowed by this transparent page sitting in front of it.
function reportStageGeometry() {
  const rect = $("stage").getBoundingClientRect();
  state.bridge.stageGeometryChanged(
    Math.round(rect.left),
    Math.round(rect.top),
    Math.round(rect.width),
    Math.round(rect.height)
  );
}

/* ── window chrome ────────────────────────────────────────── */
function setupChrome() {
  $("titlebar").addEventListener("mousedown", (event) => {
    if (event.target.closest(".winbtn")) return;
    if (event.button === 0) state.bridge.startWindowDrag();
  });
  $("titlebar").addEventListener("dblclick", (event) => {
    if (!event.target.closest(".winbtn")) state.bridge.toggleMaximize();
  });
  $("btnMin").addEventListener("click", () => state.bridge.minimizeWindow());
  $("btnMax").addEventListener("click", () => state.bridge.toggleMaximize());
  $("btnClose").addEventListener("click", () => state.bridge.closeWindow());
  $("btnOpenFolder").addEventListener("click", () => state.bridge.openFolder());
  $("btnOpenFile").addEventListener("click", () => state.bridge.openFile());
}

function setupDropTarget() {
  const app = document.querySelector(".app");
  let depth = 0;

  const clear = () => {
    depth = 0;
    app.classList.remove("is-dropping");
  };

  document.addEventListener("dragenter", (event) => {
    event.preventDefault();
    depth += 1;
    app.classList.add("is-dropping");
  });
  document.addEventListener("dragover", (event) => event.preventDefault());
  document.addEventListener("dragleave", (event) => {
    event.preventDefault();
    depth -= 1;
    if (depth <= 0) clear();
  });
  document.addEventListener("drop", (event) => {
    event.preventDefault();
    clear();
    // QWebEngine exposes dropped files as a uri-list; File objects carry no path.
    const raw = event.dataTransfer.getData("text/uri-list") || event.dataTransfer.getData("text/plain");
    const uris = raw
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"));
    if (uris.length) state.bridge.openDropped(uris);
  });
}

function connectBridge(bridge) {
  state.bridge = bridge;

  bridge.folderOpened.connect((name, items) => {
    $("folderName").textContent = name || "尚未開啟資料夾";
    state.items = items;
    renderPlaylist(items);
    if (state.playing) markPlaying(state.playing);
  });

  bridge.thumbnailReady.connect(setThumbnail);
  bridge.nowPlaying.connect(markPlaying);
  bridge.titleChanged.connect((title) => ($("nowTitle").textContent = title || ""));

  bridge.fullscreenChanged.connect((on) => {
    $("sidebar").classList.toggle("is-hidden", on);
    $("titlebar").classList.toggle("is-hidden", on);
    requestAnimationFrame(reportStageGeometry);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupChrome();
  setupDropTarget();

  new QWebChannel(qt.webChannelTransport, (channel) => {
    connectBridge(channel.objects.bridge);
    reportStageGeometry();
  });

  new ResizeObserver(reportStageGeometry).observe($("stage"));
  window.addEventListener("resize", reportStageGeometry);
});
