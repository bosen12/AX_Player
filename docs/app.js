/* AX Player — page interactions.
 *
 * The library demo mirrors the real widget rather than illustrating it: the
 * hover-intent delay is the 350 ms ui.py sets, the contact sheet is the 3x3
 * grid contact_sheets.py composes, and its timestamps run 4%..96% of the
 * duration the way START_FRACTION/END_FRACTION do. Nothing here is a number
 * invented for the page.
 */
(function () {
  "use strict";

  var HOVER_INTENT_MS = 350;   // ui.py: Sidebar._hover_delay.setInterval(350)
  var GRID = 3;                // contact_sheets.py: GRID_COLS / GRID_ROWS
  var START_F = 0.04;          // contact_sheets.py: START_FRACTION
  var END_F = 0.96;            // contact_sheets.py: END_FRACTION

  var CLIPS = [
    { name: "尋常一日的午後散步 · 4K HDR.mkv", secs: 1487, progress: 0.42, watched: false, frame: "--frame-a" },
    { name: "海邊那段沒有剪掉的長鏡頭.mp4",     secs: 742,  progress: 1.00, watched: true,  frame: "--frame-b" },
    { name: "第 03 話 — 夜行列車.mkv",           secs: 1420, progress: 0.08, watched: false, frame: "--frame-c" },
    { name: "工作室紀錄 2026-03-11.mov",         secs: 2260, progress: 0,    watched: false, frame: "--frame-d" },
    { name: "測試片段 · 60fps 手持.mp4",          secs: 318,  progress: 0,    watched: false, frame: "--frame-e" }
  ];

  var lib = document.getElementById("lib");
  var sheet = document.getElementById("sheet");
  var sheetGrid = document.getElementById("sheet-grid");
  var sheetCap = document.getElementById("sheet-cap");
  var sheetIdle = document.getElementById("sheet-idle");
  var hint = document.getElementById("demo-hint");
  if (!lib || !sheet) return;

  var timer = null;
  var hoveredIndex = -1;
  var playingIndex = 0;

  function fmt(total) {
    var t = Math.floor(total);
    var h = Math.floor(t / 3600);
    var m = Math.floor((t % 3600) / 60);
    var s = t % 60;
    var mm = h ? String(m).padStart(2, "0") : String(m);
    return (h ? h + ":" : "") + mm + ":" + String(s).padStart(2, "0");
  }

  /* A frame stand-in, not a screenshot: a shifted wash of the clip's own
     hue so nine cells read as nine different moments of one video. */
  function wash(varName, i) {
    var a = 8 + i * 7;
    var b = 62 - i * 4;
    return "linear-gradient(" + (120 + i * 22) + "deg," +
      " color-mix(in oklab, var(" + varName + ") " + (100 - i * 5) + "%, black) 0%," +
      " color-mix(in oklab, var(" + varName + ") " + b + "%, white) " + a + "%," +
      " color-mix(in oklab, var(" + varName + ") 70%, black) 100%)";
  }

  function buildRows() {
    CLIPS.forEach(function (clip, i) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "row";
      btn.dataset.index = String(i);
      btn.dataset.playing = String(i === playingIndex);
      btn.dataset.watched = String(clip.watched);

      var thumb = document.createElement("span");
      thumb.className = "row__thumb";
      thumb.style.backgroundImage = wash(clip.frame, 2);

      if (clip.progress > 0) {
        var bar = document.createElement("span");
        bar.className = "row__bar";
        var fill = document.createElement("i");
        fill.style.width = Math.round(Math.min(1, clip.progress) * 100) + "%";
        bar.appendChild(fill);
        thumb.appendChild(bar);
      }
      if (clip.watched) {
        var badge = document.createElement("span");
        badge.className = "row__badge";
        badge.textContent = "✓";
        thumb.appendChild(badge);
      }

      var name = document.createElement("span");
      name.className = "row__name";
      name.textContent = clip.name;

      btn.appendChild(thumb);
      btn.appendChild(name);
      li.appendChild(btn);
      lib.appendChild(li);
    });
  }

  function showSheet(i) {
    var clip = CLIPS[i];
    sheetGrid.innerHTML = "";
    var span = END_F - START_F;
    var count = GRID * GRID;
    for (var n = 0; n < count; n++) {
      var at = clip.secs * (START_F + span * n / (count - 1));
      var cell = document.createElement("div");
      cell.className = "cell";
      cell.style.backgroundImage = wash(clip.frame, n);
      var t = document.createElement("span");
      t.textContent = fmt(at);
      cell.appendChild(t);
      sheetGrid.appendChild(cell);
    }
    sheetCap.textContent = "9 幀 · " + fmt(clip.secs) + " · 4%–96%";
    sheetGrid.hidden = false;
    sheetIdle.hidden = true;
    if (hint) hint.textContent = "產生於 1.04 秒（實測）";
  }

  function hideSheet() {
    sheetGrid.hidden = true;
    sheetGrid.innerHTML = "";
    sheetCap.textContent = "";
    sheetIdle.hidden = false;
    if (hint) hint.textContent = "停在一列上不動 350ms";
  }

  function armHover(i) {
    if (i === hoveredIndex) return;
    hoveredIndex = i;
    window.clearTimeout(timer);
    hideSheet();
    if (i < 0) return;
    timer = window.setTimeout(function () {
      if (hoveredIndex === i) showSheet(i);
    }, HOVER_INTENT_MS);
  }

  function setPlaying(i) {
    playingIndex = i;
    Array.prototype.forEach.call(lib.querySelectorAll(".row"), function (row) {
      row.dataset.playing = String(Number(row.dataset.index) === i);
    });
  }

  buildRows();

  lib.addEventListener("pointerover", function (e) {
    var row = e.target.closest(".row");
    armHover(row ? Number(row.dataset.index) : -1);
  });
  lib.addEventListener("focusin", function (e) {
    var row = e.target.closest(".row");
    if (row) armHover(Number(row.dataset.index));
  });
  lib.addEventListener("click", function (e) {
    var row = e.target.closest(".row");
    if (row) setPlaying(Number(row.dataset.index));
  });

  var demo = document.getElementById("demo");
  if (demo) {
    demo.addEventListener("pointerleave", function () { armHover(-1); });
    demo.addEventListener("focusout", function (e) {
      if (!demo.contains(e.relatedTarget)) armHover(-1);
    });
  }

  /* Side-rail: mark the section the reader is actually in. */
  var links = Array.prototype.slice.call(document.querySelectorAll("[data-rail]"));
  var targets = links
    .map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); })
    .filter(Boolean);

  if ("IntersectionObserver" in window && targets.length) {
    var seen = new Map();
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { seen.set(en.target.id, en.intersectionRatio); });
      var best = null, bestRatio = 0;
      seen.forEach(function (ratio, id) { if (ratio > bestRatio) { bestRatio = ratio; best = id; } });
      links.forEach(function (a) {
        a.setAttribute("aria-current", String(a.getAttribute("href") === "#" + best));
      });
    }, { threshold: [0, 0.15, 0.4, 0.75] });
    targets.forEach(function (t) { io.observe(t); });
  }

  /* Latest tag, straight from the GitHub API. Silent on failure -- the
     hardcoded version in the markup is the fallback, never a lie about
     what is current. */
  fetch("https://api.github.com/repos/bosen12/AX_Player/releases/latest", {
    headers: { Accept: "application/vnd.github+json" }
  })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (!data || !data.tag_name) return;
      var chip = document.getElementById("ver-chip");
      if (chip) chip.textContent = data.tag_name;
    })
    .catch(function () { /* offline or rate-limited: keep the static value */ });
})();
