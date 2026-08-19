/* =================================================================
   KONEKSI KE API
   Sekarang dashboard/ di-serve langsung oleh FastAPI di port yang sama
   (lihat api/main.py -- StaticFiles mount), jadi default-nya relative URL
   ('' + '/api/...') supaya otomatis ikut origin yang dipakai buka
   dashboard-nya -- baik http://localhost:8000/ maupun http://<IP-LAN>:8000/,
   tanpa perlu hardcode IP. Masih bisa di-override kalau API-nya dipisah
   ke host/port lain:
     - lewat query string:  index.html?api=http://192.168.1.10:8000
     - override itu disimpan di localStorage, dipakai terus sampai
       diganti lagi / dihapus manual (localStorage.removeItem('nm_api_base'))
   ================================================================= */
const DEFAULT_API_BASE = '';
(function initApiBase(){
  const params = new URLSearchParams(window.location.search);
  const fromQuery = params.get('api');
  if (fromQuery) localStorage.setItem('nm_api_base', fromQuery.replace(/\/$/, ''));
})();
const API_BASE = localStorage.getItem('nm_api_base') || DEFAULT_API_BASE;

async function apiFetch(path){
  const res = await fetch(API_BASE + path);
  if (!res.ok){
    let detail = '';
    try { detail = (await res.json()).detail || ''; } catch(e){}
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json();
}

/* ================= UTILITIES ================= */
const fmtNum = (n) => new Intl.NumberFormat('id-ID').format(n);
const fmtMB = (mb) => {
  if (mb === null || mb === undefined) return '-';
  if (mb >= 1000) return (mb/1000).toFixed(2) + ' GB';
  if (mb < 1) return (mb*1000).toFixed(0) + ' KB';
  return mb.toFixed(2) + ' MB';
};
const fmtBytes = (b) => {
  if (b >= 1e9) return (b/1e9).toFixed(2) + ' GB';
  if (b >= 1e6) return (b/1e6).toFixed(2) + ' MB';
  if (b >= 1e3) return (b/1e3).toFixed(1) + ' KB';
  return b + ' B';
};
const fmtDateID = (isoDate) => {
  const months = ['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'];
  const [y,m,d] = isoDate.split('-');
  return `${d} ${months[parseInt(m)-1]} ${y}`;
};
const levelBadgeClass = (lvl) => lvl === 'Tinggi' ? 'badge-red' : lvl === 'Sedang' ? 'badge-amber' : 'badge-blue';
const levelIconColor = (lvl) => lvl === 'Tinggi' ? {bg:'#fde8ea', fg:'#d92d43'} : lvl === 'Sedang' ? {bg:'#fef3d9', fg:'#b3760a'} : {bg:'#e7edff', fg:'#3b6df0'};
const protoColors = {TCP:'#2563eb', UDP:'#f97316', ICMP:'#16a34a', Other:'#e11d48'};
const CHART_FONT = "'Inter', sans-serif";
Chart.defaults.font.family = CHART_FONT;
Chart.defaults.color = '#64748b';
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(()=>fn(...a), ms); }; };

/* ================= CONNECTION STATUS BANNER ================= */
function showApiError(err){
  let el = document.getElementById('apiErrorBanner');
  if (!el){
    el = document.createElement('div');
    el.id = 'apiErrorBanner';
    el.className = 'notice';
    el.style.margin = '0 32px 0';
    el.style.borderColor = '#f7c9cf';
    el.style.background = '#fdeef0';
    el.style.color = '#a3283c';
    document.querySelector('.content').prepend(el);
  }
  const apiLabel = API_BASE || window.location.origin;
  el.innerHTML = `<i class="fa-solid fa-plug-circle-xmark"></i>
    <div>Tidak bisa konek ke API di <b>${apiLabel}</b> — ${err.message || err}.<br>
    Pastikan server-nya jalan: <code>cd api && uvicorn main:app --host 0.0.0.0 --port 8000</code>,
    dan database <code>network_clean</code> sudah terisi (jalankan ETL / backfill dulu).</div>`;
}
function clearApiError(){
  const el = document.getElementById('apiErrorBanner');
  if (el) el.remove();
}

/* ================= STATUS BADGE (LIVE/OFFLINE) ================= */
function setConnStatus(isLive){
  const badge = document.getElementById('connStatusBadge');
  const text = document.getElementById('connStatusText');
  if (!badge || !text) return;
  badge.classList.toggle('live', isLive);
  badge.classList.toggle('offline', !isLive);
  text.textContent = isLive ? 'LIVE' : 'OFFLINE';
  badge.title = isLive
    ? 'Terhubung ke server — data live'
    : 'Tidak terhubung ke server / gagal menerima data';
}
async function checkConnStatus(){
  try {
    const res = await fetch(API_BASE + '/api/health', { cache: 'no-store' });
    if (!res.ok) throw new Error('bad status');
    const data = await res.json();
    setConnStatus(!!data && data.status === 'ok');
  } catch (e) {
    setConnStatus(false);
  }
}

/* ================= DETAIL MODAL (Real-time Logs & Anomaly Detection) ================= */
function openModal(title, bodyHtml){
  document.getElementById('detailModalTitle').textContent = title;
  document.getElementById('detailModalBody').innerHTML = bodyHtml;
  document.getElementById('detailModalOverlay').classList.add('open');
}
function closeModal(){
  document.getElementById('detailModalOverlay').classList.remove('open');
}
document.getElementById('detailModalClose').addEventListener('click', closeModal);
document.getElementById('detailModalOverlay').addEventListener('click', (e)=>{
  if (e.target.id === 'detailModalOverlay') closeModal();
});
document.addEventListener('keydown', (e)=>{ if (e.key === 'Escape') closeModal(); });

const modalLoadingHtml = () => `<div class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i>Memuat detail...</div>`;
const modalErrorHtml = (err) => `<div class="empty-state"><i class="fa-solid fa-triangle-exclamation"></i>Gagal memuat detail: ${err.message || err}</div>`;
const detailItem = (label, value, mono) => `<div class="detail-item"><div class="d-label">${label}</div><div class="d-value ${mono?'mono':''}">${value}</div></div>`;
const unavailableMappingNotice = () => `<div class="notice"><i class="fa-solid fa-circle-info"></i><div>Mapping User/Guest belum tersedia di <code>data/</code>, User ditampilkan sebagai "Unknown User".</div></div>`;
const destinationsTableHtml = (destinations) => {
  const rows = destinations.length ? destinations.map(x=>`
    <tr>
      <td class="ip-mono">${x.dstip}</td>
      <td>${x.country}</td>
      <td>${x.application}</td>
      <td>${fmtNum(x.conn)}</td>
      <td>${fmtBytes(x.traffic_bytes)}</td>
    </tr>`).join('') : `<tr><td colspan="5"><div class="empty-state"><i class="fa-solid fa-inbox"></i>Belum ada data destination.</div></td></tr>`;
  return `<div style="overflow-x:auto;"><table><thead><tr><th>Destination</th><th>Country</th><th>Application</th><th>Koneksi</th><th>Traffic</th></tr></thead><tbody>${rows}</tbody></table></div>`;
};

async function showIpDetail(srcip){
  openModal(srcip, modalLoadingHtml());
  try{
    const d = await apiFetch('/api/logs/ip-detail?srcip=' + encodeURIComponent(srcip));
    const html = `
      <div class="detail-grid">
        ${detailItem('Host', d.host)}
        ${detailItem('Source IP', d.srcip, true)}
        ${detailItem('Total Koneksi', fmtNum(d.total_koneksi))}
        ${detailItem('Total Traffic', fmtBytes(d.total_bytes))}
        ${detailItem('Terakhir Terlihat', d.last_seen ? d.last_seen : '-')}
      </div>
      ${!d.user_mapping_available ? unavailableMappingNotice() : ''}
      <div class="modal-section-title">Destination (Top 10)</div>
      ${destinationsTableHtml(d.destinations)}`;
    openModal(`Detail Source IP — ${d.srcip}`, html);
  } catch(err){
    openModal('Detail Source IP', modalErrorHtml(err));
  }
}

async function showAnomalyDetail(srcip, tanggal, jam){
  openModal('Detail Anomali', modalLoadingHtml());
  try{
    const d = await apiFetch(`/api/anomaly/detail?srcip=${encodeURIComponent(srcip)}&tanggal=${encodeURIComponent(tanggal)}&jam=${encodeURIComponent(jam)}`);
    const html = `
      <div class="detail-grid">
        ${detailItem('User', d.user)}
        ${detailItem('Device', d.device)}
        ${detailItem('IP', d.srcip, true)}
        ${detailItem('Waktu', `${fmtDateID(d.tanggal)} · ${d.jam}`)}
        ${detailItem('Level', `<span class="badge ${levelBadgeClass(d.level)}">${d.level}</span>`)}
        ${detailItem('Tipe Anomali', d.tipe)}
        ${detailItem('Score', d.score)}
        ${detailItem('Traffic (koneksi/jam)', fmtNum(d.jumlah_koneksi))}
      </div>
      ${!d.user_mapping_available ? unavailableMappingNotice() : ''}
      <div class="modal-section-title">Deskripsi</div>
      <p style="font-size:12.8px; color:var(--ink-soft); line-height:1.6;">${d.deskripsi}</p>
      <div class="modal-section-title">Destination pada Jam Ini</div>
      ${destinationsTableHtml(d.destinations)}`;
    openModal(`Detail Anomali — ${d.srcip}`, html);
  } catch(err){
    openModal('Detail Anomali', modalErrorHtml(err));
  }
}

/* ================= NAVIGATION ================= */
const pageTitles = {
  overview: ['Dashboard Overview', 'Ringkasan aktivitas jaringan hari ini'],
  logs: ['Real-time Logs', 'Log jaringan secara real-time'],
  traffic: ['Traffic Analysis', 'Analisis trafik jaringan'],
  anomaly: ['Anomaly Detection', 'Deteksi anomali jaringan'],
  reports: ['Reports', 'Laporan trafik jaringan'],
  alerts: ['Alerts', 'Notifikasi & peringatan keamanan jaringan'],
};

document.querySelectorAll('.nav-item[data-page]').forEach(item => {
  item.addEventListener('click', () => {
    const page = item.dataset.page;
    document.querySelectorAll('.nav-item[data-page]').forEach(n => n.classList.remove('active'));
    item.classList.add('active');
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-' + page).classList.add('active');
    document.getElementById('pageTitle').textContent = pageTitles[page][0];
    document.getElementById('pageSubtitle').textContent = pageTitles[page][1];
    closeSidebar();
  });
});

/* ================= SIDEBAR (MOBILE) ================= */
function openSidebar(){
  document.getElementById('sidebar').classList.add('open');
  document.getElementById('sidebarBackdrop').classList.add('open');
}
function closeSidebar(){
  if (window.innerWidth <= 900) {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebarBackdrop').classList.remove('open');
  }
}
document.getElementById('hamburgerBtn').addEventListener('click', openSidebar);
document.getElementById('sidebarBackdrop').addEventListener('click', closeSidebar);

/* ================= GLOBAL STATE / CACHE ================= */
const STATE = {
  meta: null,
  overview: null,
  trafficAnalysis: null,
  anomaly: null,
  monthlyReport: {ym: null, rows: []},
  yearlyReport: {year: null, rows: []},
};
let chartRefs = {};
function destroyChart(key){ if (chartRefs[key]) { chartRefs[key].destroy(); delete chartRefs[key]; } }
function makeChart(key, ctx, cfg){ destroyChart(key); chartRefs[key] = new Chart(ctx, cfg); return chartRefs[key]; }

/* ================= META (date range, IP list, bulan tersedia) ================= */
async function loadMeta(){
  const meta = await apiFetch('/api/meta');
  STATE.meta = meta;
  document.getElementById('dateRangePill').textContent = meta.range_start && meta.range_end
    ? `${fmtDateID(meta.range_start)} – ${fmtDateID(meta.range_end)}` : '—';

  const monthSel = document.getElementById('monthSelect');
  monthSel.innerHTML = '';
  meta.available_months.forEach(ym=>{
    const [y,mo] = ym.split('-');
    const opt = document.createElement('option'); opt.value = ym; opt.textContent = `${monthNamesId[mo]} ${y}`;
    monthSel.appendChild(opt);
  });

  const years = [...new Set(meta.available_months.map(ym=>ym.split('-')[0]))];
  const yearSel = document.getElementById('yearSelect');
  yearSel.innerHTML = years.map(y=>`<option value="${y}">${y}</option>`).join('') || '<option value="2026">2026</option>';

  return meta;
}

/* ================= PAGE 1: OVERVIEW ================= */
async function loadOverview(){
  const ov = await apiFetch('/api/overview');
  STATE.overview = ov;
  renderOverview(ov);
}
function renderOverview(ov){
  const statHtml = `
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon blue"><i class="fa-solid fa-database"></i></div></div>
      <div class="stat-label">Total Traffic (Hari ini)</div>
      <div class="stat-value">${fmtBytes(ov.total_traffic_bytes)}</div>
      <div class="stat-delta up"><i class="fa-solid fa-arrow-trend-up"></i>${fmtDateID(ov.last_date)}</div>
    </div>
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon purple"><i class="fa-solid fa-network-wired"></i></div></div>
      <div class="stat-label">Total Koneksi</div>
      <div class="stat-value">${fmtNum(ov.total_koneksi)}</div>
      <div class="stat-delta up"><i class="fa-solid fa-arrow-trend-up"></i><span class="muted">koneksi tercatat</span></div>
    </div>
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon teal"><i class="fa-solid fa-desktop"></i></div></div>
      <div class="stat-label">IP Unik Aktif</div>
      <div class="stat-value">${ov.unique_ip}</div>
      <div class="stat-delta up"><i class="fa-solid fa-circle-check"></i><span class="muted">host aktif</span></div>
    </div>
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon rose"><i class="fa-solid fa-triangle-exclamation"></i></div></div>
      <div class="stat-label">Anomali Terdeteksi</div>
      <div class="stat-value">${ov.anomali}</div>
      <div class="stat-delta ${ov.anomali>0?'down':'up'}"><i class="fa-solid ${ov.anomali>0?'fa-arrow-trend-up':'fa-circle-check'}"></i><span class="muted">hari ini</span></div>
    </div>`;
  document.getElementById('overviewStats').innerHTML = statHtml;

  makeChart('trend', document.getElementById('chartTrend'), {
    type:'line',
    data:{
      labels: ov.trend7.map(d=>fmtDateID(d.date).replace(/ \d{4}$/,'')),
      datasets:[{
        data: ov.trend7.map(d=>d.traffic_mb),
        borderColor:'#3b6df0', backgroundColor:'rgba(59,109,240,.08)',
        fill:true, tension:.35, pointRadius:3, pointBackgroundColor:'#3b6df0', borderWidth:2.5,
      }]
    },
    options:{
      plugins:{legend:{display:false}, tooltip:{callbacks:{label:(c)=>fmtMB(c.parsed.y)}}},
      scales:{ y:{beginAtZero:true, grid:{color:'#eef1f7'}, ticks:{callback:v=>v+' MB'}}, x:{grid:{display:false}} },
      responsive:true, maintainAspectRatio:false,
    }
  });

  const proto = ov.protocol_split;
  makeChart('protoDonut', document.getElementById('chartProtoDonut'), {
    type:'doughnut',
    data:{labels:Object.keys(proto), datasets:[{data:Object.values(proto), backgroundColor:Object.keys(proto).map(k=>protoColors[k]||'#94a3b8'), borderWidth:0}]},
    options:{cutout:'72%', plugins:{legend:{display:false}}, responsive:true, maintainAspectRatio:false}
  });
  document.getElementById('protoLegend').innerHTML = Object.entries(proto).map(([k,v])=>`
    <div class="legend-row"><div class="legend-left"><span class="dot" style="background:${protoColors[k]||'#94a3b8'}"></span>${k}</div><b>${v}%</b></div>`).join('');

  document.getElementById('topSrcTable').innerHTML = ov.top_src_ip.length ? ov.top_src_ip.map(r=>`
    <tr><td class="ip-mono">${r.ip}</td><td>${fmtMB(r.traffic_gb*1000)}</td>
    <td style="min-width:130px;"><div style="display:flex; align-items:center; gap:8px;"><div class="bar-track" style="flex:1;"><div class="bar-fill" style="width:${r.pct}%"></div></div><span style="font-weight:600; font-size:11.5px;">${r.pct}%</span></div></td></tr>`).join('')
    : `<tr><td colspan="3"><div class="empty-state"><i class="fa-solid fa-inbox"></i>Belum ada data.</div></td></tr>`;

  document.getElementById('topPortTable').innerHTML = ov.top_dest_port.length ? ov.top_dest_port.map(r=>`
    <tr><td><b>${r.port}</b> <span style="color:var(--ink-faint)">(${r.name})</span></td><td>${fmtMB(r.traffic_mb)}</td>
    <td style="min-width:130px;"><div style="display:flex; align-items:center; gap:8px;"><div class="bar-track" style="flex:1;"><div class="bar-fill" style="width:${r.pct}%"></div></div><span style="font-weight:600; font-size:11.5px;">${r.pct}%</span></div></td></tr>`).join('')
    : `<tr><td colspan="3"><div class="empty-state"><i class="fa-solid fa-inbox"></i>Belum ada data (tabel raw_data kosong).</div></td></tr>`;
}

/* ================= PAGE 1: TRAFFIC BULANAN / TAHUNAN ================= */
async function loadTrafficTrend(){
  const data = await apiFetch('/api/overview/traffic-trend');
  renderTrafficTrend(data);
}
function renderTrafficTrend(data){
  makeChart('monthlyTraffic', document.getElementById('chartMonthlyTraffic'), {
    type:'bar',
    data:{labels:data.monthly.map(d=>d.ym), datasets:[{data:data.monthly.map(d=>d.traffic_mb), backgroundColor:'#3b6df0', borderRadius:5, maxBarThickness:34}]},
    options:{plugins:{legend:{display:false}, tooltip:{callbacks:{label:c=>fmtMB(c.parsed.y)}}}, scales:{y:{beginAtZero:true, grid:{color:'#eef1f7'}, ticks:{callback:v=>v+' MB'}}, x:{grid:{display:false}}}, responsive:true, maintainAspectRatio:false}
  });
  makeChart('yearlyTraffic', document.getElementById('chartYearlyTraffic'), {
    type:'bar',
    data:{labels:data.yearly.map(d=>String(d.year)), datasets:[{data:data.yearly.map(d=>d.traffic_mb), backgroundColor:'#7c5cff', borderRadius:5, maxBarThickness:44}]},
    options:{plugins:{legend:{display:false}, tooltip:{callbacks:{label:c=>fmtMB(c.parsed.y)}}}, scales:{y:{beginAtZero:true, grid:{color:'#eef1f7'}, ticks:{callback:v=>v+' MB'}}, x:{grid:{display:false}}}, responsive:true, maintainAspectRatio:false}
  });
}

/* ================= PAGE 1: GUEST / USER ACTIVITY ================= */
async function loadUserActivity(){
  const data = await apiFetch('/api/user-activity');
  renderUserActivity(data);
}
function renderUserActivity(data){
  document.getElementById('userMappingUnavailableNotice').style.display = data.user_mapping_available ? 'none' : 'flex';
  document.getElementById('userActivityTable').innerHTML = data.items.length ? data.items.map(r=>`
    <tr>
      <td><b>${r.user}</b></td>
      <td class="ip-mono">${r.srcip}</td>
      <td>${r.device}</td>
      <td>${fmtBytes(r.traffic_bytes)}</td>
    </tr>`).join('') : `<tr><td colspan="4"><div class="empty-state"><i class="fa-solid fa-inbox"></i>Belum ada data.</div></td></tr>`;
}

/* ================= PAGE 2: REAL-TIME LOGS (server-side filter/paginasi) ================= */
let logsState = {page:1, perPage:25, search:'', proto:'', dateFrom:'', dateTo:'', sort:'desc'};
async function loadLogs(){
  const q = new URLSearchParams({
    page: logsState.page, per_page: logsState.perPage, sort: logsState.sort,
  });
  if (logsState.search) q.set('search', logsState.search);
  if (logsState.proto) q.set('proto', logsState.proto);
  if (logsState.dateFrom) q.set('date_start', logsState.dateFrom);
  if (logsState.dateTo) q.set('date_end', logsState.dateTo);

  const tbody = document.getElementById('logsTableBody');
  tbody.innerHTML = `<tr><td colspan="12"><div class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i>Memuat log...</div></td></tr>`;

  const data = await apiFetch('/api/logs?' + q.toString());
  renderLogs(data);
}
function renderLogs(data){
  const rows = data.rows;
  document.getElementById('logsTableBody').innerHTML = rows.length ? rows.map(r=>`
    <tr>
      <td class="mono">${r.waktu}</td>
      <td class="ip-mono ip-click" data-srcip="${r.srcip}" title="Klik untuk lihat detail">${r.srcip}</td>
      <td>${r.host}</td>
      <td class="ip-mono">${r.dstip}</td>
      <td>${r.country}</td>
      <td>${r.city}</td>
      <td>${r.org}</td>
      <td>${r.hostname}</td>
      <td><b>${r.port}</b></td>
      <td><span class="badge ${r.proto==='TCP'?'badge-blue':'badge-green'}">${r.proto}</span></td>
      <td>${r.application}</td>
      <td>${fmtBytes(r.size)}</td>
    </tr>`).join('') : `<tr><td colspan="12"><div class="empty-state"><i class="fa-solid fa-inbox"></i>Tidak ada log yang cocok dengan filter.</div></td></tr>`;

  const totalPages = Math.max(1, Math.ceil(data.total / data.per_page));
  const start = (data.page-1)*data.per_page;
  document.getElementById('logsCount').textContent = `Menampilkan ${data.total ? start+1 : 0}–${Math.min(start+data.per_page, data.total)} dari ${fmtNum(data.total)} log`;

  let pagesHtml = '';
  const addBtn = (p, label, disabled, active) => pagesHtml += `<button class="page-btn ${active?'active':''}" ${disabled?'disabled':''} data-p="${p}">${label}</button>`;
  addBtn(data.page-1, '<i class="fa-solid fa-chevron-left"></i>', data.page===1, false);
  let pages = [];
  if (totalPages <= 5) { for(let i=1;i<=totalPages;i++) pages.push(i); }
  else {
    pages.push(1);
    let lo = Math.max(2, data.page-1), hi = Math.min(totalPages-1, data.page+1);
    if (lo>2) pages.push('...');
    for(let i=lo;i<=hi;i++) pages.push(i);
    if (hi<totalPages-1) pages.push('...');
    pages.push(totalPages);
  }
  pages.forEach(p=>{
    if (p==='...') pagesHtml += `<span class="page-btn" style="border:none; cursor:default;">…</span>`;
    else addBtn(p, p, false, p===data.page);
  });
  addBtn(data.page+1, '<i class="fa-solid fa-chevron-right"></i>', data.page===totalPages, false);
  document.getElementById('logsPagination').innerHTML = pagesHtml;
  document.querySelectorAll('#logsPagination .page-btn[data-p]').forEach(b=>{
    b.addEventListener('click', ()=>{ logsState.page = parseInt(b.dataset.p); loadLogs().catch(showApiError); });
  });
}
const debouncedLogSearch = debounce(()=>{ logsState.page=1; loadLogs().catch(showApiError); }, 350);
document.getElementById('logSearch').addEventListener('input', (e)=>{logsState.search=e.target.value; debouncedLogSearch();});
document.getElementById('logProtoFilter').addEventListener('change', (e)=>{logsState.proto=e.target.value; logsState.page=1; loadLogs().catch(showApiError);});
document.getElementById('logsSortFilter').addEventListener('change', (e)=>{logsState.sort=e.target.value; logsState.page=1; loadLogs().catch(showApiError);});
document.getElementById('logsPerPage').addEventListener('change', (e)=>{logsState.perPage=parseInt(e.target.value); logsState.page=1; loadLogs().catch(showApiError);});
document.getElementById('logRefreshBtn').addEventListener('click', ()=>{
  const btn = document.getElementById('logRefreshBtn');
  btn.querySelector('i').classList.add('fa-spin');
  loadLogs().catch(showApiError).finally(()=>btn.querySelector('i').classList.remove('fa-spin'));
});
document.getElementById('logsTableBody').addEventListener('click', (e)=>{
  const el = e.target.closest('.ip-click');
  if (el) showIpDetail(el.dataset.srcip);
});

/* --- Real-time Logs: date range popover --- */
function updateLogsDateBtnLabel(){
  const label = document.getElementById('logsDateBtnLabel');
  const btn = document.getElementById('logsDateBtn');
  if (logsState.dateFrom && logsState.dateTo){
    label.textContent = logsState.dateFrom === logsState.dateTo
      ? fmtDateID(logsState.dateFrom)
      : `${fmtDateID(logsState.dateFrom)} – ${fmtDateID(logsState.dateTo)}`;
    btn.classList.add('active');
  } else if (logsState.dateFrom){
    label.textContent = fmtDateID(logsState.dateFrom);
    btn.classList.add('active');
  } else {
    label.textContent = 'Pilih Tanggal';
    btn.classList.remove('active');
  }
}
document.getElementById('logsDateBtn').addEventListener('click', (e)=>{
  e.stopPropagation();
  document.getElementById('logsDatePopover').classList.toggle('open');
});
document.getElementById('logsDatePopover').addEventListener('click', (e)=> e.stopPropagation());
document.addEventListener('click', ()=> document.getElementById('logsDatePopover').classList.remove('open'));
document.getElementById('logsDateApply').addEventListener('click', ()=>{
  const from = document.getElementById('logsDateFrom').value;
  const to = document.getElementById('logsDateTo').value;
  logsState.dateFrom = from;
  logsState.dateTo = to && from && to < from ? from : to; // guard reversed range
  logsState.page = 1;
  updateLogsDateBtnLabel();
  document.getElementById('logsDatePopover').classList.remove('open');
  loadLogs().catch(showApiError);
});
document.getElementById('logsDateClear').addEventListener('click', ()=>{
  document.getElementById('logsDateFrom').value = '';
  document.getElementById('logsDateTo').value = '';
  logsState.dateFrom = ''; logsState.dateTo = '';
  logsState.page = 1;
  updateLogsDateBtnLabel();
  document.getElementById('logsDatePopover').classList.remove('open');
  loadLogs().catch(showApiError);
});


/* ================= PAGE 3: TRAFFIC ANALYSIS ================= */
async function loadTraffic(){
  const t = await apiFetch('/api/traffic-analysis');
  STATE.trafficAnalysis = t;
  renderTraffic(t);
}
function renderTraffic(t){
  document.getElementById('trafficStats').innerHTML = `
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon blue"><i class="fa-solid fa-database"></i></div></div>
      <div class="stat-label">Total Traffic</div>
      <div class="stat-value">${fmtMB(t.total_traffic_mb)}</div>
      <div class="stat-delta up"><span class="muted">${fmtDateID(t.range_start)} – ${fmtDateID(t.range_end)}</span></div>
    </div>
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon purple"><i class="fa-solid fa-network-wired"></i></div></div>
      <div class="stat-label">Total Koneksi</div>
      <div class="stat-value">${fmtNum(t.total_koneksi)}</div>
      <div class="stat-delta up"><span class="muted">seluruh periode</span></div>
    </div>
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon teal"><i class="fa-solid fa-desktop"></i></div></div>
      <div class="stat-label">IP Unik</div>
      <div class="stat-value">${t.unique_ip}</div>
      <div class="stat-delta up"><span class="muted">host berbeda</span></div>
    </div>
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon amber"><i class="fa-solid fa-clock"></i></div></div>
      <div class="stat-label">Rata-rata per Jam</div>
      <div class="stat-value">${fmtBytes(t.avg_per_hour_kb*1000)}</div>
      <div class="stat-delta up"><span class="muted">semua host</span></div>
    </div>`;

  makeChart('trafficTrend', document.getElementById('chartTrafficTrend'), {
    type:'bar',
    data:{labels:t.daily_trend.map(d=>d.date), datasets:[{data:t.daily_trend.map(d=>d.traffic_mb), backgroundColor:'#3b6df0', borderRadius:5, maxBarThickness:26}]},
    options:{plugins:{legend:{display:false}, tooltip:{callbacks:{label:c=>fmtMB(c.parsed.y)}}}, scales:{y:{beginAtZero:true, grid:{color:'#eef1f7'}, ticks:{callback:v=>v+' MB'}}, x:{grid:{display:false}}}, responsive:true, maintainAspectRatio:false}
  });

  makeChart('trafficProto', document.getElementById('chartTrafficProto'), {
    type:'doughnut',
    data:{labels:t.protocol.map(p=>p.proto), datasets:[{data:t.protocol.map(p=>p.traffic_mb), backgroundColor:t.protocol.map(p=>protoColors[p.proto]||'#94a3b8'), borderWidth:0}]},
    options:{cutout:'65%', plugins:{legend:{position:'bottom', labels:{boxWidth:10, padding:16, font:{size:11.5}}}, tooltip:{callbacks:{label:c=>`${c.label}: ${fmtMB(c.parsed)}`}}}, responsive:true, maintainAspectRatio:false}
  });

  makeChart('hourly', document.getElementById('chartHourly'), {
    type:'bar',
    data:{labels:t.hourly_profile.map(h=>h.hour), datasets:[{data:t.hourly_profile.map(h=>h.avg_kb), backgroundColor:'#7c5cff', borderRadius:4, maxBarThickness:20}]},
    options:{plugins:{legend:{display:false}, tooltip:{callbacks:{label:c=>fmtBytes(c.parsed.y*1000)}}}, scales:{y:{beginAtZero:true, grid:{color:'#eef1f7'}, ticks:{callback:v=>v+' KB'}}, x:{grid:{display:false}}}, responsive:true, maintainAspectRatio:false}
  });

  document.getElementById('fullSrcTable').innerHTML = t.top_src_ip.map((r,i)=>`
    <tr><td>${i+1}</td><td class="ip-mono">${r.ip}</td><td>${fmtMB(r.traffic_gb*1000)}</td>
    <td style="min-width:140px;"><div style="display:flex; align-items:center; gap:8px;"><div class="bar-track" style="flex:1;"><div class="bar-fill" style="width:${r.pct}%"></div></div><span style="font-weight:600; font-size:11.5px;">${r.pct}%</span></div></td></tr>`).join('');

  document.getElementById('geoipUnavailableNotice').style.display = t.geoip_available ? 'none' : 'flex';
  document.getElementById('fullDstTable').innerHTML = t.top_dst_ip.length ? t.top_dst_ip.map((r,i)=>`
    <tr><td>${i+1}</td><td class="ip-mono">${r.ip}</td>
    <td>${r.country}</td><td>${r.city}</td><td>${r.org}</td><td>${r.hostname}</td><td>${r.application}</td>
    <td>${fmtMB(r.traffic_mb)}</td>
    <td style="min-width:140px;"><div style="display:flex; align-items:center; gap:8px;"><div class="bar-track" style="flex:1;"><div class="bar-fill" style="width:${r.pct}%"></div></div><span style="font-weight:600; font-size:11.5px;">${r.pct}%</span></div></td></tr>`).join('')
    : `<tr><td colspan="9"><div class="empty-state"><i class="fa-solid fa-inbox"></i>Belum ada data (tabel raw_data kosong).</div></td></tr>`;

  document.getElementById('fullPortTable').innerHTML = t.top_port.length ? t.top_port.map((r,i)=>`
    <tr><td>${i+1}</td><td><b>${r.port}</b></td><td>${r.name}</td><td>${fmtNum(r.conn)}</td><td>${fmtMB(r.traffic_mb)}</td>
    <td style="min-width:140px;"><div style="display:flex; align-items:center; gap:8px;"><div class="bar-track" style="flex:1;"><div class="bar-fill" style="width:${r.pct}%"></div></div><span style="font-weight:600; font-size:11.5px;">${r.pct}%</span></div></td></tr>`).join('')
    : `<tr><td colspan="6"><div class="empty-state"><i class="fa-solid fa-inbox"></i>Belum ada data.</div></td></tr>`;

  makeChart('protoFull', document.getElementById('chartProtoFull'), {
    type:'pie',
    data:{labels:t.protocol.map(p=>p.proto), datasets:[{data:t.protocol.map(p=>p.traffic_mb), backgroundColor:t.protocol.map(p=>protoColors[p.proto]||'#94a3b8'), borderWidth:2, borderColor:'#fff'}]},
    options:{plugins:{legend:{position:'bottom'}}, responsive:true, maintainAspectRatio:false}
  });
  document.getElementById('protoDetailTable').innerHTML = t.protocol.map(p=>`
    <tr><td><span class="dot" style="background:${protoColors[p.proto]||'#94a3b8'}; display:inline-block; margin-right:7px;"></span><b>${p.proto}</b></td><td>${fmtNum(p.conn)}</td><td>${fmtMB(p.traffic_mb)}</td><td>${p.pct}%</td></tr>`).join('');
}

document.querySelectorAll('#trafficTabs .tab-btn').forEach(btn=>{
  btn.addEventListener('click', ()=>{
    document.querySelectorAll('#trafficTabs .tab-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.ttab-panel').forEach(p=>p.style.display='none');
    document.getElementById('ttab-'+btn.dataset.ttab).style.display='block';
  });
});

/* ================= PAGE 4: ANOMALY DETECTION ================= */
async function loadAnomaly(){
  const a = await apiFetch('/api/anomaly');
  STATE.anomaly = a;
  renderAnomaly(a);
  renderAlerts(a);
}
let anomalyState = {level:'', tipe:'', search:'', dateStart:'', dateEnd:'', page:1, perPage:25};
function renderAnomaly(a){
  document.getElementById('anomalyNavBadge').textContent = a.total;
  document.getElementById('anomalyNavBadge').style.display = a.total === 0 ? 'none' : '';

  document.getElementById('anomalyStats').innerHTML = `
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon blue"><i class="fa-solid fa-shield-halved"></i></div></div>
      <div class="stat-label">Total Anomali</div>
      <div class="stat-value">${a.total}</div>
      <div class="stat-delta up"><span class="muted">${STATE.meta ? fmtDateID(STATE.meta.range_start)+' – '+fmtDateID(STATE.meta.range_end) : ''}</span></div>
    </div>
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon rose"><i class="fa-solid fa-circle-exclamation"></i></div></div>
      <div class="stat-label">Tinggi</div>
      <div class="stat-value" style="color:#d92d43">${a.level_counts.Tinggi}</div>
      <div class="stat-delta"><span class="muted">perlu tindakan segera</span></div>
    </div>
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon amber"><i class="fa-solid fa-circle-exclamation"></i></div></div>
      <div class="stat-label">Sedang</div>
      <div class="stat-value" style="color:#b3760a">${a.level_counts.Sedang}</div>
      <div class="stat-delta"><span class="muted">perlu ditinjau</span></div>
    </div>
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon blue"><i class="fa-solid fa-circle-info"></i></div></div>
      <div class="stat-label">Rendah</div>
      <div class="stat-value" style="color:#3b6df0">${a.level_counts.Rendah}</div>
      <div class="stat-delta"><span class="muted">informational</span></div>
    </div>`;

  const typeLabels = Object.keys(a.type_counts);
  makeChart('anomalyType', document.getElementById('chartAnomalyType'), {
    type:'bar',
    data:{labels:typeLabels, datasets:[{data:typeLabels.map(k=>a.type_counts[k]), backgroundColor:['#d92d43','#b3760a','#3b6df0','#7c5cff'], borderRadius:6, maxBarThickness:44}]},
    options:{indexAxis:'y', plugins:{legend:{display:false}}, scales:{x:{beginAtZero:true, ticks:{stepSize:1}, grid:{color:'#eef1f7'}}, y:{grid:{display:false}}}, responsive:true, maintainAspectRatio:false}
  });

  // Trend anomali per hari
  const trendMap = {};
  a.items.forEach(it => { trendMap[it.tanggal] = (trendMap[it.tanggal]||0) + 1; });
  const trendDates = Object.keys(trendMap).sort();
  makeChart('anomalyTrend', document.getElementById('chartAnomalyTrend'), {
    type:'line',
    data:{labels: trendDates.map(fmtDateID), datasets:[{
      data: trendDates.map(d=>trendMap[d]), borderColor:'#7c5cff', backgroundColor:'rgba(124,92,255,.1)',
      fill:true, tension:.35, pointRadius:3, pointBackgroundColor:'#7c5cff', borderWidth:2,
    }]},
    options:{plugins:{legend:{display:false}}, scales:{x:{grid:{display:false}}, y:{beginAtZero:true, ticks:{stepSize:1}, grid:{color:'#eef1f7'}}}, responsive:true, maintainAspectRatio:false}
  });

  // Populate "Jenis Tipe" filter dropdown once
  const typeSelect = document.getElementById('anomalyTypeFilter');
  if (typeSelect.options.length <= 1){
    typeSelect.innerHTML = '<option value="">Semua Tipe</option>' + typeLabels.sort().map(t=>`<option value="${t}">${t}</option>`).join('');
  }
  // Set date range bounds once, defaulting to full range of available data
  const dateStartEl = document.getElementById('anomalyDateStart');
  const dateEndEl = document.getElementById('anomalyDateEnd');
  if (!dateStartEl.value && !dateEndEl.value && a.items.length){
    const allDates = a.items.map(it=>it.tanggal).sort();
    dateStartEl.value = allDates[0];
    dateEndEl.value = allDates[allDates.length-1];
    anomalyState.dateStart = allDates[0];
    anomalyState.dateEnd = allDates[allDates.length-1];
  }

  anomalyState.page = 1;
  renderAnomalyTable();
}
function renderAnomalyTable(){
  if (!STATE.anomaly) return;
  const { level, tipe, search, dateStart, dateEnd, perPage } = anomalyState;
  const searchLc = search.trim().toLowerCase();
  const items = STATE.anomaly.items.filter(it => {
    if (level && it.level !== level) return false;
    if (tipe && it.tipe !== tipe) return false;
    if (dateStart && it.tanggal < dateStart) return false;
    if (dateEnd && it.tanggal > dateEnd) return false;
    if (searchLc && !it.srcip.toLowerCase().includes(searchLc)) return false;
    return true;
  }).sort((x,y)=> (y.tanggal+y.jam).localeCompare(x.tanggal+x.jam));

  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  anomalyState.page = Math.min(Math.max(1, anomalyState.page), totalPages);
  const page = anomalyState.page;
  const start = (page-1) * perPage;
  const pageItems = items.slice(start, start + perPage);

  document.getElementById('anomalyTableBody').innerHTML = pageItems.length ? pageItems.map(it=>`
    <tr class="row-clickable" data-srcip="${it.srcip}" data-tanggal="${it.tanggal}" data-jam="${it.jam}" title="Klik untuk lihat detail">
      <td class="mono">${it.tanggal} ${it.jam}</td>
      <td><span class="badge ${levelBadgeClass(it.level)}">${it.level}</span></td>
      <td><b>${it.tipe}</b></td>
      <td><div class="user-cell"><span class="u-name">${it.user}</span><span class="u-ip">${it.srcip}</span></div></td>
      <td style="white-space:normal; max-width:340px;">${it.deskripsi}</td>
      <td class="mono">${it.score}</td>
    </tr>`).join('') : `<tr><td colspan="6"><div class="empty-state"><i class="fa-solid fa-circle-check"></i>Tidak ada anomali yang cocok dengan filter ini.</div></td></tr>`;

  document.getElementById('anomalyCount').textContent = `Menampilkan ${total ? start+1 : 0}–${Math.min(start+perPage, total)} dari ${fmtNum(total)} anomali`;

  let pagesHtml = '';
  const addBtn = (p, label, disabled, active) => pagesHtml += `<button class="page-btn ${active?'active':''}" ${disabled?'disabled':''} data-p="${p}">${label}</button>`;
  addBtn(page-1, '<i class="fa-solid fa-chevron-left"></i>', page===1, false);
  let pages = [];
  if (totalPages <= 5) { for(let i=1;i<=totalPages;i++) pages.push(i); }
  else {
    pages.push(1);
    let lo = Math.max(2, page-1), hi = Math.min(totalPages-1, page+1);
    if (lo>2) pages.push('...');
    for(let i=lo;i<=hi;i++) pages.push(i);
    if (hi<totalPages-1) pages.push('...');
    pages.push(totalPages);
  }
  pages.forEach(p=>{
    if (p==='...') pagesHtml += `<span class="page-btn" style="border:none; cursor:default;">…</span>`;
    else addBtn(p, p, false, p===page);
  });
  addBtn(page+1, '<i class="fa-solid fa-chevron-right"></i>', page===totalPages, false);
  document.getElementById('anomalyPagination').innerHTML = pagesHtml;
  document.querySelectorAll('#anomalyPagination .page-btn[data-p]').forEach(b=>{
    b.addEventListener('click', ()=>{ anomalyState.page = parseInt(b.dataset.p); renderAnomalyTable(); });
  });
}
const debouncedAnomalySearch = debounce(()=>{ anomalyState.page=1; renderAnomalyTable(); }, 350);
document.getElementById('anomalyLevelFilter').addEventListener('change', (e)=>{ anomalyState.level=e.target.value; anomalyState.page=1; renderAnomalyTable(); });
document.getElementById('anomalyTypeFilter').addEventListener('change', (e)=>{ anomalyState.tipe=e.target.value; anomalyState.page=1; renderAnomalyTable(); });
document.getElementById('anomalySearchIp').addEventListener('input', (e)=>{ anomalyState.search=e.target.value; debouncedAnomalySearch(); });
document.getElementById('anomalyDateStart').addEventListener('change', (e)=>{ anomalyState.dateStart=e.target.value; anomalyState.page=1; renderAnomalyTable(); });
document.getElementById('anomalyDateEnd').addEventListener('change', (e)=>{ anomalyState.dateEnd=e.target.value; anomalyState.page=1; renderAnomalyTable(); });
document.getElementById('anomalyPerPage').addEventListener('change', (e)=>{ anomalyState.perPage=parseInt(e.target.value); anomalyState.page=1; renderAnomalyTable(); });
document.getElementById('anomalyRefreshBtn').addEventListener('click', ()=>{
  const btn = document.getElementById('anomalyRefreshBtn');
  btn.querySelector('i').classList.add('fa-spin');
  loadAnomaly().catch(showApiError).finally(()=> btn.querySelector('i').classList.remove('fa-spin'));
});
document.getElementById('anomalyTableBody').addEventListener('click', (e)=>{
  const tr = e.target.closest('tr.row-clickable');
  if (tr) showAnomalyDetail(tr.dataset.srcip, tr.dataset.tanggal, tr.dataset.jam);
});

/* ================= PAGE 5/6: REPORTS ================= */
document.querySelectorAll('[data-rtab]').forEach(btn=>{
  btn.addEventListener('click', ()=>{
    document.querySelectorAll('[data-rtab]').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('rtab-bulanan').style.display = btn.dataset.rtab==='bulanan' ? 'block':'none';
    document.getElementById('rtab-tahunan').style.display = btn.dataset.rtab==='tahunan' ? 'block':'none';
  });
});

const monthNamesId = {'01':'Januari','02':'Februari','03':'Maret','04':'April','05':'Mei','06':'Juni','07':'Juli','08':'Agustus','09':'September','10':'Oktober','11':'November','12':'Desember'};

async function loadMonthlyReport(ym){
  const data = await apiFetch('/api/reports/monthly?ym=' + encodeURIComponent(ym));
  STATE.monthlyReport = {ym, rows: data.rows};
  renderMonthlyCharts(data.rows);
}
function renderMonthlyCharts(rows){
  const hasData = rows.length > 0;
  document.getElementById('monthlyChartsWrap').style.display = hasData ? '' : 'none';
  document.getElementById('monthlyEmptyCard').style.display = hasData ? 'none' : '';
  if (!hasData) { destroyChart('monthlyTrafficKoneksi'); destroyChart('monthlyIpAnomali'); return; }

  const labels = rows.map(r=>fmtDateID(r.tanggal).replace(/ \d{4}$/,''));

  makeChart('monthlyTrafficKoneksi', document.getElementById('chartMonthlyTrafficKoneksi'), {
    type:'bar',
    data:{ labels, datasets:[
      { type:'bar', label:'Total Traffic (MB)', data: rows.map(r=>r.total_traffic_mb), backgroundColor:'#3b6df0', borderRadius:5, maxBarThickness:26, yAxisID:'y' },
      { type:'line', label:'Total Koneksi', data: rows.map(r=>r.total_koneksi), borderColor:'#7c5cff', backgroundColor:'#7c5cff', tension:.35, borderWidth:2.5, pointRadius:3, pointBackgroundColor:'#7c5cff', yAxisID:'y1' },
    ]},
    options:{
      plugins:{ legend:{position:'top', align:'end', labels:{boxWidth:10, usePointStyle:true, padding:16, font:{size:11.5}}},
        tooltip:{callbacks:{label:c=> c.dataset.label + ': ' + (c.dataset.yAxisID==='y' ? fmtMB(c.parsed.y) : fmtNum(c.parsed.y)) }} },
      scales:{
        y:{ beginAtZero:true, grid:{color:'#eef1f7'}, ticks:{callback:v=>v+' MB'}, title:{display:true, text:'Traffic (MB)', font:{size:11}} },
        y1:{ beginAtZero:true, position:'right', grid:{display:false}, ticks:{callback:v=>fmtNum(v)}, title:{display:true, text:'Koneksi', font:{size:11}} },
        x:{ grid:{display:false} },
      },
      responsive:true, maintainAspectRatio:false, interaction:{mode:'index', intersect:false},
    }
  });

  makeChart('monthlyIpAnomali', document.getElementById('chartMonthlyIpAnomali'), {
    type:'bar',
    data:{ labels, datasets:[
      { type:'bar', label:'IP Unik', data: rows.map(r=>r.ip_unik), backgroundColor:'#0fb5ae', borderRadius:5, maxBarThickness:26, yAxisID:'y' },
      { type:'line', label:'Jumlah Anomali', data: rows.map(r=>r.jumlah_anomali), borderColor:'#d92d43', backgroundColor:'#d92d43', tension:.35, borderWidth:2.5, pointRadius:3, pointBackgroundColor:'#d92d43', yAxisID:'y1' },
    ]},
    options:{
      plugins:{ legend:{position:'top', align:'end', labels:{boxWidth:10, usePointStyle:true, padding:16, font:{size:11.5}}},
        tooltip:{callbacks:{label:c=> c.dataset.label + ': ' + fmtNum(c.parsed.y) }} },
      scales:{
        y:{ beginAtZero:true, grid:{color:'#eef1f7'}, ticks:{stepSize:1}, title:{display:true, text:'IP Unik', font:{size:11}} },
        y1:{ beginAtZero:true, position:'right', grid:{display:false}, ticks:{stepSize:1}, title:{display:true, text:'Anomali', font:{size:11}} },
        x:{ grid:{display:false} },
      },
      responsive:true, maintainAspectRatio:false, interaction:{mode:'index', intersect:false},
    }
  });
}
document.getElementById('monthSelect').addEventListener('change', (e)=>loadMonthlyReport(e.target.value).catch(showApiError));
document.getElementById('downloadMonthlyCsv').addEventListener('click', ()=>{
  const {ym, rows} = STATE.monthlyReport;
  let csv = 'Tanggal;Total Traffic (MB);Total Koneksi;IP Unik;Top Port;Top Protocol;Jumlah Anomali\n';
  rows.forEach(r=>{ csv += `${r.tanggal};${r.total_traffic_mb};${r.total_koneksi};${r.ip_unik};${r.top_port};${r.top_protocol};${r.jumlah_anomali}\n`; });
  downloadCsv(csv, `laporan_bulanan_${ym}.csv`);
});

async function loadYearlyReport(year){
  const data = await apiFetch('/api/reports/yearly?year=' + encodeURIComponent(year));
  STATE.yearlyReport = {year, rows: data.rows};
  renderYearlyCharts(data.rows);
}
function renderYearlyCharts(rows){
  const hasData = rows.some(r=>r.total_traffic_mb !== null);
  document.getElementById('yearlyChartsWrap').style.display = hasData ? '' : 'none';
  document.getElementById('yearlyEmptyCard').style.display = hasData ? 'none' : '';
  if (!hasData) { destroyChart('yearlyTrafficKoneksi'); destroyChart('yearlyIpAnomali'); return; }

  const labels = rows.map(r=>r.bulan.slice(0,3));

  makeChart('yearlyTrafficKoneksi', document.getElementById('chartYearlyTrafficKoneksi'), {
    type:'bar',
    data:{ labels, datasets:[
      { type:'bar', label:'Total Traffic (MB)', data: rows.map(r=>r.total_traffic_mb), backgroundColor:'#3b6df0', borderRadius:5, maxBarThickness:34, yAxisID:'y' },
      { type:'line', label:'Total Koneksi', data: rows.map(r=>r.total_koneksi), borderColor:'#7c5cff', backgroundColor:'#7c5cff', tension:.35, borderWidth:2.5, pointRadius:3, pointBackgroundColor:'#7c5cff', yAxisID:'y1', spanGaps:true },
    ]},
    options:{
      plugins:{ legend:{position:'top', align:'end', labels:{boxWidth:10, usePointStyle:true, padding:16, font:{size:11.5}}},
        tooltip:{callbacks:{label:c=> c.dataset.label + ': ' + (c.dataset.yAxisID==='y' ? fmtMB(c.parsed.y) : fmtNum(c.parsed.y)) }} },
      scales:{
        y:{ beginAtZero:true, grid:{color:'#eef1f7'}, ticks:{callback:v=>v+' MB'}, title:{display:true, text:'Traffic (MB)', font:{size:11}} },
        y1:{ beginAtZero:true, position:'right', grid:{display:false}, ticks:{callback:v=>fmtNum(v)}, title:{display:true, text:'Koneksi', font:{size:11}} },
        x:{ grid:{display:false} },
      },
      responsive:true, maintainAspectRatio:false, interaction:{mode:'index', intersect:false},
    }
  });

  makeChart('yearlyIpAnomali', document.getElementById('chartYearlyIpAnomali'), {
    type:'bar',
    data:{ labels, datasets:[
      { type:'bar', label:'IP Unik', data: rows.map(r=>r.ip_unik), backgroundColor:'#0fb5ae', borderRadius:5, maxBarThickness:34, yAxisID:'y' },
      { type:'line', label:'Jumlah Anomali', data: rows.map(r=>r.jumlah_anomali), borderColor:'#d92d43', backgroundColor:'#d92d43', tension:.35, borderWidth:2.5, pointRadius:3, pointBackgroundColor:'#d92d43', yAxisID:'y1', spanGaps:true },
    ]},
    options:{
      plugins:{ legend:{position:'top', align:'end', labels:{boxWidth:10, usePointStyle:true, padding:16, font:{size:11.5}}},
        tooltip:{callbacks:{label:c=> c.dataset.label + ': ' + fmtNum(c.parsed.y) }} },
      scales:{
        y:{ beginAtZero:true, grid:{color:'#eef1f7'}, ticks:{stepSize:1}, title:{display:true, text:'IP Unik', font:{size:11}} },
        y1:{ beginAtZero:true, position:'right', grid:{display:false}, ticks:{stepSize:1}, title:{display:true, text:'Anomali', font:{size:11}} },
        x:{ grid:{display:false} },
      },
      responsive:true, maintainAspectRatio:false, interaction:{mode:'index', intersect:false},
    }
  });
}
document.getElementById('yearSelect').addEventListener('change', (e)=>loadYearlyReport(e.target.value).catch(showApiError));
document.getElementById('downloadYearlyCsv').addEventListener('click', ()=>{
  const {year, rows} = STATE.yearlyReport;
  let csv = 'Bulan;Total Traffic (MB);Total Koneksi;IP Unik;Rata-rata per Hari (MB);Jumlah Anomali\n';
  rows.forEach(r=>{ csv += `${r.bulan};${r.total_traffic_mb??'-'};${r.total_koneksi??'-'};${r.ip_unik??'-'};${r.avg_per_hari_mb??'-'};${r.jumlah_anomali??'-'}\n`; });
  downloadCsv(csv, `laporan_tahunan_${year}.csv`);
});
function downloadCsv(csv, filename){
  const BOM = '\uFEFF'; // supaya Excel baca UTF-8 dengan benar (bukan wajib buat data ini, tapi aman kalau nanti ada karakter non-ASCII)
  const blob = new Blob([BOM + csv], {type:'text/csv;charset=utf-8;'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/* ================= PAGE: ALERTS ================= */
const alertIconMap = {'Port Scan':'fa-radar','Data Exfiltration':'fa-cloud-arrow-up','Unusual Traffic':'fa-shuffle','Suspicious App Traffic':'fa-triangle-exclamation'};
const alertSevRank = {'Tinggi':3, 'Sedang':2, 'Rendah':1};
const alertSevMeta = {
  'Tinggi': {cls:'sev-high', label:'HIGH'},
  'Sedang': {cls:'sev-medium', label:'MEDIUM'},
  'Rendah': {cls:'sev-low', label:'LOW'},
};
const ALERTS_HOST_PAGE_SIZE = 10;
const alertsFilterState = { severity:'', tipe:'', sort:'terbaru', page:1 };

function renderAlerts(a){
  // populate "Jenis Alert" dropdown once, based on types actually present
  const typeSelect = document.getElementById('alertTypeFilter');
  if (typeSelect.options.length <= 1){
    const types = [...new Set(a.items.map(it=>it.tipe))].sort();
    typeSelect.innerHTML = '<option value="">Semua Jenis</option>' + types.map(t=>`<option value="${t}">${t}</option>`).join('');
  }
  renderAlertsSummary(a);
  renderAlertsList(a);
}

function renderAlertsSummary(a){
  document.getElementById('alertsStats').innerHTML = `
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon rose"><i class="fa-solid fa-shield-halved"></i></div></div>
      <div class="stat-label">Total Alerts</div>
      <div class="stat-value">${a.total}</div>
      <div class="stat-delta"><span class="muted">(periode dipilih)</span></div>
    </div>
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon rose"><i class="fa-solid fa-arrow-trend-up"></i></div></div>
      <div class="stat-label">Severity Tinggi</div>
      <div class="stat-value" style="color:#d92d43">${a.level_counts.Tinggi}</div>
    </div>
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon amber"><i class="fa-solid fa-circle-exclamation"></i></div></div>
      <div class="stat-label">Severity Sedang</div>
      <div class="stat-value" style="color:#b3760a">${a.level_counts.Sedang}</div>
    </div>
    <div class="card stat-card">
      <div class="stat-top"><div class="stat-icon blue"><i class="fa-solid fa-arrow-trend-up"></i></div></div>
      <div class="stat-label">Severity Rendah</div>
      <div class="stat-value" style="color:#3b6df0">${a.level_counts.Rendah}</div>
    </div>`;
}

function renderAlertsList(a){
  if (!a) return;
  const { severity, tipe, sort, page } = alertsFilterState;

  // 1) filter individual alert items
  const filtered = a.items.filter(it => (!severity || it.level === severity) && (!tipe || it.tipe === tipe));

  // 2) group by host (srcip)
  const hostsMap = new Map();
  filtered.forEach(it => {
    if (!hostsMap.has(it.srcip)) hostsMap.set(it.srcip, []);
    hostsMap.get(it.srcip).push(it);
  });
  let hosts = [...hostsMap.entries()].map(([srcip, entries]) => {
    const sorted = [...entries].sort((x,y)=> (y.tanggal+y.jam).localeCompare(x.tanggal+x.jam));
    const topSeverity = sorted.reduce((worst, e) => alertSevRank[e.level] > alertSevRank[worst] ? e.level : worst, 'Rendah');
    const totalKoneksi = entries.reduce((s,e)=> s + (e.jumlah_koneksi||0), 0);
    const maxTujuan = Math.max(...entries.map(e=>e.jumlah_tujuan_unik||0));
    const maxPort = Math.max(...entries.map(e=>e.jumlah_port_unik||0));
    const distinctHours = new Set(entries.map(e=>e.tanggal+' '+e.jam)).size;
    return { srcip, entries: sorted, topSeverity, totalKoneksi, maxTujuan, maxPort, distinctHours, latestKey: sorted[0].tanggal+sorted[0].jam };
  });

  // 3) sort host groups
  if (sort === 'terbaru') hosts.sort((x,y)=> y.latestKey.localeCompare(x.latestKey));
  else if (sort === 'terlama') hosts.sort((x,y)=> x.latestKey.localeCompare(y.latestKey));
  else if (sort === 'severity') hosts.sort((x,y)=> alertSevRank[y.topSeverity] - alertSevRank[x.topSeverity] || y.latestKey.localeCompare(x.latestKey));

  // 4) paginate: fill each page with whole host cards until ~ALERTS_HOST_PAGE_SIZE individual alerts are reached
  const totalAlerts = filtered.length;
  const pages = [];
  let bucket = [], bucketCount = 0;
  hosts.forEach(h => {
    if (bucketCount > 0 && bucketCount + h.entries.length > ALERTS_HOST_PAGE_SIZE){
      pages.push(bucket);
      bucket = []; bucketCount = 0;
    }
    bucket.push(h);
    bucketCount += h.entries.length;
  });
  if (bucket.length) pages.push(bucket);
  if (!pages.length) pages.push([]);

  const safePage = Math.min(Math.max(1, page), pages.length);
  alertsFilterState.page = safePage;
  const pageHosts = pages[safePage - 1];
  const startIdx = pages.slice(0, safePage - 1).reduce((s,p)=> s + p.reduce((s2,h)=>s2+h.entries.length,0), 0) + 1;
  const endIdx = startIdx + pageHosts.reduce((s,h)=>s+h.entries.length,0) - 1;

  document.getElementById('alertsList').innerHTML = pageHosts.length ? pageHosts.map(h=>{
    const sm = alertSevMeta[h.topSeverity];
    const timelineRows = h.entries.map(e=>{
      const c = levelIconColor(e.level);
      return `<div class="ahc-timeline-row">
        <div class="ahc-tl-time">${e.jam}</div>
        <div class="ahc-tl-icon" style="background:${c.bg}; color:${c.fg};"><i class="fa-solid ${alertIconMap[e.tipe]||'fa-bell'}"></i></div>
        <div class="ahc-tl-mid">
          <div class="ahc-tl-type">${e.tipe}</div>
          <div class="ahc-tl-stats">${fmtNum(e.jumlah_koneksi)} koneksi &middot; ${fmtNum(e.jumlah_tujuan_unik)} tujuan &middot; ${fmtNum(e.jumlah_port_unik)} port</div>
        </div>
        <span class="badge ${levelBadgeClass(e.level)}">${e.level}</span>
      </div>`;
    }).join('');
    return `<div class="alert-host-card ${sm.cls}" data-srcip="${h.srcip}">
      <div class="ahc-bar"></div>
      <div class="ahc-body">
        <div class="ahc-top">
          <div>
            <span class="ahc-sev-badge ${sm.cls}">${sm.label}</span>
            <div class="ahc-ip">${h.srcip}</div>
            <div class="ahc-desc">Aktivitas mencurigakan terdeteksi selama ${h.distinctHours} jam</div>
          </div>
          <button class="ahc-toggle" data-toggle-host="${h.srcip}"><i class="fa-solid fa-chevron-down"></i></button>
        </div>
        <div class="ahc-stat-row">
          <div class="ahc-stat-box"><div class="n"><i class="fa-solid fa-diagram-project"></i>${fmtNum(h.totalKoneksi)}</div><div class="l">Total Koneksi</div></div>
          <div class="ahc-stat-box"><div class="n"><i class="fa-solid fa-bullseye"></i>${fmtNum(h.maxTujuan)}</div><div class="l">Tujuan Unik</div></div>
          <div class="ahc-stat-box"><div class="n"><i class="fa-solid fa-plug"></i>${fmtNum(h.maxPort)}</div><div class="l">Port Berbeda</div></div>
        </div>
        <div class="ahc-main" data-host-content>
          <div class="ahc-timeline">${timelineRows}</div>
          <div class="ahc-side">
            <button class="ahc-host-btn" data-view-host="${h.srcip}"><i class="fa-solid fa-user-shield"></i>Lihat Aktivitas Host</button>
          </div>
        </div>
      </div>
    </div>`;
  }).join('') : `<div class="card"><div class="empty-state"><i class="fa-solid fa-bell-slash"></i>Tidak ada alert yang cocok dengan filter ini.</div></div>`;

  renderAlertsPagination(totalAlerts, totalAlerts ? startIdx : 0, Math.min(endIdx, totalAlerts), pages.length);
}

function renderAlertsPagination(total, from, to, totalPages){
  totalPages = Math.max(1, totalPages);
  document.getElementById('alertsPaginationInfo').textContent = total
    ? `Menampilkan ${from} – ${to} dari ${total} alerts`
    : 'Menampilkan 0 dari 0 alerts';
  const { page } = alertsFilterState;
  let btns = `<button class="page-btn" id="alertsPrevBtn" ${page<=1?'disabled':''}><i class="fa-solid fa-chevron-left"></i></button>`;
  for (let p=1; p<=totalPages; p++){
    btns += `<button class="page-btn ${p===page?'active':''}" data-alerts-page="${p}">${p}</button>`;
  }
  btns += `<button class="page-btn" id="alertsNextBtn" ${page>=totalPages?'disabled':''}><i class="fa-solid fa-chevron-right"></i></button>`;
  document.getElementById('alertsPageBtns').innerHTML = btns;
}

document.getElementById('severityPills').addEventListener('click', (e)=>{
  const btn = e.target.closest('.severity-pill');
  if (!btn) return;
  document.querySelectorAll('#severityPills .severity-pill').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  alertsFilterState.severity = btn.dataset.severity;
  alertsFilterState.page = 1;
  renderAlertsList(STATE.anomaly);
});
document.getElementById('alertTypeFilter').addEventListener('change', (e)=>{
  alertsFilterState.tipe = e.target.value;
  alertsFilterState.page = 1;
  renderAlertsList(STATE.anomaly);
});
document.getElementById('alertSortFilter').addEventListener('change', (e)=>{
  alertsFilterState.sort = e.target.value;
  alertsFilterState.page = 1;
  renderAlertsList(STATE.anomaly);
});
document.getElementById('alertsPageBtns').addEventListener('click', (e)=>{
  const totalPages = document.querySelectorAll('#alertsPageBtns [data-alerts-page]').length;
  if (e.target.closest('#alertsPrevBtn')) alertsFilterState.page = Math.max(1, alertsFilterState.page-1);
  else if (e.target.closest('#alertsNextBtn')) alertsFilterState.page = Math.min(totalPages, alertsFilterState.page+1);
  else {
    const btn = e.target.closest('[data-alerts-page]');
    if (!btn) return;
    alertsFilterState.page = parseInt(btn.dataset.alertsPage, 10);
  }
  renderAlertsList(STATE.anomaly);
  document.getElementById('page-alerts').scrollIntoView({behavior:'smooth', block:'start'});
});
document.getElementById('alertsList').addEventListener('click', (e)=>{
  const viewBtn = e.target.closest('[data-view-host]');
  if (viewBtn){ showIpDetail(viewBtn.dataset.viewHost); return; }
  const toggleBtn = e.target.closest('[data-toggle-host]');
  if (toggleBtn){
    const card = toggleBtn.closest('.alert-host-card');
    const content = card.querySelector('[data-host-content]');
    const collapsed = content.style.display === 'none';
    content.style.display = collapsed ? '' : 'none';
    toggleBtn.classList.toggle('collapsed', !collapsed);
  }
});

/* ================= INIT ================= */
async function init(){
  try {
    const meta = await loadMeta();
    clearApiError();

    // =========================
    // 1. DATA UTAMA DASHBOARD
    // =========================
    await Promise.all([
      loadOverview(),
      loadTraffic(),
      loadAnomaly(),
      loadUserActivity(),
      loadTrafficTrend()
    ]);

    // =========================
    // 2. DATA TAMBAHAN
    // =========================
    loadLogs();

    // =========================
    // 3. REPORT BULANAN
    // =========================
    if (meta.available_months.length) {
      const lastYm =
        meta.available_months[meta.available_months.length - 1];

      document.getElementById('monthSelect').value = lastYm;
      loadMonthlyReport(lastYm);
    }

    // =========================
    // 4. REPORT TAHUNAN
    // =========================
    if (meta.available_months.length) {
      const lastYear =
        meta.available_months[meta.available_months.length - 1]
          .split('-')[0];

      document.getElementById('yearSelect').value = lastYear;
      loadYearlyReport(lastYear);
    }

  } catch (err) {
    console.error(err);
    showApiError(err);
  }
}

init();

/* cek koneksi API tiap 15 detik, independen dari load data per-halaman,
   supaya badge LIVE/OFFLINE selalu mencerminkan kondisi server saat ini */
checkConnStatus();
setInterval(checkConnStatus, 15000);
