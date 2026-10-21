// Shared filter/feed rules are exported for the small dependency-free Node tests.
(function (root) {
  "use strict";
  function matches(row, filters) {
    var geo = row.geo || {};
    if (geo.status !== "ok" || geo.coast_km > filters.max_coast_km ||
        geo.airport_drive_minutes > filters.max_airport_minutes) return false;
    if (filters.price_cap_yen != null &&
        (["sale", "both"].indexOf(row.deal) < 0 || row.price == null ||
         row.price > filters.price_cap_yen)) return false;
    return true;
  }
  function fresh(rows, now) {
    var end = new Date(now).getTime();
    return rows.filter(function (r) {
      // Require a timezone, like the Python exporter. Invalid/future times stay out.
      var stamp = r.first_seen_at || "";
      if (!/(Z|[+-]\d{2}:\d{2})$/.test(stamp)) return false;
      var time = new Date(stamp).getTime();
      return time >= end - 86400000 && time <= end;
    }).sort(function (a, b) { return new Date(b.first_seen_at) - new Date(a.first_seen_at); });
  }
  function xml(value) {
    return String(value).replace(/[<>&"']/g, function (c) {
      return {"<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;"}[c];
    });
  }
  function rss(rows, filters, now, notice) {
    return '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>' +
      '<title>Coastal Kansai/Shikoku akiya</title><link>' + xml(root.location ? root.location.href : "https://example.invalid/coastal/") + '</link>' +
      '<description>' + xml(JSON.stringify(filters) + ". " + notice) + '</description>' +
      '<lastBuildDate>' + xml(new Date(now).toUTCString()) + '</lastBuildDate>' +
      rows.map(function (r) {
        return '<item><title>' + xml(r.muni + " — " + r.no) + '</title><link>' + xml(r.source_url) +
          '</link><guid isPermaLink="false">' + xml(r.id) + '</guid><pubDate>' +
          xml(new Date(r.first_seen_at).toUTCString()) + '</pubDate></item>';
      }).join("") + '</channel></rss>';
  }
  var api = {matches: matches, fresh: fresh, rss: rss};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;
  var form = document.querySelector("[data-coastal-form]");
  if (!form) return;
  var list = document.querySelector("[data-coastal-results]");
  var status = document.querySelector("[data-coastal-status]");
  var more = document.querySelector("[data-coastal-more]");
  var jsonButton = document.querySelector("[data-coastal-json]");
  var rssButton = document.querySelector("[data-coastal-rss]");
  var data, filters, hits = [], shown = 0;
  function append() {
    hits.slice(shown, shown + 30).forEach(function (r) {
      var li = document.createElement("li");
      li.className = "card";
      var price = document.createElement("div");
      price.className = "card-price";
      price.textContent = r.price_text;
      var title = document.createElement("div");
      title.className = "card-title";
      var link = document.createElement("a");
      link.href = r.url;
      link.textContent = r.muni + " · " + r.no;
      title.appendChild(link);
      var facts = document.createElement("p");
      facts.textContent = "海岸 約" + r.geo.coast_km.toFixed(1) + "km · " + r.geo.airport_iata +
        " 推定" + r.geo.airport_drive_minutes + "分";
      var source = document.createElement("a");
      source.href = r.source_url;
      source.textContent = "自治体の一次情報";
      li.append(price, title, facts, source);
      list.appendChild(li);
    });
    shown += 30;
    more.hidden = shown >= hits.length;
  }
  function render() {
    if (!data || !form.reportValidity()) return;
    filters = {
      max_coast_km: Number(form.elements.coast.value),
      max_airport_minutes: Number(form.elements.airport.value),
      price_cap_yen: form.elements.price.value === "" ? null : Number(form.elements.price.value)
    };
    hits = data.rows.filter(function (r) { return matches(r, filters); });
    var known = data.rows.filter(function (r) { return r.geo.status === "ok"; }).length;
    status.textContent = hits.length + " 件が該当。対象 " + data.rows.length + " 件 · 位置確認済み " +
      known + " 件 · 位置不明 " + (data.rows.length - known) + " 件。新着 " +
      fresh(hits, data.generated_at).length + " 件（24時間）。";
    list.replaceChildren();
    shown = 0;
    append();
    var params = new URLSearchParams();
    params.set("coast", form.elements.coast.value);
    params.set("airport", form.elements.airport.value);
    if (filters.price_cap_yen != null) params.set("price", String(filters.price_cap_yen));
    root.history.replaceState(null, "", "?" + params.toString());
  }
  function download(kind) {
    if (!data || !form.reportValidity()) return;
    render();
    var rows = fresh(hits, data.generated_at);
    var value = kind === "rss" ? rss(rows, filters, data.generated_at, data.notice) : JSON.stringify({
      generated_at: data.generated_at, window_hours: 24, filters: filters, notice: data.notice,
      listings: rows
    }, null, 2);
    var url = URL.createObjectURL(new Blob([value], {type: kind === "rss" ? "application/rss+xml" : "application/json"}));
    var link = document.createElement("a");
    link.href = url;
    link.download = "coastal-new." + kind;
    link.click();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  form.addEventListener("submit", function (event) { event.preventDefault(); render(); });
  more.addEventListener("click", append);
  jsonButton.addEventListener("click", function () { download("json"); });
  rssButton.addEventListener("click", function () { download("rss"); });
  var params = new URLSearchParams(root.location.search);
  ["coast", "airport", "price"].forEach(function (key) {
    var value = params.get(key);
    if (value !== null && value !== "" && Number.isFinite(Number(value)) && Number(value) >= 0)
      form.elements[key].value = value;
  });
  fetch("/search/coastal.json", {cache: "no-cache"}).then(function (response) {
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }).then(function (value) {
    data = value;
    jsonButton.disabled = rssButton.disabled = false;
    render();
  }).catch(function () {
    status.textContent = "位置情報を読み込めませんでした。再読み込みしてください。初期条件の結果は下に表示しています。";
  });
})(typeof window !== "undefined" ? window : globalThis);
