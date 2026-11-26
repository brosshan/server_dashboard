let servers = [];
let devices = [];
let selectedHostname = null;
let selectedLocation = "all";
let socket = null;
let reconnectDelay = 1000;
const chart = echarts.init(document.getElementById("history-chart"));

// === 輔助與樣式函數 ===

function statusBadgeClass(status) {
  if (status === "online") return "badge-online";
  if (status === "warning") return "badge-warning";
  if (status === "offline") return "badge-offline";
  return "badge-unknown";
}

function statusText(status) {
  return { online: "在線", warning: "警示", offline: "離線", unknown: "未知" }[status] || status;
}

function statusColor(status) {
  return { online: "#22c55e", warning: "#f59e0b", offline: "#ef4444", unknown: "#94a3b8" }[status] || "#94a3b8";
}

function formatLatency(latency) {
  if (latency === null || latency === undefined) return "--";
  return `${latency.toFixed(1)} ms`;
}

// === 頂部統計指標渲染 ===

function renderSummary() {
  const activeAgentIps = new Set(servers.map((s) => s.ip_address).filter(Boolean));
  const activeAgentNames = new Set(servers.map((s) => s.hostname).filter(Boolean));

  const allTargets = [
    ...servers.map((s) => ({ status: s.status, type: "server" })),
    ...devices
      .filter((d) => d.is_active && !activeAgentIps.has(d.ip_address) && !activeAgentNames.has(d.name))
      .map((d) => ({ status: d.status, type: d.device_type })),
  ];

  const total = allTargets.length;
  const online = allTargets.filter((x) => x.status === "online").length;
  const warning = allTargets.filter((x) => x.status === "warning").length;
  const offline = allTargets.filter((x) => x.status === "offline").length;

  const fwCount = devices.filter((d) => d.device_type === "firewall" && d.is_active).length;
  const nasCount = devices.filter((d) => d.device_type === "nas" && d.is_active).length;
  const upsCount = devices.filter((d) => d.device_type === "ups" && d.is_active).length;

  const cards = [
    ["總受監控節點", total, "#38bdf8"],
    ["全面在線", online, "#22c55e"],
    ["延遲/警示", warning, "#f59e0b"],
    ["異常離線", offline, "#ef4444"],
    ["外點防火牆", fwCount, "#818cf8"],
    ["各點 NAS 儲存", nasCount, "#34d399"],
    ["UPS 不斷電系統", upsCount, "#fbbf24"],
  ];

  document.getElementById("summary").innerHTML = cards.map(([label, value, color]) => `
    <div class="glass rounded-xl p-4">
      <p class="text-xs text-slate-400">${label}</p>
      <p class="text-2xl font-bold mt-1 tracking-tight" style="color:${color}">${value}</p>
    </div>
  `).join("");
}

// === 站點篩選標籤渲染 ===

function renderLocationTabs() {
  const container = document.getElementById("location-tabs");
  const locSet = new Set();
  devices.forEach((d) => { if (d.location) locSet.add(d.location); });
  servers.forEach((s) => { if (s.location) locSet.add(s.location); });
  const locations = Array.from(locSet);
  
  let html = `
    <span class="text-xs text-slate-400 font-medium">站點切換：</span>
    <button data-loc="all" class="loc-filter-btn px-3 py-1 text-xs rounded-full border transition ${
      selectedLocation === "all"
        ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
        : "bg-slate-800/80 text-slate-400 border-slate-700 hover:text-slate-200"
    }">全部站點</button>
  `;

  locations.forEach((loc) => {
    const isAct = selectedLocation === loc;
    const safeLoc = escapeHTML(loc);
    html += `
      <button data-loc="${safeLoc}" class="loc-filter-btn px-3 py-1 text-xs rounded-full border transition ${
        isAct
          ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
          : "bg-slate-800/80 text-slate-400 border-slate-700 hover:text-slate-200"
      }">${safeLoc}</button>
    `;
  });

  container.innerHTML = html;

  container.querySelectorAll(".loc-filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedLocation = btn.dataset.loc;
      renderLocationTabs();
      renderDevicesDashboard();
      renderServers();
    });
  });
}

// === 儀表板設備卡片渲染 (Firewall & NAS) ===

function renderDevicesDashboard() {
  const filtered = selectedLocation === "all"
    ? devices
    : devices.filter((d) => d.location === selectedLocation);

  const firewalls = filtered.filter((d) => d.device_type === "firewall");
  const nases = filtered.filter((d) => d.device_type === "nas");
  const upses = filtered.filter((d) => d.device_type === "ups");
  
  // 自訂伺服器（僅過濾未安裝 Agent 的純 Ping/Port 監控伺服器，已由 Agent 遙測的主機統一由主機列表豐富展示）
  const activeAgentIps = new Set(servers.map((s) => s.ip_address).filter(Boolean));
  const activeAgentNames = new Set(servers.map((s) => s.hostname).filter(Boolean));
  const customServers = filtered.filter((d) => 
    d.device_type === "server" && 
    d.check_method !== "agent" && 
    !activeAgentIps.has(d.ip_address) && 
    !activeAgentNames.has(d.name)
  );

  document.getElementById("badge-firewall-count").textContent = `${firewalls.length} 台`;
  document.getElementById("badge-nas-count").textContent = `${nases.length} 台`;
  const upsBadgeEl = document.getElementById("badge-ups-count");
  if (upsBadgeEl) upsBadgeEl.textContent = `${upses.length} 台`;

  // 渲染自訂設定之伺服器 (Ping / TCP 模式)
  const customServerContainer = document.getElementById("custom-server-grid");
  if (customServerContainer) {
    if (customServers.length > 0) {
      customServerContainer.innerHTML = `
        <div class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center justify-between">
          <span class="flex items-center gap-1.5"><span class="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>站點主機 (連線探測)</span>
          <span class="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400">${customServers.length} 台</span>
        </div>
      ` + customServers.map((srv) => `
        <div class="glass-card rounded-lg p-2.5 flex items-center justify-between hover:border-cyan-400 transition mb-1.5">
          <div>
            <div class="flex items-center gap-1.5">
              <strong class="text-xs font-semibold text-slate-100">${escapeHTML(srv.name)}</strong>
              <span class="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-300">${escapeHTML(srv.location)}</span>
            </div>
            <div class="text-[11px] text-slate-400 font-mono mt-0.5">${escapeHTML(srv.ip_address)} ${srv.check_port ? `:${srv.check_port}` : ''}</div>
          </div>
          <div class="text-right">
            <span class="text-[11px] px-2 py-0.5 rounded-full font-medium ${statusBadgeClass(srv.status)}">
              ${statusText(srv.status)}
            </span>
            <div class="text-[10px] font-mono text-cyan-400 mt-0.5">${formatLatency(srv.latency_ms)}</div>
          </div>
        </div>
      `).join("");
    } else {
      customServerContainer.innerHTML = "";
    }
  }

  // 渲染防火牆
  const fwContainer = document.getElementById("firewall-grid");
  if (firewalls.length === 0) {
    fwContainer.innerHTML = `<div class="col-span-full text-xs text-slate-500 p-6 text-center glass rounded-xl">尚無設定防火牆設備，可前往「⚙️ 設備與站點設定」新增。</div>`;
  } else {
    fwContainer.innerHTML = firewalls.map((fw) => `
      <div class="glass-card rounded-xl p-4 flex flex-col justify-between">
        <div>
          <div class="flex items-start justify-between gap-2">
            <div>
              <span class="text-[11px] text-indigo-400 font-medium tracking-wide uppercase">${escapeHTML(fw.location)}</span>
              <h3 class="font-bold text-slate-100 text-sm mt-0.5">${escapeHTML(fw.name)}</h3>
            </div>
            <span class="text-xs px-2.5 py-0.5 rounded-full font-medium ${statusBadgeClass(fw.status)}">
              ${statusText(fw.status)}
            </span>
          </div>
          <div class="mt-3 text-xs text-slate-400 space-y-1">
            <div class="flex justify-between">
              <span>目標 IP：</span>
              <span class="font-mono text-slate-300">${escapeHTML(fw.ip_address)}</span>
            </div>
            <div class="flex justify-between">
              <span>探測機制：</span>
              <span class="text-slate-300 uppercase">${escapeHTML(fw.check_method)} ${fw.check_port ? `:${fw.check_port}` : ""}</span>
            </div>
          </div>
        </div>

        <div class="mt-4 pt-3 border-t border-slate-700/60 flex items-center justify-between text-xs">
          <div class="flex items-center gap-1.5">
            <span class="text-slate-400">延遲:</span>
            <span class="font-mono font-semibold ${fw.latency_ms > 100 ? 'text-amber-400' : 'text-cyan-400'}">
              ${formatLatency(fw.latency_ms)}
            </span>
          </div>
          <span class="text-[11px] text-slate-500 truncate max-w-[130px]" title="${escapeHTML(fw.status_detail)}">
            ${escapeHTML(fw.status_detail) || "正常"}
          </span>
        </div>
      </div>
    `).join("");
  }

  // 渲染 NAS
  const nasContainer = document.getElementById("nas-grid");
  if (nases.length === 0) {
    nasContainer.innerHTML = `<div class="col-span-full text-xs text-slate-500 p-6 text-center glass rounded-xl">尚無設定 NAS 設備，可前往「⚙️ 設備與站點設定」新增。</div>`;
  } else {
    nasContainer.innerHTML = nases.map((nas) => {
      const snmp = nas.snmp;
      let metricsHtml = "";
      if (snmp) {
        const v0 = snmp.volumes && snmp.volumes.length ? snmp.volumes[0] : null;
        metricsHtml = `
          <div class="mt-3 pt-3 border-t border-slate-700/50 space-y-2 text-xs">
            <!-- CPU 條 -->
            <div>
              <div class="flex justify-between text-[11px] mb-0.5">
                <span class="text-slate-400">CPU 使用率</span>
                <span class="font-bold text-cyan-400 font-mono">${snmp.cpu_percent.toFixed(1)}%</span>
              </div>
              <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div class="bg-cyan-500 h-1.5 rounded-full" style="width: ${Math.min(100, snmp.cpu_percent)}%"></div>
              </div>
            </div>

            <!-- RAM 條 -->
            <div>
              <div class="flex justify-between text-[11px] mb-0.5">
                <span class="text-slate-400">實體記憶體</span>
                <span><b class="text-purple-400 font-mono">${snmp.memory_percent.toFixed(1)}%</b> <span class="text-slate-500">(${snmp.memory_used_gb}G/${snmp.memory_total_gb}G)</span></span>
              </div>
              <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div class="bg-purple-500 h-1.5 rounded-full" style="width: ${Math.min(100, snmp.memory_percent)}%"></div>
              </div>
            </div>

            <!-- 儲存空間 Volume 條 -->
            ${v0 ? `
            <div>
              <div class="flex justify-between text-[11px] mb-0.5">
                <span class="text-slate-400">儲存空間 (${escapeHTML(v0.mount)})</span>
                <span><b class="${v0.percent > 85 ? 'text-rose-400' : 'text-emerald-400'} font-mono">${v0.percent.toFixed(1)}%</b> <span class="text-slate-500">(${v0.used_tb}T/${v0.total_tb}T)</span></span>
              </div>
              <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div class="${v0.percent > 85 ? 'bg-rose-500' : 'bg-emerald-500'} h-1.5 rounded-full" style="width: ${Math.min(100, v0.percent)}%"></div>
              </div>
            </div>
            ` : ""}
          </div>
        `;
      }

      return `
      <div class="glass-card rounded-xl p-4 flex flex-col justify-between hover:border-emerald-500/50 transition">
        <div>
          <div class="flex items-start justify-between gap-2">
            <div>
              <span class="text-[11px] text-emerald-400 font-medium tracking-wide uppercase">${escapeHTML(nas.location)}</span>
              <h3 class="font-bold text-slate-100 text-sm mt-0.5">${escapeHTML(nas.name)}</h3>
            </div>
            <div class="flex items-center gap-1.5">
              ${snmp && snmp.temp_c !== null ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-950/70 text-amber-300 border border-amber-800/40 font-mono">🌡️ ${snmp.temp_c}°C</span>` : ""}
              <span class="text-xs px-2.5 py-0.5 rounded-full font-medium ${statusBadgeClass(nas.status)}">
                ${statusText(nas.status)}
              </span>
            </div>
          </div>
          <div class="mt-2.5 text-xs text-slate-400 space-y-1">
            <div class="flex justify-between">
              <span>NAS IP：</span>
              <span class="font-mono text-slate-300">${escapeHTML(nas.ip_address)}</span>
            </div>
            <div class="flex justify-between">
              <span>監控通訊協定：</span>
              <span class="text-slate-300 font-mono">${snmp ? "SNMP v2c (已連線)" : (nas.check_port ? `TCP Port ${nas.check_port}` : "ICMP Ping")}</span>
            </div>
          </div>
          ${metricsHtml}
        </div>

        <div class="mt-4 pt-3 border-t border-slate-700/60 flex items-center justify-between text-xs">
          <div class="flex items-center gap-1.5">
            <span class="text-slate-400">連線品質:</span>
            <span class="font-mono font-semibold text-emerald-400">
              ${formatLatency(nas.latency_ms)}
            </span>
          </div>
          <span class="text-[11px] text-slate-500 truncate max-w-[140px]" title="${escapeHTML(nas.status_detail)}">
            ${escapeHTML(nas.status_detail) || "正常"}
          </span>
        </div>
      </div>
      `;
    }).join("");
  }

  // 渲染 UPS 不斷電系統
  const upsContainer = document.getElementById("ups-grid");
  if (upsContainer) {
    if (upses.length === 0) {
      upsContainer.innerHTML = `<div class="col-span-full text-xs text-slate-500 p-6 text-center glass rounded-xl">尚無設定 UPS 不斷電系統設備，可前往「⚙️ 設備與站點設定」新增。</div>`;
    } else {
      upsContainer.innerHTML = upses.map((ups) => {
        const u = ups.snmp;
        let metricsHtml = "";
        if (u) {
          const battPercent = u.battery_percent !== undefined ? u.battery_percent : 100;
          const battColor = battPercent < 30 ? "bg-rose-500" : (battPercent < 60 ? "bg-amber-500" : "bg-emerald-500");
          const battTextColor = battPercent < 30 ? "text-rose-400" : (battPercent < 60 ? "text-amber-400" : "text-emerald-400");
          
          const loadPercent = u.percent_load !== undefined ? u.percent_load : 0;
          const loadColor = loadPercent > 80 ? "bg-rose-500" : (loadPercent > 60 ? "bg-amber-500" : "bg-cyan-500");

          metricsHtml = `
            <div class="mt-3 pt-3 border-t border-slate-700/50 space-y-2 text-xs">
              <!-- 電池電量條 -->
              <div>
                <div class="flex justify-between text-[11px] mb-0.5">
                  <span class="text-slate-400">電池容量 (${escapeHTML(u.battery_status || '正常')})</span>
                  <span><b class="${battTextColor} font-mono">${battPercent}%</b> ${u.minutes_remaining !== undefined && u.minutes_remaining !== null ? `<span class="text-slate-400">· 剩餘約 ${u.minutes_remaining} 分鐘</span>` : ''}</span>
                </div>
                <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                  <div class="${battColor} h-1.5 rounded-full" style="width: ${Math.min(100, battPercent)}%"></div>
                </div>
              </div>

              <!-- 負載率條 -->
              <div>
                <div class="flex justify-between text-[11px] mb-0.5">
                  <span class="text-slate-400">UPS 負載率</span>
                  <span><b class="text-cyan-400 font-mono">${loadPercent}%</b> <span class="text-slate-500">(輸出來源: ${escapeHTML(u.output_source || '市電')})</span></span>
                </div>
                <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                  <div class="${loadColor} h-1.5 rounded-full" style="width: ${Math.min(100, loadPercent)}%"></div>
                </div>
              </div>

              <!-- 電壓與頻率網格 -->
              <div class="grid grid-cols-2 gap-2 mt-2 pt-2 border-t border-slate-800 text-[11px]">
                <div class="bg-slate-900/60 p-2 rounded">
                  <span class="text-slate-500 block text-[10px]">輸入電壓 / 頻率</span>
                  <span class="font-mono text-slate-300 font-semibold">${u.input_voltage !== null ? `${u.input_voltage} V` : '--'}</span>
                  <span class="text-slate-500 text-[10px] ml-1">${u.input_freq !== null ? `${u.input_freq} Hz` : ''}</span>
                </div>
                <div class="bg-slate-900/60 p-2 rounded">
                  <span class="text-slate-500 block text-[10px]">輸出電壓 / 頻率</span>
                  <span class="font-mono text-slate-300 font-semibold">${u.output_voltage !== null ? `${u.output_voltage} V` : '--'}</span>
                  <span class="text-slate-500 text-[10px] ml-1">${u.output_freq !== null ? `${u.output_freq} Hz` : ''}</span>
                </div>
              </div>
            </div>
          `;
        }

        return `
        <div class="glass-card rounded-xl p-4 flex flex-col justify-between hover:border-amber-500/50 transition">
          <div>
            <div class="flex items-start justify-between gap-2">
              <div>
                <span class="text-[11px] text-amber-400 font-medium tracking-wide uppercase">${escapeHTML(ups.location)}</span>
                <h3 class="font-bold text-slate-100 text-sm mt-0.5">${escapeHTML(ups.name)}</h3>
              </div>
              <div class="flex items-center gap-1.5">
                ${u && u.temperature_c !== null && u.temperature_c !== undefined ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-950/70 text-amber-300 border border-amber-800/40 font-mono">🌡️ ${u.temperature_c}°C</span>` : ""}
                <span class="text-xs px-2.5 py-0.5 rounded-full font-medium ${statusBadgeClass(ups.status)}">
                  ${statusText(ups.status)}
                </span>
              </div>
            </div>

            <div class="mt-2.5 text-xs text-slate-400 space-y-1">
              <div class="flex justify-between">
                <span>UPS IP：</span>
                <span class="font-mono text-slate-300">${escapeHTML(ups.ip_address)}</span>
              </div>
              <div class="flex justify-between">
                <span>設備型號 / 類型：</span>
                <span class="text-slate-300 font-mono">${u ? `${escapeHTML(u.model || '')} (${escapeHTML(u.ups_type || '在線式')})` : escapeHTML(ups.notes || 'UPS 監控卡')}</span>
              </div>
            </div>
            ${metricsHtml}
          </div>

          <div class="mt-4 pt-3 border-t border-slate-700/60 flex items-center justify-between text-xs">
            <div class="flex items-center gap-1.5">
              <span class="text-slate-400">連線品質:</span>
              <span class="font-mono font-semibold text-amber-400">
                ${formatLatency(ups.latency_ms)}
              </span>
            </div>
            <span class="text-[11px] text-slate-500 truncate max-w-[140px]" title="${escapeHTML(ups.status_detail)}">
              ${escapeHTML(ups.status_detail) || "正常"}
            </span>
          </div>
        </div>
        `;
      }).join("");
    }
  }
}

// === 伺服器清單與趨勢圖表渲染 ===

function renderServers() {
  const list = document.getElementById("server-list");

  // 依當前選定站點過濾主機
  const filteredServers = selectedLocation === "all"
    ? servers
    : servers.filter((s) => s.location === selectedLocation);

  document.getElementById("badge-server-count").textContent = `${filteredServers.length} 台`;

  if (filteredServers.length === 0) {
    list.innerHTML = `<div class="text-xs text-slate-500 p-4 text-center">本站點目前無受監控之主機。</div>`;
    renderServerDetailCards(null);
    return;
  }

  // 若尚未選取或目前選取的主機不存在，預設選取過濾清單的第一台
  if (!selectedHostname || !filteredServers.some((s) => s.hostname === selectedHostname)) {
    selectedHostname = filteredServers[0].hostname;
  }

  list.innerHTML = filteredServers.map((server) => {
    const isSelected = selectedHostname === server.hostname;
    const cpuFree = Math.max(0, 100 - server.cpu_percent);
    const ramFree = Math.max(0, 100 - server.memory_percent);
    const ramFreeGb = Math.max(0, server.memory_total_gb - server.memory_used_gb);

    // 優先顯示使用者在「設備設定」中命名的名稱，並提示原主機名稱與站點
    const titleName = server.display_name || server.hostname;
    const hasCustomName = server.display_name && server.display_name !== server.hostname;
    const hostNote = hasCustomName ? ` (${escapeHTML(server.hostname)})` : "";
    const locBadge = server.location ? `<span class="text-[10px] px-1.5 py-0.2 rounded bg-cyan-950/80 text-cyan-400 border border-cyan-800/50 font-medium">${escapeHTML(server.location)}</span>` : "";

    return `
      <button data-host="${escapeHTML(server.hostname)}" class="server-card w-full text-left glass-card rounded-lg p-3 hover:border-cyan-400 transition ${isSelected ? 'border-cyan-500 ring-1 ring-cyan-500/50' : ''}">
        <div class="flex justify-between items-center gap-1.5">
          <div class="flex items-center gap-1.5 flex-wrap">
            <strong class="text-sm font-semibold text-slate-100">${escapeHTML(titleName)}</strong>
            <span class="text-xs text-slate-400 font-normal">${hostNote}</span>
            ${locBadge}
          </div>
          <span class="text-xs px-2 py-0.5 rounded-full font-medium ${statusBadgeClass(server.status)} whitespace-nowrap">
            ${statusText(server.status)}
          </span>
        </div>

        <div class="mt-2.5 space-y-2 text-xs">
          <!-- CPU 條 -->
          <div>
            <div class="flex justify-between text-[11px] mb-1">
              <span class="text-slate-400">CPU 使用 / 剩餘</span>
              <span><b class="text-cyan-400">${server.cpu_percent.toFixed(1)}%</b> <span class="text-slate-500">| 剩 ${cpuFree.toFixed(1)}%</span></span>
            </div>
            <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
              <div class="bg-cyan-500 h-1.5 rounded-full" style="width: ${Math.min(100, server.cpu_percent)}%"></div>
            </div>
          </div>

          <!-- RAM 條 -->
          <div>
            <div class="flex justify-between text-[11px] mb-1">
              <span class="text-slate-400">RAM 使用 / 剩餘</span>
              <span><b class="text-purple-400">${server.memory_percent.toFixed(1)}%</b> <span class="text-slate-500">| 剩 ${ramFree.toFixed(1)}% (${ramFreeGb.toFixed(1)}G)</span></span>
            </div>
            <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
              <div class="bg-purple-500 h-1.5 rounded-full" style="width: ${Math.min(100, server.memory_percent)}%"></div>
            </div>
          </div>
        </div>

        <div class="text-[11px] text-slate-500 mt-2.5 pt-2 border-t border-slate-700/50 flex justify-between items-center">
          <span>${escapeHTML(server.ip_address)}${server.notes ? ` · <span class="text-slate-400">${escapeHTML(server.notes)}</span>` : ""}</span>
          <span>${escapeHTML(server.platform)}</span>
        </div>
      </button>
    `;
  }).join("");

  list.querySelectorAll(".server-card").forEach((button) => {
    button.addEventListener("click", () => {
      selectedHostname = button.dataset.host;
      renderServers();
      loadHistory();
    });
  });

  const curServer = filteredServers.find((s) => s.hostname === selectedHostname) || filteredServers[0];
  renderServerDetailCards(curServer);
}

// === 渲染選定主機的詳細 CPU、RAM、Disk 資訊卡片 ===

function renderServerDetailCards(server) {
  const container = document.getElementById("server-detail-metrics");
  if (!container) return;

  if (!server) {
    container.innerHTML = `<div class="col-span-full text-xs text-slate-500 p-2 text-center">無選取之伺服器詳細資料</div>`;
    return;
  }

  const cpuUsed = server.cpu_percent;
  const cpuFree = Math.max(0, 100 - cpuUsed);

  const ramUsed = server.memory_percent;
  const ramFree = Math.max(0, 100 - ramUsed);
  const ramFreeGb = Math.max(0, server.memory_total_gb - server.memory_used_gb);

  // 磁碟總計或各磁區
  const disks = server.disk || [];

  container.innerHTML = `
    <!-- CPU 詳細卡片 -->
    <div class="bg-slate-800/60 border border-slate-700/80 rounded-lg p-3">
      <div class="flex items-center justify-between">
        <span class="text-xs text-slate-400 font-semibold">⚙️ CPU 運算資源</span>
        <span class="text-xs font-mono font-bold ${cpuUsed > 85 ? 'text-rose-400' : 'text-cyan-400'}">${cpuUsed.toFixed(1)}%</span>
      </div>
      <div class="mt-2 grid grid-cols-2 text-xs">
        <div>
          <span class="text-[10px] text-slate-500 block">使用中</span>
          <span class="font-bold text-slate-200">${cpuUsed.toFixed(1)}%</span>
        </div>
        <div>
          <span class="text-[10px] text-slate-500 block">剩餘空間</span>
          <span class="font-bold text-emerald-400">${cpuFree.toFixed(1)}%</span>
        </div>
      </div>
      <div class="w-full bg-slate-900 rounded-full h-1.5 mt-2.5 overflow-hidden">
        <div class="bg-cyan-500 h-1.5 rounded-full" style="width: ${Math.min(100, cpuUsed)}%"></div>
      </div>
    </div>

    <!-- 記憶體詳細卡片 -->
    <div class="bg-slate-800/60 border border-slate-700/80 rounded-lg p-3">
      <div class="flex items-center justify-between">
        <span class="text-xs text-slate-400 font-semibold">🧠 實體記憶體 (RAM)</span>
        <span class="text-xs font-mono font-bold ${ramUsed > 85 ? 'text-rose-400' : 'text-purple-400'}">${ramUsed.toFixed(1)}%</span>
      </div>
      <div class="mt-2 grid grid-cols-2 text-xs">
        <div>
          <span class="text-[10px] text-slate-500 block">已使用 (${server.memory_used_gb.toFixed(1)} GB)</span>
          <span class="font-bold text-slate-200">${ramUsed.toFixed(1)}%</span>
        </div>
        <div>
          <span class="text-[10px] text-slate-500 block">剩餘容量 (${ramFreeGb.toFixed(1)} GB)</span>
          <span class="font-bold text-emerald-400">${ramFree.toFixed(1)}%</span>
        </div>
      </div>
      <div class="w-full bg-slate-900 rounded-full h-1.5 mt-2.5 overflow-hidden">
        <div class="bg-purple-500 h-1.5 rounded-full" style="width: ${Math.min(100, ramUsed)}%"></div>
      </div>
    </div>

    <!-- 磁碟空間詳細卡片 -->
    <div class="bg-slate-800/60 border border-slate-700/80 rounded-lg p-3">
      <div class="flex items-center justify-between mb-1.5">
        <span class="text-xs text-slate-400 font-semibold">💾 本機磁碟空間 (Disks)</span>
        <span class="text-[10px] text-slate-400">${disks.length} 個磁區</span>
      </div>
      <div class="space-y-1.5 max-h-[75px] overflow-y-auto pr-1">
        ${disks.length === 0 ? '<span class="text-xs text-slate-500">無磁區資料</span>' : disks.map((d) => {
          const diskFreePercent = Math.max(0, 100 - d.percent);
          const diskFreeGb = Math.max(0, d.total_gb - d.used_gb);
          return `
            <div class="text-[11px]">
              <div class="flex justify-between items-center text-[10px] text-slate-300">
                <span class="font-bold font-mono">${escapeHTML(d.mount)} (${d.total_gb.toFixed(0)} GB)</span>
                <span>用 <b class="${d.percent > 85 ? 'text-rose-400' : 'text-amber-400'}">${d.percent.toFixed(1)}%</b> / 剩 <b class="text-emerald-400">${diskFreePercent.toFixed(1)}%</b> (${diskFreeGb.toFixed(1)}G)</span>
              </div>
              <div class="w-full bg-slate-900 rounded-full h-1 mt-0.5 overflow-hidden">
                <div class="${d.percent > 85 ? 'bg-rose-500' : 'bg-emerald-500'} h-1 rounded-full" style="width: ${Math.min(100, d.percent)}%"></div>
              </div>
            </div>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

async function loadHistory() {
  if (!selectedHostname) return;
  const hours = document.getElementById("hours").value;
  const response = await fetchReadWithAuth(`/api/history/${encodeURIComponent(selectedHostname)}?hours=${hours}`);
  if (!response.ok) return;
  const rows = await response.json();
  const curSrv = servers.find((s) => s.hostname === selectedHostname);
  const titleDisplay = curSrv && curSrv.display_name && curSrv.display_name !== curSrv.hostname
    ? `${curSrv.display_name} (${selectedHostname})`
    : selectedHostname;
  document.getElementById("chart-title").textContent = `${titleDisplay} 資源歷史趨勢 (${hours}小時)`;
  chart.setOption({
    tooltip: { trigger: "axis" },
    legend: { data: ["CPU 使用率", "記憶體使用率"], textStyle: { color: "#cbd5e1" } },
    grid: { left: 45, right: 20, top: 45, bottom: 45 },
    xAxis: {
      type: "category",
      data: rows.map((row) => new Date(row.recorded_at).toLocaleTimeString("zh-TW", { hour: '2-digit', minute: '2-digit' })),
      axisLabel: { color: "#94a3b8", hideOverlap: true },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 100,
      axisLabel: { color: "#94a3b8", formatter: "{value}%"},
      splitLine: { lineStyle: { color: "#1e293b" } },
    },
    series: [
      { name: "CPU 使用率", type: "line", smooth: true, data: rows.map((row) => row.cpu_percent), itemStyle: { color: "#38bdf8" } },
      { name: "記憶體使用率", type: "line", smooth: true, data: rows.map((row) => row.memory_percent), itemStyle: { color: "#a78bfa" } },
    ],
  });
}

// === 設定介面：設備管理表格與 CRUD ===

function renderDeviceTable() {
  const tbody = document.getElementById("device-table-body");
  if (devices.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-slate-500">目前尚無自訂監控設備，請點擊上方按鈕新增！</td></tr>`;
    return;
  }

  tbody.innerHTML = devices.map((d) => {
    const typeIcon = { server: "🖥️ 伺服器", nas: "💾 NAS", firewall: "🛡️ 防火牆", ups: "🔋 UPS" }[d.device_type] || d.device_type;
    return `
      <tr class="hover:bg-slate-800/50 transition">
        <td class="py-3 px-4 font-semibold text-slate-100">${escapeHTML(d.name)}</td>
        <td class="py-3 px-4"><span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300">${typeIcon}</span></td>
        <td class="py-3 px-4 text-cyan-300">${escapeHTML(d.location)}</td>
        <td class="py-3 px-4 font-mono text-xs">${escapeHTML(d.ip_address)}</td>
        <td class="py-3 px-4 uppercase text-xs">${escapeHTML(d.check_method)} ${d.check_port ? `(${d.check_port})` : ''}</td>
        <td class="py-3 px-4">
          <span class="text-xs px-2.5 py-0.5 rounded-full font-medium ${statusBadgeClass(d.status)}">
            ${statusText(d.status)}
          </span>
        </td>
        <td class="py-3 px-4 text-xs">
          <span class="font-mono text-slate-300 font-semibold">${formatLatency(d.latency_ms)}</span>
          <p class="text-[11px] text-slate-500 truncate max-w-[150px]">${escapeHTML(d.notes || d.status_detail || '')}</p>
        </td>
        <td class="py-3 px-4 text-right space-x-2">
          <button type="button" data-action="test" data-id="${d.id}" class="device-action-btn text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-cyan-400 transition" title="立即檢測">檢測</button>
          <button type="button" data-action="edit" data-id="${d.id}" class="device-action-btn text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition">編輯</button>
          <button type="button" data-action="delete" data-id="${d.id}" class="device-action-btn text-xs px-2 py-1 rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 transition">刪除</button>
        </td>
      </tr>
    `;
  }).join("");
}

// === Modal 與 CRUD 邏輯 ===

const modal = document.getElementById("device-modal");
const form = document.getElementById("device-form");
const probeResultEl = document.getElementById("probe-test-result");

function openDeviceModal(device = null) {
  form.reset();
  probeResultEl.classList.add("hidden");
  if (device) {
    document.getElementById("modal-title").textContent = "編輯監控設備";
    document.getElementById("form-device-id").value = device.id;
    document.getElementById("form-name").value = device.name;
    document.getElementById("form-device-type").value = device.device_type;
    document.getElementById("form-location").value = device.location;
    document.getElementById("form-ip").value = device.ip_address;
    document.getElementById("form-port").value = device.check_port || "";
    document.getElementById("form-method").value = device.check_method;
    document.getElementById("form-active").value = device.is_active ? "true" : "false";
    document.getElementById("form-notes").value = device.notes || "";
  } else {
    document.getElementById("modal-title").textContent = "新增監控設備";
    document.getElementById("form-device-id").value = "";
  }
  modal.classList.remove("hidden");
}

function closeDeviceModal() {
  modal.classList.add("hidden");
}

document.getElementById("btn-open-add-device").addEventListener("click", () => openDeviceModal());
document.getElementById("modal-close").addEventListener("click", closeDeviceModal);
document.getElementById("modal-cancel").addEventListener("click", closeDeviceModal);

// 清除舊版 localStorage 殘留金鑰，改用 sessionStorage（關閉分頁即自動清除）
localStorage.removeItem("monitor_admin_key");
let adminKey = sessionStorage.getItem("monitor_admin_key") || "";
let readApiKey = sessionStorage.getItem("monitor_read_key") || "";

// 安全防護：HTML 實體轉義函數 (防止 DOM-based XSS)
function escapeHTML(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function updateAdminAuthUI() {
  const statusEl = document.getElementById("admin-auth-status");
  if (statusEl) {
    if (adminKey) {
      statusEl.textContent = "已設管理金鑰";
      statusEl.className = "text-emerald-400";
    } else {
      statusEl.textContent = "未設金鑰";
      statusEl.className = "text-slate-400";
    }
  }
}

document.getElementById("btn-admin-auth").addEventListener("click", () => {
  const entered = prompt("請輸入管理者金鑰 (X-Admin-Key)，請查閱伺服器 .env 中的 ADMIN_API_KEY：", "");
  if (entered !== null) {
    adminKey = entered.trim();
    if (adminKey) {
      sessionStorage.setItem("monitor_admin_key", adminKey);
      readApiKey = adminKey;
      sessionStorage.setItem("monitor_read_key", readApiKey);
    } else {
      sessionStorage.removeItem("monitor_admin_key");
      readApiKey = "";
      sessionStorage.removeItem("monitor_read_key");
    }
    updateAdminAuthUI();
    if (typeof connect === "function") {
      if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
      connect();
    }
  }
});
updateAdminAuthUI();

function getAuthHeaders() {
  return {
    "Content-Type": "application/json",
    ...(adminKey ? { "X-Admin-Key": adminKey } : {}),
  };
}

function getReadHeaders(key = readApiKey || adminKey) {
  return key
    ? { "X-API-Key": key, "X-Admin-Key": key }
    : {};
}

async function fetchReadWithAuth(url, options = {}) {
  const request = (key) => fetch(url, {
    ...options,
    headers: {
      ...(options.headers || {}),
      ...getReadHeaders(key),
    },
  });

  let response = await request(readApiKey || adminKey);
  if (response.status !== 401) return response;

  const entered = prompt(
    "此儀表板需要讀取授權。請輸入 API_KEY 或 ADMIN_API_KEY：",
    readApiKey || adminKey
  );
  if (entered === null || !entered.trim()) return response;

  readApiKey = entered.trim();
  sessionStorage.setItem("monitor_read_key", readApiKey);
  response = await request(readApiKey);
  if (response.ok && socket && socket.readyState === WebSocket.CLOSED) connect();
  return response;
}

async function fetchWithAuth(url, options = {}) {
  options.headers = {
    ...getAuthHeaders(),
    ...(options.headers || {}),
  };
  let res = await fetch(url, options);
  if (res.status === 401) {
    const entered = prompt(
      "【需要管理者授權】目前的 X-Admin-Key 管理金鑰無效或未設定。\n請輸入管理者金鑰（請查閱伺服器 .env 內的 ADMIN_API_KEY）：",
      ""
    );
    if (entered !== null && entered.trim()) {
      adminKey = entered.trim();
      sessionStorage.setItem("monitor_admin_key", adminKey);
      updateAdminAuthUI();
      options.headers = {
        ...options.headers,
        "X-Admin-Key": adminKey,
      };
      res = await fetch(url, options);
    }
  }
  return res;
}

// 表單提交
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = document.getElementById("form-device-id").value;
  const payload = {
    name: document.getElementById("form-name").value.trim(),
    device_type: document.getElementById("form-device-type").value,
    location: document.getElementById("form-location").value.trim(),
    ip_address: document.getElementById("form-ip").value.trim(),
    check_port: document.getElementById("form-port").value ? parseInt(document.getElementById("form-port").value) : null,
    check_method: document.getElementById("form-method").value,
    is_active: document.getElementById("form-active").value === "true",
    notes: document.getElementById("form-notes").value.trim(),
  };

  try {
    let res;
    if (id) {
      res = await fetchWithAuth(`/api/devices/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    } else {
      res = await fetchWithAuth("/api/devices", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      const detailMsg = errData.detail
        ? (Array.isArray(errData.detail) ? errData.detail.map((e) => e.msg).join(", ") : errData.detail)
        : `HTTP ${res.status}`;
      throw new Error(detailMsg);
    }
    closeDeviceModal();
    await refreshAll();
  } catch (err) {
    alert("儲存錯誤: " + err.message);
  }
});

// 立即測試按鈕 (Modal 內)
document.getElementById("btn-test-probe").addEventListener("click", async () => {
  const ip = document.getElementById("form-ip").value.trim();
  if (!ip) {
    alert("請先填寫 IP 位址！");
    return;
  }
  probeResultEl.classList.remove("hidden");
  probeResultEl.innerHTML = `<span class="text-cyan-400">正在測試連線...</span>`;

  const payload = {
    name: document.getElementById("form-name").value.trim() || "Test",
    device_type: document.getElementById("form-device-type").value,
    location: document.getElementById("form-location").value.trim(),
    ip_address: ip,
    check_port: document.getElementById("form-port").value ? parseInt(document.getElementById("form-port").value) : null,
    check_method: document.getElementById("form-method").value,
  };

  try {
    const res = await fetchWithAuth("/api/devices/test-probe", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res.status}`);
    }
    const result = await res.json();
    const isOk = result.status === "online" || result.status === "warning";
    probeResultEl.innerHTML = `
      <div class="flex items-center gap-2 ${isOk ? 'text-emerald-400' : 'text-rose-400'} font-semibold">
        <span>${isOk ? '✓ 連線測試成功' : '✗ 連線失敗'}</span>
        ${result.latency_ms ? `<span>(${escapeHTML(result.latency_ms)} ms)</span>` : ''}
      </div>
      <p class="text-[11px] text-slate-400 mt-1">${escapeHTML(result.status_detail || '')}</p>
    `;
  } catch (err) {
    probeResultEl.innerHTML = `<span class="text-rose-400">測試異常: ${escapeHTML(err.message)}</span>`;
  }
});

// 使用事件委派處理設備表格 CRUD 操作（避免行內 onclick，配合嚴格 CSP）
document.getElementById("device-table-body").addEventListener("click", (e) => {
  const btn = e.target.closest(".device-action-btn");
  if (!btn) return;
  const id = parseInt(btn.dataset.id, 10);
  const action = btn.dataset.action;
  if (action === "test") window.testDevice(id);
  else if (action === "edit") window.editDevice(id);
  else if (action === "delete") window.deleteDevice(id);
});

// 全局暴露 CRUD 動作給 HTML 行內使用
window.editDevice = (id) => {
  const d = devices.find((x) => x.id === id);
  if (d) openDeviceModal(d);
};

window.deleteDevice = async (id) => {
  if (!confirm("確定要刪除此設備監控項目嗎？")) return;
  try {
    const res = await fetchWithAuth(`/api/devices/${id}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res.status}`);
    }
    await refreshAll();
  } catch (err) {
    alert("刪除失敗: " + err.message);
  }
};

window.testDevice = async (id) => {
  try {
    const res = await fetchWithAuth(`/api/devices/${id}/test`, {
      method: "POST",
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res.status}`);
    }
    const result = await res.json();
    await refreshAll();
    alert(`檢測完成：[${result.status}] ${result.status_detail}`);
  } catch (err) {
    alert("檢測失敗: " + err.message);
  }
};

// === 頁面分頁切換 ===

const viewDashboard = document.getElementById("view-dashboard");
const viewSettings = document.getElementById("view-settings");
const tabBtnDash = document.getElementById("tab-btn-dashboard");
const tabBtnSettings = document.getElementById("tab-btn-settings");

tabBtnDash.addEventListener("click", () => {
  viewDashboard.classList.remove("hidden");
  viewSettings.classList.add("hidden");
  tabBtnDash.className = "px-4 py-1.5 text-sm font-medium rounded-md bg-cyan-600 text-white shadow";
  tabBtnSettings.className = "px-4 py-1.5 text-sm font-medium rounded-md text-slate-300 hover:text-white hover:bg-slate-700/60 transition";
  chart.resize();
});

tabBtnSettings.addEventListener("click", () => {
  viewSettings.classList.remove("hidden");
  viewDashboard.classList.add("hidden");
  tabBtnSettings.className = "px-4 py-1.5 text-sm font-medium rounded-md bg-cyan-600 text-white shadow";
  tabBtnDash.className = "px-4 py-1.5 text-sm font-medium rounded-md text-slate-300 hover:text-white hover:bg-slate-700/60 transition";
  renderDeviceTable();
});

// === 資料載入與 WebSocket ===

async function refreshAll() {
  const resServers = await fetchReadWithAuth("/api/servers");
  const resDevices = await fetchReadWithAuth("/api/devices");
  if (resServers.ok) servers = await resServers.json();
  if (resDevices.ok) devices = await resDevices.json();

  if (!selectedHostname && servers.length) selectedHostname = servers[0].hostname;

  renderSummary();
  renderLocationTabs();
  renderDevicesDashboard();
  renderServers();
  renderDeviceTable();
  if (selectedHostname) loadHistory();
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const authKey = readApiKey || adminKey;
  const protocols = ["monitor.v1"];
  if (authKey) {
    const bytes = new TextEncoder().encode(authKey);
    let binary = "";
    bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
    const encodedKey = btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
    protocols.push(`auth.${encodedKey}`);
  }
  socket = new WebSocket(`${protocol}//${location.host}/ws`, protocols);
  socket.onopen = () => {
    reconnectDelay = 1000;
    document.getElementById("connection").textContent = "即時連線中";
    document.getElementById("connection").className = "rounded-full px-3 py-1 text-xs font-medium bg-emerald-600/30 text-emerald-300 border border-emerald-500/30";
  };
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "servers") {
      servers = message.data;
    } else if (message.type === "devices_status") {
      devices = message.data;
    } else if (message.type === "metric") {
      const index = servers.findIndex((server) => server.hostname === message.data.hostname);
      if (index >= 0) servers[index] = message.data;
      else servers.push(message.data);
      if (!selectedHostname) selectedHostname = message.data.hostname;
    }
    renderSummary();
    renderLocationTabs();
    renderDevicesDashboard();
    renderServers();
    renderDeviceTable();
  };
  socket.onclose = (event) => {
    if (event.code === 1008) {
      document.getElementById("connection").textContent = "需要讀取授權";
      document.getElementById("connection").className = "rounded-full px-3 py-1 text-xs font-medium bg-amber-600/30 text-amber-300 border border-amber-500/30";
      return;
    }
    if (event.code === 1000) return;
    document.getElementById("connection").textContent = "連線中斷重試中...";
    document.getElementById("connection").className = "rounded-full px-3 py-1 text-xs font-medium bg-amber-600/30 text-amber-300 border border-amber-500/30";
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  };
}

// === 區塊自由拖拉編排 (Drag and Drop Layout) ===

const SECTION_ORDER_STORAGE_KEY = "dashboard_section_order_v1";
const DEFAULT_SECTION_ORDER = ["servers", "nas", "firewall", "ups"];

function initDraggableSections() {
  const container = document.getElementById("dashboard-sections-container");
  if (!container) return;

  // 1. 讀取並應用儲存的順序
  applySavedSectionOrder();

  // 2. 註冊拖拉監聽
  let draggedEl = null;

  const sections = container.querySelectorAll(".dashboard-section");
  sections.forEach((section) => {
    section.addEventListener("dragstart", (e) => {
      draggedEl = section;
      section.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", section.dataset.sectionId);
    });

    section.addEventListener("dragend", () => {
      if (draggedEl) {
        draggedEl.classList.remove("dragging");
      }
      sections.forEach((s) => s.classList.remove("drag-over"));
      draggedEl = null;
      saveSectionOrder();
      if (chart) chart.resize();
    });

    section.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      if (!draggedEl || draggedEl === section) return;
      section.classList.add("drag-over");
    });

    section.addEventListener("dragleave", () => {
      section.classList.remove("drag-over");
    });

    section.addEventListener("drop", (e) => {
      e.preventDefault();
      section.classList.remove("drag-over");
      if (!draggedEl || draggedEl === section) return;

      const rect = section.getBoundingClientRect();
      const nextSibling = (e.clientY - rect.top > rect.height / 2) ? section.nextSibling : section;
      container.insertBefore(draggedEl, nextSibling);
      saveSectionOrder();
      if (chart) chart.resize();
    });
  });

  // 3. 重設順序按鈕
  const resetBtn = document.getElementById("btn-reset-layout");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      localStorage.removeItem(SECTION_ORDER_STORAGE_KEY);
      applySavedSectionOrder(DEFAULT_SECTION_ORDER);
      if (chart) chart.resize();
    });
  }
}

function saveSectionOrder() {
  const container = document.getElementById("dashboard-sections-container");
  if (!container) return;
  const currentOrder = Array.from(container.children)
    .filter((el) => el.classList && el.classList.contains("dashboard-section"))
    .map((el) => el.dataset.sectionId)
    .filter(Boolean);
  try {
    localStorage.setItem(SECTION_ORDER_STORAGE_KEY, JSON.stringify(currentOrder));
  } catch (err) {
    console.error("無法儲存區塊順序:", err);
  }
}

function applySavedSectionOrder(customOrder = null) {
  const container = document.getElementById("dashboard-sections-container");
  if (!container) return;

  let order = customOrder;
  if (!order) {
    try {
      const stored = localStorage.getItem(SECTION_ORDER_STORAGE_KEY);
      if (stored) order = JSON.parse(stored);
    } catch (e) {
      order = null;
    }
  }
  if (!Array.isArray(order) || order.length === 0) {
    order = DEFAULT_SECTION_ORDER;
  }

  // 依順序將元素 append 回容器
  order.forEach((id) => {
    const el = container.querySelector(`[data-section-id="${id}"]`);
    if (el) container.appendChild(el);
  });
}

document.getElementById("hours").addEventListener("change", loadHistory);
window.addEventListener("resize", () => chart.resize());

refreshAll().then(connect).catch(console.error);
initDraggableSections();
