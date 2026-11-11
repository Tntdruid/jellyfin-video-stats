const PALETTE = ["#e5484d", "#f59e0b", "#3b82f6", "#14b8a6", "#a855f7", "#ec4899", "#22c55e", "#6366f1", "#94a3b8"];
const KIND_COLORS = { movie: "#f59e0b", series: "#e5484d", video: "#3b82f6" };
const METHOD_COLORS = { DirectPlay: "#22c55e", DirectStream: "#14b8a6", Transcode: "#e5484d", Ukendt: "#94a3b8" };
const DAYS = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"];
const ICONS = { clock: "🕒", star: "⭐", play: "▶️", binge: "🍿", repeat: "🔁", pause: "⏸️", stop: "⏹️", movie: "🎬", cpu: "⚙️", moon: "🌙" };
const LANGS = { dan: "Dansk", eng: "Engelsk", swe: "Svensk", nor: "Norsk", nob: "Norsk", deu: "Tysk", ger: "Tysk", fra: "Fransk",
  fre: "Fransk", spa: "Spansk", ita: "Italiensk", jpn: "Japansk", kor: "Koreansk", und: "Ukendt", Ingen: "Ingen" };
const REASONS = {
  VideoCodecNotSupported: "Videocodec understøttes ikke", AudioCodecNotSupported: "Lydcodec understøttes ikke",
  ContainerNotSupported: "Containerformat understøttes ikke", ContainerBitrateExceedsLimit: "Bitrate over grænsen",
  SubtitleCodecNotSupported: "Undertekster skal brændes ind", VideoResolutionNotSupported: "Opløsning understøttes ikke",
  AudioChannelsNotSupported: "Antal lydkanaler understøttes ikke", VideoRangeTypeNotSupported: "HDR understøttes ikke",
  VideoBitDepthNotSupported: "Bitdybde understøttes ikke", AudioBitrateNotSupported: "Lyd-bitrate understøttes ikke",
};

const state = { range: "30", user: "", bucket: null, meta: null };
const charts = {};

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const fmt = (n, d = 0) => Number(n || 0).toLocaleString("da-DK", { maximumFractionDigits: d });
const hrs = (minutes, d = 1) => `${fmt(minutes / 60, d)} t`;
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const lang = (k) => LANGS[k] || k;
const days = (n) => `${n} ${n === 1 ? "dag" : "dage"}`;

function rangeParams() {
  const now = Math.floor(Date.now() / 1000);
  let start = 0;
  if (state.range === "year") start = Math.floor(new Date(new Date().getFullYear(), 0, 1) / 1000);
  else if (state.range !== "all") start = now - Number(state.range) * 86400;
  const p = new URLSearchParams({ start, end: now + 60 });
  if (state.user) p.set("user", state.user);
  return p;
}

function autoBucket() {
  if (state.range === "7" || state.range === "30") return "day";
  if (state.range === "90") return "week";
  return "month";
}

async function api(path, extra = {}) {
  const p = rangeParams();
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  const r = await fetch(`api/${path}?${p}`);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function chart(id) {
  const el = document.getElementById(id);
  if (charts[id] && charts[id].getDom() !== el) charts[id].dispose();  // container was re-rendered
  if (!charts[id] || charts[id].isDisposed()) charts[id] = echarts.init(el, null, { renderer: "canvas" });
  return charts[id];
}

function baseOption() {
  const text = css("--muted"), line = css("--line");
  return {
    animation: !state.quiet,  // no replayed animations on background refreshes
    textStyle: { color: text, fontFamily: "inherit" },
    grid: { left: 40, right: 12, top: 30, bottom: 30, containLabel: false },
    tooltip: { trigger: "axis", backgroundColor: css("--card"), borderColor: line, textStyle: { color: css("--text") } },
    legend: { top: 0, textStyle: { color: text }, type: "scroll", itemWidth: 10, itemHeight: 10 },
    xAxis: { type: "category", axisLine: { lineStyle: { color: line } }, axisTick: { show: false } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: line } } },
  };
}

function pieOption(data) {
  return {
    animation: !state.quiet,
    tooltip: { trigger: "item", backgroundColor: css("--card"), borderColor: css("--line"), textStyle: { color: css("--text") } },
    legend: { bottom: 0, textStyle: { color: css("--muted") }, itemWidth: 10, itemHeight: 10, type: "scroll" },
    series: [{
      type: "pie", radius: ["45%", "72%"], center: ["50%", "45%"], itemStyle: { borderColor: css("--card"), borderWidth: 2 },
      label: { color: css("--text"), formatter: "{d} %" }, data,
    }],
  };
}

function fmtLabel(iso, bucket) {
  const d = new Date(iso + "T00:00:00");
  if (bucket === "month") return d.toLocaleDateString("da-DK", { month: "short", year: "2-digit" });
  return d.toLocaleDateString("da-DK", { day: "numeric", month: "short" });
}

const seriesLink = (id) => `#/series/${encodeURIComponent(id)}`;
const movieLink = (id) => `#/movie/${encodeURIComponent(id)}`;
const personLink = (name) => `#/person/${encodeURIComponent(name)}`;
const channelLink = (id) => `#/channel/${encodeURIComponent(id)}`;
const titleLink = (kind, id) => ({ series: seriesLink, video: channelLink }[kind] || movieLink)(id);

// A missing image first falls back to a second one (a channel without artwork shows one of its videos),
// then to the first letter of the name.
function cover(imageId, name, cls = "img", fallbackId = null) {
  const letter = esc((name || "?")[0]);
  if (!imageId) imageId = fallbackId, fallbackId = null;
  return imageId
    ? `<img class="${cls}" loading="lazy" src="api/image/${esc(imageId)}" alt="" data-letter="${letter}"${fallbackId ? ` data-fallback="${esc(fallbackId)}"` : ""} onerror="imageFailed(this)">`
    : `<div class="${cls}">${letter}</div>`;
}

function imageFailed(img) {
  if (img.dataset.fallback) {
    img.src = `api/image/${img.dataset.fallback}`;
    delete img.dataset.fallback;
    return;
  }
  const div = document.createElement("div");
  div.className = img.className;
  div.textContent = img.dataset.letter;
  img.replaceWith(div);
}

// --- renderers ---------------------------------------------------------------

function delta(cur, prev, invert = false) {
  if (!prev) return `<div class="delta">&nbsp;</div>`;
  const pct = ((cur - prev) / prev) * 100;
  const good = invert ? pct < 0 : pct > 0;
  return `<div class="delta ${Math.abs(pct) < 1 ? "" : good ? "up" : "down"}">${pct > 0 ? "▲" : "▼"} ${fmt(Math.abs(pct))} % vs. forrige periode</div>`;
}
const kpi = (l, v, d = `<div class="delta">&nbsp;</div>`) => `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div>${d}</div>`;
const note = (t) => `<div class="delta">${t}</div>`;

function renderKpis(s) {
  const p = s.previous;
  $("#kpis").innerHTML = [
    kpi("Seetid", hrs(s.minutes, 0), delta(s.minutes, p.minutes)),
    kpi("Film", fmt(s.movies), note(`${hrs(s.movie_minutes, 0)} filmtid`)),
    kpi("Afsnit", fmt(s.episodes), note(`fra ${fmt(s.series)} serier`)),
    s.videos || p.videos
      ? kpi("Videoer", fmt(s.videos), note(`fra ${fmt(s.channels)} kanaler · ${hrs(s.video_minutes, 0)}`))
      : kpi("Nye serier", fmt(s.new_series), note("påbegyndt i perioden")),
    kpi("Set færdig", `${fmt(s.completion_rate * 100)} %`, delta(s.completion_rate, p.completion_rate)),
    kpi("Største binge", s.binge ? `${s.binge.n} afsnit` : "–", note(s.binge ? esc(s.binge.name) : "&nbsp;")),
    kpi("Streak", days(s.streak_current), note(`rekord: ${days(s.streak_best)}`)),
    kpi("Transcoding", `${fmt(s.transcode_rate * 100)} %`, delta(s.transcode_rate, p.transcode_rate, true)),
  ].join("");
}

function renderTimeline(t, bucket) {
  const opt = baseOption();
  opt.xAxis.data = t.labels.map((l) => fmtLabel(l, bucket));
  opt.tooltip.valueFormatter = (v) => `${fmt(v, 1)} t`;
  opt.series = kindBars(t, "t");
  chart("timeline").setOption(opt, true);
}

// Stacked hours for series, movies and (only when there are any) videos.
function kindBars(t, stack) {
  const kinds = [["Serier", "series"], ["Film", "movie"], ["Videoer", "video"]]
    .filter(([, k]) => k !== "video" || t.video_minutes.some((m) => m > 0));
  return kinds.map(([name, k], i) => ({
    name, type: "bar", stack, data: t[`${k}_minutes`].map((m) => +(m / 60).toFixed(1)),
    itemStyle: { color: KIND_COLORS[k], borderRadius: i === kinds.length - 1 ? [3, 3, 0, 0] : 0 },
  }));
}

function renderTop(id, rows, linkFor = null, imgCls = "img") {
  const el = document.getElementById(id);
  if (!rows.length) { el.innerHTML = `<div class="empty">Ingen data endnu</div>`; return; }
  const max = Math.max(...rows.map((r) => r.minutes || 0));
  el.innerHTML = rows.map((r) => {
    const tag = linkFor ? `a class="row" href="${esc(linkFor(r))}"` : `div class="row"`;
    const count = r.minutes != null ? `${hrs(r.minutes)}<br>${fmt(r.plays)} ×` : "";
    return `
    <li>
      <${tag}>
        ${cover(r.image_id, r.name, imgCls, r.fallback_image_id)}
        <div class="meta">
          <div class="name" title="${esc(r.name)}">${esc(r.name)}</div>
          ${r.sub ? `<div class="sub">${esc(r.sub)}</div>` : ""}
          ${max && r.minutes != null ? `<div class="bar" style="width:${(r.minutes / max) * 100}%"></div>` : ""}
        </div>
        <div class="count">${count}</div>
      </${linkFor ? "a" : "div"}>
    </li>`;
  }).join("");
}

function renderShareArea(id, data, bucket) {
  const opt = baseOption();
  const totals = data.labels.map((_, i) => data.series.reduce((s, x) => s + x.data[i], 0));
  // an area needs at least two points to have any width; with fewer buckets draw stacked bars
  const bars = data.labels.length < 3;
  opt.xAxis.data = data.labels.map((l) => fmtLabel(l, bucket));
  opt.xAxis.boundaryGap = bars;
  opt.yAxis.max = 100;
  opt.yAxis.axisLabel = { formatter: "{value} %" };
  opt.tooltip.valueFormatter = (v) => `${fmt(v)} %`;
  opt.series = data.series.map((s, i) => ({
    name: s.name,
    stack: "share",
    ...(bars
      ? { type: "bar", barMaxWidth: 120 }
      : { type: "line", areaStyle: { opacity: 0.85 }, symbol: "none", smooth: 0.3, lineStyle: { width: 0 } }),
    itemStyle: { color: PALETTE[i % PALETTE.length] },
    data: s.data.map((v, j) => (totals[j] ? (v / totals[j]) * 100 : 0)),
  }));
  if (!data.series.length) opt.title = { text: "Ingen data endnu", left: "center", top: "middle", textStyle: { color: css("--muted"), fontSize: 13 } };
  chart(id).setOption(opt, true);
}

function renderHeatmap(cells) {
  const max = Math.max(1, ...cells.map((c) => c[2]));
  chart("heatmap").setOption({
    animation: !state.quiet,
    textStyle: { color: css("--muted") },
    tooltip: { formatter: (p) => `${DAYS[p.value[1]]} kl. ${String(p.value[0]).padStart(2, "0")}: ${p.value[2]} afspilninger`,
               backgroundColor: css("--card"), borderColor: css("--line"), textStyle: { color: css("--text") } },
    grid: { left: 40, right: 12, top: 10, bottom: 50 },
    xAxis: { type: "category", data: [...Array(24).keys()].map((h) => String(h).padStart(2, "0")), splitArea: { show: false },
             axisLine: { lineStyle: { color: css("--line") } }, axisTick: { show: false } },
    yAxis: { type: "category", data: DAYS, inverse: true, axisLine: { show: false }, axisTick: { show: false } },
    visualMap: { min: 0, max, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemHeight: 120,
                 inRange: { color: [css("--line"), css("--accent")] }, textStyle: { color: css("--muted") } },
    series: [{ type: "heatmap", data: cells, itemStyle: { borderColor: css("--card"), borderWidth: 2, borderRadius: 3 } }],
  }, true);
}

function renderInsights(items) {
  $("#insights").innerHTML = items.length
    ? items.map((i) => `<li><span class="ico">${ICONS[i.icon] || "•"}</span><span>${esc(i.text)}</span></li>`).join("")
    : `<li class="empty">Indsigter dukker op, når der er set lidt mere.</li>`;
}

const methodTag = (m) => (m === "Transcode" ? `<span class="tag warn" title="Afspillet med transcoding">transcode</span>` : "");

function renderRecent(rows) {
  $("#recent").innerHTML = rows.length ? rows.map((r) => {
    const t = new Date(r.started_at * 1000);
    const pct = r.progress != null ? Math.round(r.progress * 100) : null;
    const title = r.kind === "series"
      ? `<a class="plain" href="${esc(seriesLink(r.title_id))}"><strong>${esc(r.title)}</strong></a> <span class="muted">${esc(r.episode)} · ${esc(r.name)}</span>`
      : r.kind === "video"
        ? `<strong>${esc(r.name || "Ukendt")}</strong> <span class="muted">· <a class="plain" href="${esc(channelLink(r.title_id))}">${esc(r.title)}</a></span>`
        : `<a class="plain" href="${esc(movieLink(r.item_id))}"><strong>${esc(r.name || "Ukendt")}</strong></a>`;
    return `<tr>
      <td class="muted">${t.toLocaleDateString("da-DK", { day: "numeric", month: "short" })} ${t.toLocaleTimeString("da-DK", { hour: "2-digit", minute: "2-digit" })}</td>
      <td>${title}</td>
      <td>${r.counted ? "" : `<span class="tag">kun kigget</span>`} ${methodTag(r.play_method)}</td>
      <td class="muted">${pct != null ? `<span class="pbar"><span style="width:${pct}%"></span></span> ${pct} %` : ""}</td>
      <td class="muted">${esc(r.user_name || "")}</td>
      <td class="muted">${esc(r.device || "")}</td>
    </tr>`;
  }).join("") : `<tr><td class="empty">Ingen afspilninger endnu</td></tr>`;
}

const epLabel = (n) => (n.season_number != null && n.episode_number != null
  ? `S${String(n.season_number).padStart(2, "0")}E${String(n.episode_number).padStart(2, "0")}` : "");
const resLabel = (h) => (!h ? "" : h >= 1800 ? "4K" : h >= 1000 ? "1080p" : h >= 700 ? "720p" : "SD");

async function renderNow() {
  try {
    const now = await (await fetch("api/now")).json();
    const el = $("#now");
    el.hidden = !now.length;
    el.innerHTML = now.map((n) => {
      const series = n.type === "Episode", video = n.type === "Video";
      const img = series && n.series_id ? n.series_id : n.item_id;
      const title = series ? `<strong>${esc(n.series_name || "")}</strong> <span class="muted">${epLabel(n)} · ${esc(n.name)}</span>`
        : video ? `<strong>${esc(n.name)}</strong> <span class="muted">· ${esc(n.series_name || "")}</span>`
        : `<strong>${esc(n.name)}</strong>`;
      return `
      <div class="item">
        ${cover(img, n.series_name || n.name, video ? "thumb" : "poster")}
        <div style="flex:1;min-width:0">
          <div class="live">${n.paused ? "PAUSE" : "AFSPILLES NU"} · ${esc(n.user_name || "")} · ${esc(n.device || "")}</div>
          <div class="ellipsis">${title}</div>
          <div class="muted small">${[resLabel(n.height), n.play_method === "Transcode" ? "transcoding" : n.play_method ? "direkte" : ""].filter(Boolean).join(" · ")}</div>
          ${n.duration ? `<progress max="${n.duration}" value="${n.position}"></progress>` : ""}
        </div>
      </div>`;
    }).join("");
  } catch { /* ignore */ }
}

function renderStatus(meta) {
  const el = $("#status");
  const c = meta.collector;
  if (!c.enabled) { el.className = "status"; el.title = "Opsamling slået fra (mangler Jellyfin URL/API-nøgle)"; return; }
  if (c.last_error) { el.className = "status err"; el.title = `Fejl: ${c.last_error}`; return; }
  const age = c.last_poll ? Date.now() / 1000 - c.last_poll : 0;
  if (age > Math.max(60, c.poll_interval * 3)) {
    el.className = "status err";
    el.title = `Opsamlingen er gået i stå – sidste tjek af Jellyfin for ${Math.round(age / 60)} min. siden. Genstart add-on'et.`;
    return;
  }
  el.className = "status ok";
  el.title = c.last_poll ? `Forbundet til Jellyfin – sidst tjekket ${new Date(c.last_poll * 1000).toLocaleTimeString("da-DK")}` : "Starter…";
}

// --- main -----------------------------------------------------------------

async function loadMeta() {
  state.meta = await (await fetch("api/meta")).json();
  renderStatus(state.meta);
  const me = state.meta.me?.jellyfin_user;
  // first load: start on the viewer's own stats when their HA user matches a Jellyfin user
  if (state.user === "" && me && !state.userChosen) state.user = me;
  const sel = $("#user");
  sel.innerHTML = `<option value="">Alle brugere</option>` +
    state.meta.users.map((u) => `<option value="${esc(u.id)}">${esc(u.name || u.id)}${u.id === me ? " (dig)" : ""}</option>`).join("");
  sel.value = state.user;
}

async function loadDashboard() {
  const bucket = state.bucket || autoBucket();
  const trend = autoBucket() === "day" && state.range === "30" ? "week" : autoBucket();
  document.querySelectorAll("#bucket button").forEach((b) => b.classList.toggle("on", b.dataset.bucket === bucket));

  const [summary, timeline, series, movies, people, channels, videos, genres, heat, insights, recent] = await Promise.all([
    api("summary"), api("timeline", { bucket }),
    api("top", { kind: "series" }), api("top", { kind: "movies" }), api("top", { kind: "people" }),
    api("top", { kind: "channels" }), api("top", { kind: "videos" }),
    api("genres", { bucket: trend }), api("heatmap"), api("insights"), api("recent"),
  ]);
  api("progress").then(renderProgress).catch(console.error);
  $("#video-row").hidden = !channels.length;
  renderTop("top-channels", channels, (r) => channelLink(r.key), "face");
  renderTop("top-videos", videos, (r) => channelLink(r.channel_id), "thumb");
  renderKpis(summary);
  renderTimeline(timeline, bucket);
  renderTop("top-series", series, (r) => seriesLink(r.key), "poster");
  renderTop("top-movies", movies, (r) => movieLink(r.key), "poster");
  renderTop("top-people", people, (r) => personLink(r.key), "face");
  renderShareArea("genres", genres, trend);
  renderHeatmap(heat);
  renderInsights(insights);
  renderRecent(recent);
}

// --- series progress ------------------------------------------------------------

const shortDate = (t) => new Date(t * 1000).toLocaleDateString("da-DK", { day: "numeric", month: "short", year: "numeric" });
const meter = (share) => `<div class="meter"><div style="width:${Math.round(share * 100)}%"></div></div>`;

function renderProgress(p) {
  $("#progress-row").hidden = !p.continue.length && !p.finished.length;
  const row = (r, body) => `
    <li><a class="row" href="${esc(seriesLink(r.key))}">
      ${cover(r.image_id, r.name, "poster")}
      <div class="meta"><div class="name">${esc(r.name)}</div>${body}</div>
    </a></li>`;
  $("#continue").innerHTML = p.continue.length ? p.continue.slice(0, 8).map((r) => row(r, `
      <div class="sub">${r.next ? `Næste: ${esc(r.next.episode)} · ${esc(r.next.name)}` : "&nbsp;"}</div>
      ${meter(r.share)}
      <div class="sub">${fmt(r.seen)} af ${fmt(r.total)} afsnit · ${fmt(r.total - r.seen)} tilbage (${hrs(r.remaining_minutes)})</div>`)).join("")
    : `<div class="empty">Ingen serier i gang</div>`;
  $("#finished").innerHTML = p.finished.length ? p.finished.slice(0, 8).map((r) => row(r, `
      <div class="sub">${fmt(r.total)} afsnit${r.last ? ` · sidste set ${shortDate(r.last)}` : ""}</div>
      <div class="sub">${r.status === "Continuing" ? "⏳ Ajour – venter på nye afsnit" : "✅ Hele serien set"}</div>`)).join("")
    : `<div class="empty">Ingen serier set helt færdige endnu</div>`;
  $("#finished-hint").textContent = p.finished.length ? `${fmt(p.finished.length)} serier` : "";
}

function renderSeriesProgress(p) {
  const el = $("#detail-progress");
  el.hidden = !p;
  if (!p) return;
  const state = p.seen >= p.total
    ? (p.status === "Continuing" ? "Du er ajour – serien fortsætter" : "Du har set hele serien")
    : p.next ? `Næste afsnit: <strong>${esc(p.next.episode)} · ${esc(p.next.name)}</strong>` : "";
  el.innerHTML = `
    <div class="card-head"><h2>Fremdrift</h2><span class="hint">uanset periode · tæller også afsnit markeret som set i Jellyfin</span></div>
    <div class="progress-head">
      <div class="pct">${fmt(p.share * 100)} %</div>
      <div style="flex:1;min-width:220px">
        <div>${fmt(p.seen)} af ${fmt(p.total)} afsnit set${p.seen < p.total ? ` · ${hrs(p.remaining_minutes)} tilbage` : ""}</div>
        ${meter(p.share)}
        <div class="sub" style="margin-top:6px">${state}</div>
      </div>
    </div>
    <div class="seasons">${p.seasons.map((s) => `
      <div class="season"><span>Sæson ${s.season ?? "?"}</span>${meter(s.seen / s.total)}<span class="muted">${s.seen}/${s.total}</span></div>`).join("")}
    </div>`;
}

// --- tech page ----------------------------------------------------------------

async function loadTech() {
  const [t, s] = await Promise.all([api("tech"), api("summary")]);
  const total = t.methods.reduce((a, m) => a + m.n, 0) || 1;
  const direct = t.methods.filter((m) => m.k !== "Transcode").reduce((a, m) => a + m.n, 0);
  const top = (rows) => rows[0] ? `${lang(rows[0].k)}` : "–";
  $("#tech-kpis").innerHTML = [
    kpi("Direkte afspilning", `${fmt((direct / total) * 100)} %`, note("uden transcoding")),
    kpi("Transcoding", `${fmt(s.transcode_rate * 100)} %`, delta(s.transcode_rate, s.previous.transcode_rate, true)),
    kpi("Undertekster", `${fmt(s.subtitle_rate * 100)} %`, note("af afspilningerne")),
    kpi("Mest brugte lyd", top(t.audio)),
    kpi("Typisk opløsning", top(t.resolutions)),
  ].join("");

  chart("tech-methods").setOption(pieOption(t.methods.map((m) => ({ name: m.label, value: m.n, itemStyle: { color: METHOD_COLORS[m.k] } }))), true);

  const opt = baseOption();
  opt.legend.show = false;
  opt.grid.left = 130;
  opt.xAxis = { type: "value", max: 100, axisLabel: { formatter: "{value} %" }, splitLine: { lineStyle: { color: css("--line") } } };
  opt.yAxis = { type: "category", inverse: true, data: t.clients.map((c) => c.name), axisLine: { show: false }, axisTick: { show: false } };
  opt.tooltip = { ...opt.tooltip, formatter: (p) => `${esc(p[0].name)}: ${fmt(p[0].value)} % transcodet af ${fmt(t.clients[p[0].dataIndex].n)} afspilninger` };
  opt.series = [{ type: "bar", data: t.clients.map((c) => +(c.transcode * 100).toFixed(1)), barMaxWidth: 18,
    itemStyle: { borderRadius: [0, 3, 3, 0], color: (p) => (p.value >= 30 ? METHOD_COLORS.Transcode : p.value >= 10 ? "#f59e0b" : METHOD_COLORS.DirectPlay) } }];
  chart("tech-clients").setOption(opt, true);

  const maxR = Math.max(1, ...t.reasons.map((r) => r.n));
  $("#tech-reasons").innerHTML = t.reasons.length ? t.reasons.map((r) => `
    <li><div class="lrow"><span>${esc(REASONS[r.k] || r.k)}</span><span class="muted">${fmt(r.n)}</span></div>
      <div class="bar" style="width:${(r.n / maxR) * 100}%"></div></li>`).join("")
    : `<div class="empty">Ingen transcoding i perioden 🎉</div>`;

  chart("tech-res").setOption(pieOption(t.resolutions.map((r, i) => ({ name: r.k, value: r.n, itemStyle: { color: PALETTE[i % PALETTE.length] } }))), true);

  const langList = (title, rows) => {
    const sum = rows.reduce((a, r) => a + r.n, 0) || 1;
    return `<h3>${title}</h3>${rows.map((r) => `<div class="lrow"><span>${esc(lang(r.k))}</span><span class="muted">${fmt((r.n / sum) * 100)} %</span></div>`).join("") || `<div class="muted">–</div>`}`;
  };
  $("#tech-lang").innerHTML = langList("Lyd", t.audio) + langList("Undertekster", t.subtitles);
  renderImport(state.meta);
  renderHa(state.meta);
  if (state.meta.import.running) pollImport();
}

function renderHa(meta) {
  const h = meta.home_assistant;
  const parts = [];
  if (!h.available) parts.push("Ikke forbundet til Home Assistant. Det sker automatisk, når add-on'et kører i Home Assistant.");
  else {
    if (h.last_error) parts.push(`⚠️ ${esc(h.last_error)}`);
    parts.push(h.sensors_enabled
      ? `Sensorer: ${fmt(h.sensors)} opdateres hvert halve minut${h.last_update ? `, senest ${new Date(h.last_update * 1000).toLocaleTimeString("da-DK", { hour: "2-digit", minute: "2-digit" })}` : ""}.`
      : "Sensorer er slået fra (ha_sensors).");
    parts.push(h.notify_enabled
      ? `Besked om nye afsnit sendes via <code>${esc(h.notify_service)}</code> og som eventet <code>jellyfin_video_stats_new_episode</code>.${h.notified ? ` ${fmt(h.notified)} sendt siden start.` : ""}`
      : "Besked om nye afsnit er slået fra (notify_new_episodes).");
  }
  $("#ha-status").innerHTML = parts.map((p) => `<div>${p}</div>`).join("");
  $("#ha-hint").textContent = h.available && !h.last_error ? "forbundet" : "";
  $("#ha-sensors").innerHTML = h.available && h.sensors_enabled ? (h.entities || []).map((e) => `<li><code>${esc(e)}</code></li>`).join("") : "";
}

function renderImport(meta) {
  const i = meta.import;
  const el = $("#import-status"), btn = $("#import-btn");
  btn.hidden = !i.enabled;
  btn.disabled = i.running;
  btn.textContent = i.running ? "Importerer…" : i.total ? "Importér igen" : "Importér historik";
  let text;
  if (!i.enabled) text = "Kræver, at add-on'et er forbundet til Jellyfin.";
  else if (i.running) text = "Henter afspilninger fra Playback Reporting-pluginet…";
  else if (i.error) text = `Importen fejlede: ${esc(i.error)}`;
  else if (i.available === false) text = "Playback Reporting-pluginet er ikke installeret i Jellyfin. Installér det under Kontrolpanel → Plugins, hvis du vil have historik fra før add-on'et.";
  else if (i.total || i.imported != null) {
    const last = i.last_run ? new Date(i.last_run * 1000).toLocaleString("da-DK", { dateStyle: "medium", timeStyle: "short" }) : "";
    text = `${fmt(i.total)} afspilninger er importeret${last ? `, senest ${last}` : ""}.` +
      (i.imported != null ? ` Sidste kørsel tilføjede ${fmt(i.imported)} og sprang ${fmt(i.skipped)} over (allerede registreret eller under 1 minut).` : "") +
      " Det er sikkert at importere igen – dubletter springes over.";
  } else text = "Henter gamle afspilninger fra Jellyfins Playback Reporting-plugin, så statistikken også dækker tiden før add-on'et.";
  el.innerHTML = text;
}

$("#import-btn").addEventListener("click", async () => {
  $("#import-btn").disabled = true;
  await fetch("api/import", { method: "POST" });
  pollImport();
});

// Follow a running import until it is done, then reload the view with the new history. Only one at a time.
async function pollImport() {
  if (state.importPolling) return;
  state.importPolling = true;
  try {
    do {
      await new Promise((r) => setTimeout(r, 1500));
      await loadMeta();
      renderImport(state.meta);
    } while (state.meta.import.running);
  } finally {
    state.importPolling = false;
  }
  refresh();
}

// --- detail pages ---------------------------------------------------------------

const longDate = (t) => new Date(t * 1000).toLocaleDateString("da-DK", { day: "numeric", month: "long", year: "numeric" });
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const WEEKDAY_NAMES = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"];
const KIND_TEXT = {
  series: { rank: "serier", list: "Afsnit", hint: "i rækkefølge" },
  movie: { rank: "film", list: "Medvirkende", hint: "" },
  person: { rank: "skuespillere", list: "Film og serier", hint: "efter seetid" },
  channel: { rank: "kanaler", list: "Videoer", hint: "senest sete først" },
};

async function loadDetail(kind, key) {
  let a;
  try {
    a = await api("detail", { kind, key });
  } catch {
    $("#detail-hero").innerHTML = `<div><h2>Intet set i perioden</h2><div class="sub">Prøv en længere periode, fx "Alt".</div></div>`;
    for (const id of ["detail-kpis", "detail-items", "detail-viewers"]) document.getElementById(id).innerHTML = "";
    chart("detail-months").clear();
    chart("detail-hours").clear();
    return;
  }
  const favDay = a.weekdays.indexOf(Math.max(...a.weekdays));
  const facts = [
    a.year, a.official_rating, a.community_rating ? `★ ${fmt(a.community_rating, 1)}` : null,
    a.duration ? `${Math.floor(a.duration / 3600)} t ${Math.round((a.duration % 3600) / 60)} min` : null,
    (a.studios || []).slice(0, 2).join(", ") || null,
  ].filter(Boolean).map(esc).join(" · ");
  $("#detail-hero").innerHTML = `
    ${cover(a.image_id, a.name, kind === "person" || kind === "channel" ? "cover face" : "cover", a.fallback_image_id)}
    <div style="min-width:0">
      ${a.rank ? `<div class="sub">#${a.rank} blandt dine ${KIND_TEXT[kind].rank} i perioden</div>` : ""}
      <h2>${esc(a.name)}</h2>
      ${facts ? `<div class="sub">${facts}</div>` : ""}
      ${a.first ? `<div class="sub">Første gang set ${longDate(a.first)}</div>` : ""}
      <div class="chips">${a.genres.map((g) => `<span class="chip">${esc(g.name)}</span>`).join("")}</div>
    </div>`;

  $("#detail-kpis").innerHTML = [
    kpi("Seetid", hrs(a.minutes), note(`${fmt(a.share * 100, 1)} % af al seetid`)),
    kind === "series" && kpi("Afsnit set", fmt(a.items), note(`fra ${fmt(a.seasons)} ${a.seasons === 1 ? "sæson" : "sæsoner"}`)),
    kind === "series" && a.latest && kpi("Seneste afsnit", esc(a.latest.episode || a.latest.name), note(esc(a.latest.name))),
    kind === "movie" && kpi("Set", `${fmt(a.days)} ${a.days === 1 ? "gang" : "gange"}`, note(`${fmt(a.completed)} gange helt færdig`)),
    kind === "person" && kpi("Titler", fmt(a.titles), note(`${fmt(a.items)} film/afsnit`)),
    kind === "channel" && kpi("Videoer set", fmt(a.items), note(`${fmt(a.completed)} set færdig`)),
    kpi("Afspilninger", fmt(a.plays)),
    kpi("Dage", fmt(a.days), note("med mindst én afspilning")),
    kpi("Yndlingsdag", capital(WEEKDAY_NAMES[favDay])),
    kpi("Sidst set", new Date(a.last * 1000).toLocaleDateString("da-DK", { day: "numeric", month: "short" })),
  ].filter(Boolean).join("");

  const months = baseOption();
  months.legend.show = false;
  months.xAxis.data = a.months.labels.map((l) => fmtLabel(l, "month"));
  months.tooltip.valueFormatter = (v) => `${fmt(v, 1)} t`;
  months.series = [{ type: "bar", name: "Timer", data: a.months.hours, itemStyle: { color: css("--accent"), borderRadius: [3, 3, 0, 0] } }];
  chart("detail-months").setOption(months, true);

  const hours = baseOption();
  hours.legend.show = false;
  hours.xAxis.data = [...Array(24).keys()].map((h) => String(h).padStart(2, "0"));
  hours.series = [{ type: "bar", name: "Afspilninger", data: a.hours, itemStyle: { color: "#f59e0b", borderRadius: [3, 3, 0, 0] } }];
  chart("detail-hours").setOption(hours, true);

  $("#detail-items-title").textContent = KIND_TEXT[kind].list;
  $("#detail-items-hint").textContent = KIND_TEXT[kind].hint;
  renderSeriesProgress(a.progress);
  if (kind === "series") {
    a.list.forEach((r) => {
      r.name = r.sub ? `${r.sub} · ${r.name}` : r.name;
      r.sub = r.seen === false ? "ikke set" : r.plays == null ? "set (før perioden eller markeret i Jellyfin)"
        : r.completed ? "set færdig" : "set, men ikke færdig";
    });
    renderTop("detail-items", a.list, null, "thumb");
    document.querySelectorAll("#detail-items li").forEach((li, i) => li.classList.toggle("unseen", a.list[i].seen === false));
  } else if (kind === "channel") {
    renderTop("detail-items", a.list, null, "thumb");
  } else if (kind === "movie") {
    renderTop("detail-items", a.list, (r) => personLink(r.key), "face");
  } else {
    renderTop("detail-items", a.list, (r) => titleLink(r.kind, r.key), "poster");
  }
  renderTop("detail-viewers", a.viewers.map((v) => ({ ...v, image_id: null })), null);
}

// --- wrapped ------------------------------------------------------------------

async function loadWrapped() {
  const p = new URLSearchParams();
  if (state.year) p.set("year", state.year);
  if (state.user) p.set("user", state.user);
  const w = await (await fetch(`api/wrapped?${p}`)).json();
  $("#wrapped-year").innerHTML = (w.years.length ? w.years : [w.year])
    .map((y) => `<option value="${y}" ${y === w.year ? "selected" : ""}>${y}</option>`).join("");

  const el = $("#view-wrapped");
  if (!w.plays) {
    el.innerHTML = `<section class="wr-hero"><div class="eyebrow">Wrapped ${w.year}</div><div class="lead" style="margin-top:12px">Intet set i ${w.year} endnu.</div></section>`;
    return;
  }
  const day = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("da-DK", { day: "numeric", month: "long" });
  const list = (rows, linkFor) => `<ol class="wr-list">${rows.map((r, i) => `
    <li><span class="n">${i + 1}</span>
      <span>${linkFor ? `<a href="${esc(linkFor(r))}" style="color:inherit">${esc(r.name)}</a>` : esc(r.name)}</span>
      <span class="s">${hrs(r.minutes)}</span></li>`).join("")}</ol>`;
  const fact = (eyebrow, headline, text) =>
    `<section class="wr-card"><div class="eyebrow">${eyebrow}</div><div class="headline">${headline}</div><div class="text">${text}</div></section>`;

  const star = w.top_series[0];
  const fw = w.first_watch;
  const runnersUp = w.genres.slice(1, 4).map((g) => esc(g.name)).join(", ");
  const facts = [
    w.binge && fact("Årets binge", `${w.binge.n} afsnit`, `af ${esc(w.binge.name)} den ${day(w.binge.d)} – ${hrs(w.binge.minutes)} i træk.`),
    fact("Travleste dag", day(w.busiest_day.d), `${hrs(w.busiest_day.minutes)} foran skærmen på én dag.`),
    w.longest_session && fact("Længste session", hrs(w.longest_session.minutes),
      `${fmt(w.longest_session.items)} film og afsnit i træk den ${longDate(w.longest_session.start)}.`),
    w.finished_series.length && fact("Gjort færdig",
      w.finished_series.length === 1 ? "1 serie" : `${fmt(w.finished_series.length)} serier`,
      `set helt til ende: ${w.finished_series.slice(0, 4).map((s) => esc(s.name)).join(", ")}${w.finished_series.length > 4 ? " m.fl." : ""}.`),
    w.rewatch && fact("Genset", esc(w.rewatch.name), `Set ${w.rewatch.n} gange i løbet af året.`),
    fact("Årets første", esc(fw.title), `${fw.kind === "series" ? `${esc(fw.episode)} · ` : fw.kind === "video" ? `${esc(fw.name)} · ` : ""}${longDate(fw.started_at)}.`),
    w.genres[0] && fact("Årets genre", esc(w.genres[0].name), runnersUp ? `Efterfulgt af ${runnersUp}.` : ""),
  ].filter(Boolean).join("");

  el.innerHTML = `
    <section class="wr-hero">
      <div class="eyebrow">Dit ${w.year} på skærmen</div>
      <div class="big">${fmt(w.minutes / 60)} timer</div>
      <div class="lead">Det er ${fmt(w.minutes / 1440, 1)} døgn med ${fmt(w.movies)} film og ${fmt(w.episodes)} afsnit fra ${fmt(w.series)} serier${w.videos ? ` – plus ${fmt(w.videos)} videoer fra ${fmt(w.channels)} kanaler` : ""}.</div>
    </section>
    <div class="wr-row">
      <section class="wr-card wr-persona"><div class="eyebrow">Din seertype</div><div class="headline">${esc(w.persona.title)}</div><div class="text">${esc(w.persona.text)}</div></section>
      ${fact("Dit yndlingstidspunkt", `${capital(w.peak.weekday)} kl. ${String(w.peak.hour).padStart(2, "0")}`, "Her er der størst chance for at finde dig i sofaen.")}
      ${w.videos
        ? fact("Film / serier / videoer", [w.movie_minutes, w.series_minutes, w.video_minutes].map((m) => fmt((m / w.minutes) * 100)).join(" / "), "procent af seetiden.")
        : fact("Film mod serier", `${fmt((w.movie_minutes / w.minutes) * 100)} / ${fmt((w.series_minutes / w.minutes) * 100)}`, "procent af seetiden gik til film og serier.")}
    </div>
    ${star ? `<section class="wr-card wr-star">${cover(star.image_id, star.name, "ph")}
      <div><div class="eyebrow">Årets serie</div>
        <div class="headline"><a href="${esc(seriesLink(star.key))}" style="color:inherit;text-decoration:none">${esc(star.name)}</a></div>
        <div class="text">${fmt(star.episodes)} afsnit og ${hrs(star.minutes)} fordelt på ${fmt(star.days)} dage.</div></div>
    </section>` : ""}
    <div class="wr-row">
      <section class="wr-card"><div class="eyebrow">Top serier</div>${list(w.top_series, (r) => seriesLink(r.key))}</section>
      <section class="wr-card"><div class="eyebrow">Top film</div>${list(w.top_movies, (r) => movieLink(r.key))}</section>
      <section class="wr-card"><div class="eyebrow">Top skuespillere</div>${list(w.top_people, (r) => personLink(r.key))}</section>
      ${w.top_channels.length ? `<section class="wr-card"><div class="eyebrow">Top kanaler</div>${list(w.top_channels, (r) => channelLink(r.key))}</section>` : ""}
    </div>
    <div class="wr-row">${facts}</div>
    <section class="card"><div class="card-head"><h2>Måned for måned</h2><span class="hint">timer</span></div><div id="wr-months" class="chart"></div></section>`;

  const months = baseOption();
  months.xAxis.data = w.months.labels.map((l) => fmtLabel(l, "month"));
  months.tooltip.valueFormatter = (v) => `${fmt(v, 1)} t`;
  months.series = kindBars(w.months, "m");
  chart("wr-months").setOption(months, true);
}

// --- compare ------------------------------------------------------------------

async function loadCompare() {
  const c = await api("compare");
  $("#compare-pairs").innerHTML = c.pairs.length ? c.pairs.map((p) => `
    <section class="card match" style="margin-bottom:16px">
      <div class="pct">${fmt(p.match * 100)} %</div>
      <div style="flex:1;min-width:220px">
        <h2>Smags-match: ${esc(p.a)} og ${esc(p.b)}</h2>
        <div class="meter"><div style="width:${p.match * 100}%"></div></div>
        <div class="hint" style="margin-top:6px">${fmt(p.shared_count)} fælles film og serier</div>
        <div class="chips">${p.shared.map((s) => `<span class="chip">${esc(s)}</span>`).join("")}</div>
      </div>
    </section>`).join("")
    : `<section class="card empty">Sammenligningen kræver mindst to brugere, der har set noget i perioden.</section>`;

  const row = (dt, dd) => `<dt>${dt}</dt><dd>${dd}</dd>`;
  $("#compare-people").innerHTML = c.people.map((p) => `
    <section class="card person">
      <h3>${esc(p.name)}</h3>
      <dl>
        ${row("Seetid", hrs(p.minutes))}
        ${row("Film", fmt(p.movies))}
        ${row("Afsnit", `${fmt(p.episodes)} <span class="muted">(${fmt(p.series)} serier)</span>`)}
        ${row("Top serie", p.top_series ? `<a href="${esc(seriesLink(p.top_series.key))}" style="color:inherit">${esc(p.top_series.name)}</a>` : "–")}
        ${row("Top film", p.top_movie ? `<a href="${esc(movieLink(p.top_movie.key))}" style="color:inherit">${esc(p.top_movie.name)}</a>` : "–")}
        ${p.top_channel ? row("Top kanal", `<a href="${esc(channelLink(p.top_channel.key))}" style="color:inherit">${esc(p.top_channel.name)}</a>`) : ""}
        ${row("Top genre", esc(p.top_genre || "–"))}
        ${row("Ser mest", p.peak_hour != null ? `kl. ${String(p.peak_hour).padStart(2, "0")}` : "–")}
        ${row("Set færdig", `${fmt(p.completion_rate * 100)} %`)}
        ${row("Transcoding", `${fmt(p.transcode_rate * 100)} %`)}
      </dl>
    </section>`).join("");

  const bucket = state.range === "7" || state.range === "30" ? "week" : "month";
  const series = await Promise.all(c.people.map((p) => api("timeline", { bucket, user: p.id })));
  const opt = baseOption();
  opt.xAxis.data = (series[0]?.labels || []).map((l) => fmtLabel(l, bucket));
  opt.tooltip.valueFormatter = (v) => `${fmt(v, 1)} t`;
  opt.series = c.people.map((p, i) => ({
    name: p.name, type: "bar", data: series[i].minutes.map((m) => +(m / 60).toFixed(1)),
    itemStyle: { color: PALETTE[i % PALETTE.length], borderRadius: [3, 3, 0, 0] },
  }));
  chart("compare-chart").setOption(opt, true);
}

// --- routing ------------------------------------------------------------------

const DETAIL_VIEWS = ["series", "movie", "person", "channel"];  // all rendered into #view-detail
const VIEWS = ["dashboard", ...DETAIL_VIEWS, "tech", "wrapped", "compare"];

function currentRoute() {
  const [view, arg] = location.hash.replace(/^#\/?/, "").split("/");
  return { view: VIEWS.includes(view) ? view : "dashboard", arg: arg ? decodeURIComponent(arg) : null };
}

function updateControls(view) {
  const multiUser = (state.meta?.users.length || 0) > 1;
  $("#range").hidden = view === "wrapped";
  $("#wrapped-year").hidden = view !== "wrapped";
  $("#user").hidden = view === "compare" || !multiUser;
  document.querySelector('#nav a[data-view="compare"]').hidden = !multiUser;
  $("#export").href = `api/export.csv?${rangeParams()}`;
  document.querySelectorAll("#nav a").forEach((a) =>
    a.classList.toggle("on", a.dataset.view === view || (DETAIL_VIEWS.includes(view) && a.dataset.view === "dashboard")));
}

async function refresh() {
  const { view, arg } = currentRoute();
  const shown = DETAIL_VIEWS.includes(view) ? "detail" : view;
  ["dashboard", "detail", "tech", "wrapped", "compare"].forEach((v) => ($(`#view-${v}`).hidden = v !== shown));
  updateControls(view);
  try {
    if (DETAIL_VIEWS.includes(view)) await loadDetail(view, arg);
    else if (view === "tech") await loadTech();
    else if (view === "wrapped") await loadWrapped();
    else if (view === "compare") await loadCompare();
    else await loadDashboard();
  } catch (e) {
    console.error(e);
  }
  Object.values(charts).forEach((c) => c.resize());
}

document.querySelectorAll("#range button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#range button").forEach((x) => x.classList.toggle("on", x === b));
  state.range = b.dataset.range;
  state.bucket = null;
  refresh();
}));
document.querySelectorAll("#bucket button").forEach((b) => b.addEventListener("click", () => {
  state.bucket = b.dataset.bucket;
  api("timeline", { bucket: state.bucket }).then((t) => {
    document.querySelectorAll("#bucket button").forEach((x) => x.classList.toggle("on", x === b));
    renderTimeline(t, state.bucket);
  });
}));
$("#user").addEventListener("change", (e) => { state.user = e.target.value; state.userChosen = true; refresh(); });
$("#wrapped-year").addEventListener("change", (e) => { state.year = e.target.value; refresh(); });
window.addEventListener("hashchange", () => { window.scrollTo(0, 0); refresh(); });
window.addEventListener("resize", () => Object.values(charts).forEach((c) => c.resize()));
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", refresh);

// Reload the visible view when a play has been recorded since last look.
// While the tab is hidden the marker is left alone, so it catches up as soon as it is shown again.
async function checkForNewData() {
  try {
    const { marker } = await (await fetch("api/latest")).json();
    if (document.hidden || marker === state.marker) return;
    const first = state.marker === undefined;
    state.marker = marker;
    if (first) return;
    state.quiet = true;
    await loadMeta();
    await refresh();
  } catch { /* try again next tick */ } finally {
    state.quiet = false;
  }
}

document.addEventListener("visibilitychange", () => { if (!document.hidden) { renderNow(); checkForNewData(); } });

(async () => {
  await loadMeta();
  await refresh();
  renderNow();
  checkForNewData();
  setInterval(() => { renderNow(); checkForNewData(); }, 10000);
  setInterval(async () => { await loadMeta(); updateControls(currentRoute().view); }, 60000);
})();
