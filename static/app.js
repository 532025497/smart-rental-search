/* 智能租房搜索 — 前端逻辑 */
(function() {
  "use strict";

  // ============== DOM 引用 ==============
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const form = $("#search-form");
  const btnSearch = $("#btn-search");
  const btnDemo = $("#btn-demo");
  const progressPanel = $("#progress-panel");
  const resultsPanel = $("#results-panel");
  const errorPanel = $("#error-panel");
  const logsEl = $("#logs");
  const elapsedEl = $("#elapsed");
  const phaseEl = $("#phase-label");
  const progressFill = $("#progress-fill");
  const listingsEl = $("#listings");
  const stationListEl = $("#station-list");
  const aiRecEl = $("#ai-recommendation");
  const listingCountEl = $("#listing-count");
  const statsRowEl = $("#stats-row");
  const errorMessageEl = $("#error-message");
  const listingImportForm = $("#listing-import-form");
  const priceForm = $("#price-form");
  const importStatusEl = $("#import-status");
  const priceResultEl = $("#price-result");
  const marketPricesEl = $("#market-prices");

  let map = null;          // Leaflet map 实例
  let pollTimer = null;    // 轮询定时器
  let currentJobId = null;

  // ============== 工具函数 ==============
  function show(el) { el.classList.remove("hidden"); }
  function hide(el) { el.classList.add("hidden"); }
  function showError(msg) {
    hide(progressPanel);
    hide(resultsPanel);
    show(errorPanel);
    errorMessageEl.textContent = msg;
    resetSearchButton();
  }
  function resetSearchButton() {
    btnSearch.disabled = false;
    btnSearch.textContent = "🚀 开始搜索";
  }

  // ============== 进度bar估算 ==============
  function estimateProgress(logs) {
    // 简易: 根据关键日志匹配phase估算
    const last = logs[logs.length - 1] || "";
    if (last.includes("[Phase 1]")) return 10;
    if (last.includes("[OK] 地理编码")) return 15;
    if (last.includes("[OK] 加载地铁站")) return 20;
    if (last.includes("通勤计算:")) {
      const m = last.match(/(\d+)\/(\d+)/);
      if (m) return 20 + Math.floor(20 * m[1] / m[2]);
    }
    if (last.includes("[planner] 可行域")) return 45;
    if (last.includes("[Phase 2]")) return 50;
    if (last.includes("[Phase 3]")) return 55;
    if (/\[\d+\/\d+\] 提取:/.test(last)) return 70;
    if (last.includes("[Phase 4]")) return 90;
    if (last.includes("统计:") || last.includes("====")) return 95;
    if (last.includes("保存:")) return 100;
    return 0;
  }

  function updatePhase(logs) {
    const last = logs[logs.length - 1] || "";
    if (last.includes("[Phase 1]")) phaseEl.textContent = "Phase 1: 规划师生成采集计划";
    else if (last.includes("[Phase 2]")) phaseEl.textContent = "Phase 2: 评判器定义验收标准";
    else if (last.includes("[Phase 3]")) phaseEl.textContent = "Phase 3: 采集与房源验证";
    else if (last.includes("[Phase 4]")) phaseEl.textContent = "Phase 4: 排序输出";
    else if (last.includes("通勤计算:")) phaseEl.textContent = "计算精确通勤时间";
    else if (last.includes("统计:")) phaseEl.textContent = "汇总结果";
  }

  // ============== API 调用 ==============
  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return r.json();
  }

  async function getJSON(url) {
    const r = await fetch(url);
    return r.json();
  }

  // ============== 表单提交 ==============
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    btnSearch.disabled = true;
    btnSearch.textContent = "⏳ 执行中...";
    hide(resultsPanel);
    hide(errorPanel);
    show(progressPanel);

    const formData = new FormData(form);
    const payload = {
      city: formData.get("city"),
      work: formData.get("work"),
      commute: parseInt(formData.get("commute"), 10),
      budget_min: parseInt(formData.get("budget_min"), 10),
      budget_max: parseInt(formData.get("budget_max"), 10),
      max_posts: parseInt(formData.get("max_posts"), 10),
      use_stub: formData.get("use_stub") === "on",
      lease_term: formData.get("lease_term"),
      room_type: formData.get("room_type"),
      personal_only: formData.get("personal_only") === "on",
    };

    try {
      const res = await postJSON("/api/search", payload);
      if (!res.ok) {
        showError(res.error || "启动任务失败");
        return;
      }
      currentJobId = res.job_id;
      startPolling(currentJobId);
    } catch (e) {
      showError("网络错误: " + e.message);
    }
  });

  // ============== 本地房源导入 ==============
  listingImportForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#btn-import");
    btn.disabled = true;
    btn.textContent = "保存中...";
    hide(importStatusEl);
    const data = new FormData(listingImportForm);
    const payload = {
      city: data.get("city"),
      area: data.get("area"),
      price_monthly: data.get("price_monthly"),
      lease_term: data.get("lease_term"),
      room_type: data.get("room_type"),
      source_url: data.get("source_url"),
      raw_text: data.get("raw_text"),
      is_personal: data.get("is_personal") === "on",
      source_platform: "manual",
    };
    try {
      const res = await postJSON("/api/listings/import", payload);
      show(importStatusEl);
      importStatusEl.classList.toggle("error", !res.ok);
      if (!res.ok) {
        importStatusEl.textContent = res.error || "保存失败";
        return;
      }
      importStatusEl.textContent = res.listing.duplicate
        ? "已更新重复房源，未新增重复样本"
        : `已保存：${res.listing.title}`;
      listingImportForm.elements.raw_text.value = "";
      listingImportForm.elements.source_url.value = "";
      renderPriceResult(
        payload.area,
        res.price_stats,
        [res.listing]
      );
      priceForm.elements.city.value = payload.city;
      priceForm.elements.area.value = payload.area;
      priceForm.elements.lease_term.value = res.listing.lease_term;
      if ([...priceForm.elements.room_type.options]
          .some((option) => option.value === res.listing.room_type)) {
        priceForm.elements.room_type.value = res.listing.room_type;
      }
    } catch (err) {
      show(importStatusEl);
      importStatusEl.classList.add("error");
      importStatusEl.textContent = "网络错误: " + err.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "保存房源";
    }
  });

  // ============== 独立价格查询 ==============
  priceForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = new FormData(priceForm);
    const params = new URLSearchParams({
      city: data.get("city"),
      area: data.get("area"),
      lease_term: data.get("lease_term"),
      room_type: data.get("room_type"),
      personal_only: data.get("personal_only") === "on" ? "1" : "0",
      days: "60",
    });
    priceResultEl.className = "price-result empty-state";
    priceResultEl.textContent = "查询中...";
    try {
      const res = await getJSON(`/api/prices?${params.toString()}`);
      if (!res.ok) {
        priceResultEl.textContent = res.error || "查询失败";
        return;
      }
      renderPriceResult(res.area, res.stats, res.listings || []);
    } catch (err) {
      priceResultEl.textContent = "网络错误: " + err.message;
    }
  });

  // ============== Demo按钮 ==============
  btnDemo.addEventListener("click", async () => {
    btnDemo.disabled = true;
    btnDemo.textContent = "加载中...";
    try {
      const res = await getJSON("/api/demo");
      if (!res.ok) {
        showError(res.error || "无历史数据");
        return;
      }
      hide(progressPanel);
      hide(errorPanel);
      renderResult({
        listings: res.listings,
        viable_stations: res.viable_stations,
        work_location: res.work_location,
        stats: res.stats,
        elapsed: res.elapsed,
        criteria: "",
        price_summaries: [],
      });
    } catch (e) {
      showError("网络错误: " + e.message);
    } finally {
      btnDemo.disabled = false;
      btnDemo.textContent = "📊 查看历史结果";
    }
  });

  // ============== 轮询 ==============
  function startPolling(jobId) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => pollStatus(jobId), 1500);
    pollStatus(jobId);  // 立即触发一次
  }

  async function pollStatus(jobId) {
    try {
      const s = await getJSON(`/api/status/${jobId}`);
      if (!s.ok) {
        clearInterval(pollTimer);
        pollTimer = null;
        showError(s.error || "状态查询失败");
        return;
      }

      // 更新日志+进度
      const logs = s.logs || [];
      logsEl.textContent = logs.slice(-30).join("\n");
      logsEl.scrollTop = logsEl.scrollHeight;
      if (s.elapsed != null) elapsedEl.textContent = s.elapsed.toFixed(1) + "s";
      const pct = estimateProgress(logs);
      progressFill.style.width = pct + "%";
      updatePhase(logs);

      // 完成/出错
      if (s.status === "done") {
        clearInterval(pollTimer);
        pollTimer = null;
        await fetchResult(jobId);
      } else if (s.status === "error") {
        clearInterval(pollTimer);
        pollTimer = null;
        showError(s.error || "任务失败");
      }
    } catch (e) {
      console.error("poll error:", e);
    }
  }

  async function fetchResult(jobId) {
    const r = await getJSON(`/api/result/${jobId}`);
    if (!r.ok) {
      showError(r.error || "获取结果失败");
      return;
    }
    hide(progressPanel);
    renderResult(r);
    resetSearchButton();
  }

  // ============== 渲染结果 ==============
  function renderResult(r) {
    show(resultsPanel);

    // 1. 地图
    renderMap(r.viable_stations || [], r.work_location || {});

    // 2. 站点列表
    renderStations(r.viable_stations || []);

    // 3. 统计
    renderStats(r.stats || {}, r.elapsed);

    renderMarketPrices(r.price_summaries || []);

    // 4. AI推荐面板 (Top 3 by confidence)
    renderAIRecommendation(r.listings || []);

    // 5. 房源列表
    renderListings(r.listings || []);
  }

  function renderMarketPrices(items) {
    if (!items.length) {
      marketPricesEl.innerHTML = "<p class='hint'>可达区域暂无价格样本</p>";
      return;
    }
    marketPricesEl.innerHTML = items.map((item) => `
      <div class="market-price-item">
        <div class="area">${escapeHTML(item.area)}</div>
        <div class="range">${formatPrice(item.q25)} - ${formatPrice(item.q75)}</div>
        <div class="sample">中位数 ${formatPrice(item.median)} · ${item.sample_count}条 · ${escapeHTML(item.confidence)}</div>
      </div>`).join("");
  }

  function renderPriceResult(area, stats, listings) {
    if (!stats || !stats.sample_count) {
      priceResultEl.className = "price-result empty-state";
      priceResultEl.textContent = `${area || "该区域"} 暂无近60天价格样本`;
      return;
    }
    priceResultEl.className = "price-result";
    const recent = listings.slice(0, 3).map((item) =>
      `<div class="price-sample-row">${escapeHTML(item.title)} · ${formatPrice(item.price_monthly)}</div>`
    ).join("");
    priceResultEl.innerHTML = `
      <div class="price-main">
        <span>${escapeHTML(area)} 中位月租</span>
        <strong>${formatPrice(stats.median)}</strong>
      </div>
      <div class="price-detail">
        <span>常见区间 ${formatPrice(stats.q25)} - ${formatPrice(stats.q75)}</span>
        <span>完整范围 ${formatPrice(stats.minimum)} - ${formatPrice(stats.maximum)}</span>
        <span>近60天 ${stats.sample_count} 条样本</span>
        <span>可信度 ${escapeHTML(stats.confidence)}</span>
      </div>
      ${recent ? `<div class="price-samples">${recent}</div>` : ""}`;
  }

  function formatPrice(value) {
    return value == null ? "-" : `${Number(value).toLocaleString("zh-CN")}元`;
  }

  // ---- 地图 ----
  function renderMap(stations, workLoc) {
    if (!map) {
      map = L.map("map").setView([39.95, 116.30], 11);
      L.tileLayer("https://webst0{s}.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}", {
        subdomains: "1234",
        attribution: "© 高德地图",
        maxZoom: 18,
      }).addTo(map);
    } else {
      map.eachLayer((l) => {
        if (l instanceof L.Marker) map.removeLayer(l);
      });
    }

    // 工作地点 (红色pin)
    if (workLoc.lng && workLoc.lat) {
      L.marker([workLoc.lat, workLoc.lng], {
        icon: createIcon("💼", "#e74c3c"),
      }).addTo(map).bindPopup("<b>工作地点</b>");
    }

    // 可行站点 (绿色pin)
    const bounds = [];
    if (workLoc.lng) bounds.push([workLoc.lat, workLoc.lng]);
    stations.forEach((s) => {
      if (!s.lng || !s.lat) return;
      L.marker([s.lat, s.lng], {
        icon: createIcon("📍", "#0099a9"),
      }).addTo(map).bindPopup(
        `<b>${escapeHTML(s.name)}</b><br>通勤: ${s.commute_min}分钟<br>` +
        `距离: ${s.distance_km?.toFixed(1) || "?"}km<br>` +
        `步行: ${s.walking_m || "?"}m<br>换乘: ${s.transfers || 0}次`
      );
      bounds.push([s.lat, s.lng]);
    });

    if (bounds.length) map.fitBounds(bounds, { padding: [40, 40] });
  }

  function createIcon(emoji, color) {
    return L.divIcon({
      className: "custom-marker",
      html: `<div style="font-size:22px; color:${color};
              text-shadow: 0 0 4px white, 0 0 4px white;">${emoji}</div>`,
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    });
  }

  // ---- 站点chip ----
  function renderStations(stations) {
    if (!stations.length) {
      stationListEl.innerHTML = "<span class='hint'>无可行站点</span>";
      return;
    }
    stationListEl.innerHTML = stations.map((s) => `
      <span class="station-chip">
        📍 ${escapeHTML(s.name)}
        <span class="commute">${s.commute_min || "?"}min</span>
      </span>`).join("");
  }

  // ---- 统计 ----
  function renderStats(stats, elapsed) {
    if (!Object.keys(stats).length) {
      statsRowEl.innerHTML = `<span class="hint">耗时 ${elapsed || 0}s</span>`;
      return;
    }
    statsRowEl.innerHTML = `
      <span class="stat-item">采集 <b>${stats.collected || 0}</b>帖</span>
      <span class="stat-item">LLM提取 <b>${stats.extracted || 0}</b>次</span>
      <span class="stat-item">验证 <b>${stats.validated || 0}</b>次</span>
      <span class="stat-item">通过 <b>${stats.passed || 0}</b>条</span>
      <span class="stat-item">重试 <b>${stats.retried || 0}</b>次</span>
      <span class="stat-item">丢弃 <b>${stats.rejected || 0}</b>条</span>
      <span class="stat-item">LLM调用 <b>${stats.llm_calls || 0}</b>次</span>
      <span class="stat-item">tokens <b>${stats.llm_tokens || 0}</b></span>
      <span class="stat-item">耗时 <b>${elapsed || "?"}</b>s</span>
    `;
  }

  // ---- AI推荐 ----
  function renderAIRecommendation(listings) {
    // Top 3 by confidence (且是rental, 且置信度>0.5)
    const top = listings
      .filter((l) => l.is_rental !== false && (l.confidence || 0) > 0.5)
      .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
      .slice(0, 3);

    if (!top.length) {
      aiRecEl.innerHTML = "<p class='hint'>暂无高置信度房源推荐</p>";
      return;
    }

    aiRecEl.innerHTML = top.map((l, i) => {
      const rank = ["🥇", "🥈", "🥉"][i] || "★";
      const reason = buildReason(l);
      return `
        <div class="ai-listing">
          <div class="title">${rank} ${escapeHTML(l.title || "无标题")}</div>
          <div class="listing-meta">
            <span>💰 ${l.price_monthly || "?"}元/月</span>
            <span>· ${l.room_type || "?"} ${l.layout || ""}</span>
            <span>· ${l.district || ""} ${l.neighborhood || ""}</span>
          </div>
          <div class="reason">${reason}</div>
        </div>`;
    }).join("");
  }

  function buildReason(l) {
    const parts = [];
    parts.push(`置信度 ${(l.confidence * 100).toFixed(0)}%`);
    if (l.rental_subtype) parts.push(`类型: ${l.rental_subtype}`);
    if (l.attempts > 1) parts.push(`经${l.attempts}轮提取`);
    return "推荐理由: " + parts.join(" · ");
  }

  // ---- 房源列表 ----
  function renderListings(listings) {
    listingCountEl.textContent = listings.length;
    if (!listings.length) {
      listingsEl.innerHTML = "<p class='hint'>暂无房源</p>";
      return;
    }

    listingsEl.innerHTML = listings.map((l) => {
      const conf = l.confidence || 0;
      const confClass = conf >= 0.85 ? "confidence-high"
                      : conf >= 0.6 ? "confidence-mid"
                      : "confidence-low";
      const listingClass = !l.is_rental ? "rejected"
                        : conf < 0.6 ? "low-confidence" : "";
      const price = l.price_monthly ? `${l.price_monthly}<small>元/月</small>` : "?元/月";

      const tags = [];
      if (l.rental_subtype) tags.push(`<span class="tag type">${escapeHTML(l.rental_subtype)}</span>`);
      if (l.deposit_method) tags.push(`<span class="tag deposit">${escapeHTML(l.deposit_method)}</span>`);
      if (l.room_type) tags.push(`<span class="tag">${escapeHTML(l.room_type)}</span>`);
      if (l.lease_term && l.lease_term !== "未知") tags.push(`<span class="tag">${escapeHTML(l.lease_term)}</span>`);
      if (l.is_personal === true) tags.push(`<span class="tag personal">个人房源</span>`);

      const meta = [];
      if (l.district || l.neighborhood)
        meta.push(`<span class="meta-item">📍 <b>${escapeHTML(l.district || "")} ${escapeHTML(l.neighborhood || "")}</b></span>`);
      if (l.layout) meta.push(`<span class="meta-item">🏠 <b>${escapeHTML(l.layout)}</b></span>`);
      if (l.area_sqm) meta.push(`<span class="meta-item">📐 <b>${l.area_sqm}</b>平</span>`);
      if (l.floor) meta.push(`<span class="meta-item">🏢 <b>${escapeHTML(l.floor)}</b></span>`);
      if (l.available_from) meta.push(`<span class="meta-item">📅 <b>${escapeHTML(l.available_from)}</b></span>`);

      const safeUrl = safeHttpUrl(l.source_url);
      const sourceLink = safeUrl
        ? `<a class="listing-link" href="${escapeHTML(safeUrl)}" target="_blank" rel="noopener noreferrer">原帖↗</a>`
        : "";

      return `
        <div class="listing ${listingClass}">
          <div class="listing-header">
            <div class="listing-title">${escapeHTML(l.title || "无标题")}</div>
            <div class="listing-price">${price}</div>
          </div>
          <div class="listing-meta">${meta.join("")}</div>
          <div class="listing-tags">
            ${tags.join("")}
            <span class="listing-confidence ${confClass}">置信度 ${(conf * 100).toFixed(0)}%</span>
            ${sourceLink}
          </div>
          ${l.highlights ? `<div class="listing-highlights">✨ ${escapeHTML(l.highlights)}</div>` : ""}
          ${l.contact ? `<div class="listing-highlights">📞 ${escapeHTML(l.contact)}</div>` : ""}
        </div>`;
    }).join("");
  }

  // ============== 工具: HTML转义 ==============
  function escapeHTML(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function safeHttpUrl(value) {
    if (!value) return "";
    try {
      const url = new URL(value, window.location.origin);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch (_err) {
      return "";
    }
  }

  // ============== 初始化 ==============
  console.log("智能租房搜索 UI 已加载");
})();
