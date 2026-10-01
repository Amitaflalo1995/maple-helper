/* Maple Helper website: progressive enhancement only. Everything works without this file. */
(function () {
  "use strict";
  var root = document.documentElement;
  root.classList.remove("no-js");
  root.classList.add("js");

  /* ---------- which computer is this? ---------- */
  function detectOS() {
    var ua = navigator.userAgent || "";
    var platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
    if (/android|iphone|ipad|ipod/i.test(ua) || (/Mac/.test(platform) && navigator.maxTouchPoints > 1)) return "mobile";
    if (/win/i.test(platform) || /Windows/.test(ua)) return "windows";
    if (/mac/i.test(platform) || /Mac OS X/.test(ua)) return "mac";
    return "other";
  }
  var os = detectOS();
  if (os === "mobile") root.classList.add("is-mobile");

  /* The page ships with Windows as the primary button. On a Mac, swap the emphasis and order. */
  if (os === "mac") {
    document.querySelectorAll(".dl").forEach(function (group) {
      var win = group.querySelector("[data-os=windows]");
      var mac = group.querySelector("[data-os=mac]");
      if (!win || !mac) return;
      win.classList.add("secondary");
      mac.classList.remove("secondary");
      group.insertBefore(mac, win);
    });
  }

  /* ---------- install tabs (Windows / macOS) ---------- */
  document.querySelectorAll(".tabs").forEach(function (box) {
    var tabs = Array.prototype.slice.call(box.querySelectorAll("[role=tab]"));
    function select(tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
        document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      });
      if (focus) tab.focus();
    }
    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () { select(tab, false); });
      tab.addEventListener("keydown", function (e) {
        var rtl = getComputedStyle(box).direction === "rtl";
        var next = { ArrowRight: rtl ? -1 : 1, ArrowLeft: rtl ? 1 : -1, Home: -i, End: tabs.length - 1 - i }[e.key];
        if (next === undefined) return;
        e.preventDefault();
        select(tabs[(i + next + tabs.length) % tabs.length], true);
      });
    });
    if (os === "mac") {
      var macTab = box.querySelector("[data-os=mac]");
      if (macTab) select(macTab, false);
    }
  });

  /* ---------- latest version number (nice to have; silent on failure) ----------
     Cached for an hour per browser so repeat visits don't spend the GitHub API's 60/hour limit. */
  var slot = document.querySelectorAll("[data-version]");
  function showVersion(v) {
    slot.forEach(function (el) {
      el.querySelector("bdi").textContent = v;
      el.hidden = false;
    });
  }
  if (slot.length) {
    var KEY = "mh-latest-version", cached = null;
    try { cached = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { cached = null; }
    if (cached && cached.v && Date.now() - cached.t < 3600 * 1000) {
      showVersion(cached.v);
    } else if (window.fetch) {
      fetch("https://api.github.com/repos/Amitaflalo1995/maple-helper/releases/latest", { headers: { Accept: "application/vnd.github+json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (rel) {
          if (!rel || !rel.tag_name) return;
          var v = String(rel.tag_name).replace(/^v/, "");
          showVersion(v);
          try { localStorage.setItem(KEY, JSON.stringify({ v: v, t: Date.now() })); } catch (e) { /* storage blocked */ }
        })
        .catch(function () {});
    }
  }

  /* ---------- gentle reveal on scroll ---------- */
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var items = document.querySelectorAll(".reveal");
  if (!reduce && "IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    items.forEach(function (el) { io.observe(el); });
  } else {
    items.forEach(function (el) { el.classList.add("in"); });
  }
})();
