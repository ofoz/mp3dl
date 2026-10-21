/* 管理后台：概览 / 用户 / 卡密 / 流水
   所有数据走 /api/admin/*，前端只负责展示与操作。 */
(function () {
  'use strict';

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));

  const state = {
    me: null,
    tab: 'overview',
    users: [],
    userOffset: 0,
    userTotal: 0,
    usersAll: 0,
    userQuery: '',
    lastCodes: [],
    loaded: {},
  };

  /* ---------------- 基础工具 ---------------- */
  async function api(path, opts) {
    opts = opts || {};
    const res = await fetch(path, {
      method: opts.method || 'GET',
      credentials: 'same-origin',
      headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    let payload = null;
    try { payload = await res.json(); } catch (e) { payload = null; }
    if (!res.ok) {
      const err = new Error((payload && payload.error) || ('请求失败 ' + res.status));
      err.status = res.status;
      err.payload = payload;
      throw err;
    }
    return payload;
  }

  let toastTimer = null;
  function toast(text, ms) {
    const el = $('#toast');
    el.textContent = text;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), ms || 2200);
  }

  const pad2 = (n) => String(n).padStart(2, '0');
  function timeText(ts) {
    if (!ts) return '—';
    const d = new Date(Number(ts) * 1000);
    if (Number.isNaN(d.getTime())) return '—';
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) +
      ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }

  function fmtBytes(n) {
    n = Number(n) || 0;
    if (n >= 1073741824) return (n / 1073741824).toFixed(2) + ' GB';
    if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB';
    if (n >= 1024) return (n / 1024).toFixed(0) + ' KB';
    return n + ' B';
  }

  function num(n) {
    return (Number(n) || 0).toLocaleString('zh-CN');
  }

  /* ---------------- 权限守卫 ---------------- */
  function guard(title, text, btnText) {
    $('#guardTitle').textContent = title;
    $('#guardText').textContent = text;
    if (btnText) $('#guard .btn').textContent = btnText;
    $('#guard').hidden = false;
  }

  /* ---------------- Tab ---------------- */
  function switchTab(name, silent) {
    if (!$('#tab-' + name)) name = 'overview';
    state.tab = name;
    $$('#admTabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    $$('.tabpane').forEach((s) => { s.hidden = s.id !== 'tab-' + name; });
    if (!silent) history.replaceState(null, '', '#' + name);
    loadTab(name);
  }

  function loadTab(name) {
    if (name === 'overview') return loadStats();
    if (name === 'users') return loadUsers(false);
    if (name === 'codes') return loadCodes();
    if (name === 'ledger') return loadLedger();
  }

  $('#admTabs').onclick = (e) => {
    const btn = e.target.closest('button[data-tab]');
    if (btn) switchTab(btn.dataset.tab);
  };

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-goto]');
    if (btn) switchTab(btn.dataset.goto);
  });

  /* ---------------- 顶栏 ---------------- */
  function renderMe() {
    const u = state.me;
    $('#admUser').innerHTML =
      '<span class="badge soft">管理员</span>' +
      '<span class="dim adm-mail">' + esc(u.email) + '</span>' +
      '<a class="btn sm ghost" href="/">返回站点</a>' +
      '<button class="btn sm ghost danger" id="admLogout" title="退出登录">退出登录</button>';
    $('#admLogout').onclick = doLogout;
  }

  async function doLogout() {
    const btn = $('#admLogout');
    if (btn) btn.disabled = true;
    // 会话可能已过期，失败也照样回首页当未登录处理
    try { await api('/api/auth/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
    location.href = '/';
  }

  /* ---------------- 概览 ---------------- */
  async function loadStats() {
    const grid = $('#statGrid');
    try {
      const s = await api('/api/admin/stats');
      const items = [
        { k: '注册用户', v: num(s.users), foot: '近 24h 新增 ' + num(s.users_24h) },
        { k: '钱包积分总额', v: num(s.credits_in_wallets), foot: '尚未被消费的积分', cls: 'ok' },
        { k: '下载数量', v: num(s.downloads_24h), i: '首 / 24h', foot: '累计 ' + num(s.downloads) + ' 首', cls: 'accent' },
        { k: '积分消耗', v: num(s.charged_credits_24h), i: '分 / 24h', foot: '免费额度用掉 ' + num(s.free_tracks_24h) + ' 首' },
        { k: '未使用卡密', v: num(s.codes_unused), foot: '已核销 ' + num(s.codes_used) + ' 张', cls: 'warn' },
        { k: '音频文件', v: num(s.files), foot: '缓存占用 ' + fmtBytes(s.storage_bytes) },
        { k: '下载任务', v: num(s.jobs), foot: '单曲 + 批量 + 歌单' },
        {
          k: '当前价目', v: num(s.prices.mp3), i: '积分 / 首 MP3',
          foot: '转码 ' + s.prices.transcode + ' · 无损 ' + s.prices.flac + ' · 免费 ' + s.free_daily + ' 首/天',
        },
      ];
      grid.innerHTML = items.map((it) =>
        '<div class="stat ' + (it.cls || '') + '">' +
          '<div class="k">' + it.k + '</div>' +
          '<div class="v">' + it.v + (it.i ? '<i>' + it.i + '</i>' : '') + '</div>' +
          '<div class="foot">' + it.foot + '</div>' +
        '</div>'
      ).join('');

      $('#sysInfo').innerHTML =
        '<div><b>缓存</b>：上限 ' + s.cache_limit_gb + ' GB，当前 ' + fmtBytes(s.storage_bytes) +
        '；服务每 30 分钟清理一次过期文件。</div>' +
        '<div><b>计费</b>：每日免费 ' + s.free_daily + ' 首 MP3，超出 ' + s.prices.mp3 +
        ' 积分/首；服务端转码 ' + s.prices.transcode + ' 积分/首；无损 ' + s.prices.flac + ' 积分/首。</div>' +
        '<div><b>卡密</b>：一张卡密固定面额、一次性使用，用户在前台「卡密充值」兑换后直接进余额。</div>';
    } catch (err) {
      grid.innerHTML = '<div class="empty">' + esc(err.message) + '</div>';
    }
  }

  /* ---------------- 用户 ---------------- */
  function userRow(u) {
    const self = state.me && u.id === state.me.id;
    return '<tr>' +
      '<td class="dim">' + u.id + '</td>' +
      '<td><div class="strong">' + esc(u.email) + '</div>' +
        '<div class="sub">' + esc(u.nickname || '—') + '</div></td>' +
      '<td class="num strong">' + num(u.credits) + '</td>' +
      '<td class="num">' + u.free_left + ' / ' + u.free_limit + '</td>' +
      '<td>' + (u.is_admin ? '<span class="badge soft">管理员</span>' : '<span class="badge">用户</span>') + '</td>' +
      '<td>' + (u.status ? '<span class="badge ok">正常</span>' : '<span class="badge err">禁用</span>') + '</td>' +
      '<td class="dim nowrap">' + timeText(u.created_at) + '</td>' +
      '<td class="dim nowrap">' + timeText(u.last_login_at) + '</td>' +
      '<td class="acts">' +
        '<button class="btn sm" data-act="credit" data-id="' + u.id + '">调积分</button>' +
        (self
          ? '<span class="dim" style="font-size:12px">当前账号</span>'
          : '<button class="btn sm" data-act="admin" data-id="' + u.id + '" data-admin="' + (u.is_admin ? 0 : 1) + '">' +
              (u.is_admin ? '取消管理' : '设为管理') + '</button>' +
            '<button class="btn sm" data-act="status" data-id="' + u.id + '" data-status="' + (u.status ? 0 : 1) + '">' +
              (u.status ? '禁用' : '启用') + '</button>') +
      '</td>' +
    '</tr>';
  }

  function paintUsers() {
    const tbody = $('#userTable tbody');
    if (!state.users.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="9">没有匹配的用户</td></tr>';
    } else {
      tbody.innerHTML = state.users.map(userRow).join('');
    }
    $('#userMeta').textContent = state.userQuery
      ? '匹配 ' + state.userTotal + ' 个（全站 ' + state.usersAll + ' 个），已显示 ' + state.users.length + ' 个'
      : '共 ' + state.userTotal + ' 个账号，已显示 ' + state.users.length + ' 个';
    $('#btnUserMore').hidden = state.users.length >= state.userTotal;
  }

  async function loadUsers(more) {
    try {
      const offset = more ? state.users.length : 0;
      const qs = '?limit=50&offset=' + offset + (state.userQuery ? '&q=' + encodeURIComponent(state.userQuery) : '');
      const data = await api('/api/admin/users' + qs);
      state.users = more ? state.users.concat(data.users) : data.users;
      state.userTotal = data.total;
      state.usersAll = data.users_all || data.total;
      paintUsers();
    } catch (err) {
      $('#userTable tbody').innerHTML =
        '<tr class="empty-row"><td colspan="9">' + esc(err.message) + '</td></tr>';
    }
  }

  $('#userTable tbody').onclick = async (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const user = state.users.find((x) => x.id === id);
    if (!user) return;

    if (btn.dataset.act === 'credit') { openCredit(user); return; }

    if (btn.dataset.act === 'admin') {
      const on = btn.dataset.admin === '1';
      if (!confirm((on ? '把 ' : '取消 ') + user.email + (on ? ' 设为管理员？' : ' 的管理员权限？'))) return;
      try {
        await api('/api/admin/users/' + id + '/admin', { method: 'POST', body: { is_admin: on ? 1 : 0 } });
        toast(on ? '已设为管理员' : '已取消管理员');
        loadUsers(false);
      } catch (err) { toast(err.message); }
      return;
    }

    if (btn.dataset.act === 'status') {
      const on = btn.dataset.status === '1';
      if (!confirm((on ? '启用 ' : '禁用 ') + user.email + ' ？' + (on ? '' : '\n禁用后该账号无法登录和下载。'))) return;
      try {
        await api('/api/admin/users/' + id + '/status', { method: 'POST', body: { status: on ? 1 : 0 } });
        toast(on ? '已启用' : '已禁用');
        loadUsers(false);
      } catch (err) { toast(err.message); }
    }
  };

  let userTimer = null;
  $('#userQ').oninput = (e) => {
    state.userQuery = e.target.value.trim();
    clearTimeout(userTimer);
    userTimer = setTimeout(() => loadUsers(false), 320);
  };
  $('#btnUserReload').onclick = () => loadUsers(false);
  $('#btnUserMore').onclick = () => loadUsers(true);

  /* ---------------- 调积分弹窗 ---------------- */
  let creditUser = null;
  function openCredit(user) {
    creditUser = user;
    $('#creditSub').textContent = user.email + ' · 当前 ' + user.credits + ' 积分';
    $('#creditMsg').className = 'msg';
    $('#creditAmount').value = 100;
    $('#creditMask').hidden = false;
    setTimeout(() => $('#creditAmount').focus(), 50);
  }
  function closeCredit() { $('#creditMask').hidden = true; creditUser = null; }

  $('#creditClose').onclick = (e) => { e.preventDefault(); closeCredit(); };
  $('#creditMask').onclick = (e) => { if (e.target.id === 'creditMask') closeCredit(); };
  $$('[data-quick]').forEach((b) => {
    b.onclick = () => { $('#creditAmount').value = b.dataset.quick; };
  });

  $('#btnCreditSubmit').onclick = async () => {
    if (!creditUser) return;
    const amount = parseInt($('#creditAmount').value, 10);
    const msg = $('#creditMsg');
    msg.className = 'msg';
    if (!amount) { msg.className = 'msg err'; msg.textContent = '请输入非 0 的整数'; return; }
    const btn = $('#btnCreditSubmit');
    btn.disabled = true;
    try {
      const data = await api('/api/admin/credits', {
        method: 'POST', body: { email: creditUser.email, credits: amount },
      });
      const u = state.users.find((x) => x.id === creditUser.id);
      if (u) { u.credits = data.balance; paintUsers(); }
      msg.className = 'msg ok';
      msg.textContent = (amount > 0 ? '已增加 ' : '已扣减 ') + Math.abs(amount) +
        ' 积分，当前余额 ' + data.balance;
      toast('余额已更新为 ' + data.balance);
      loadStats();
    } catch (err) {
      msg.className = 'msg err';
      msg.textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  };

  /* ---------------- 卡密 ---------------- */
  async function loadCodes() {
    const tbody = $('#codeTable tbody');
    const unused = $('#onlyUnused').checked ? '&unused=1' : '';
    try {
      const data = await api('/api/admin/codes?limit=200' + unused);
      const rows = data.codes || [];
      if (!rows.length) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="7">还没有卡密，先生成一批</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map((c) => {
        const used = Number(c.used_by) > 0;
        return '<tr>' +
          '<td class="mono">' + esc(c.code) + '</td>' +
          '<td class="num strong">' + num(c.credits) + '</td>' +
          '<td>' + (used ? '<span class="badge">已使用</span>' : '<span class="badge ok">未使用</span>') + '</td>' +
          '<td class="dim">' + (used ? esc(c.used_email || ('用户 #' + c.used_by)) : '—') + '</td>' +
          '<td class="dim nowrap">' + timeText(c.created_at) + '</td>' +
          '<td class="dim nowrap">' + timeText(c.used_at) + '</td>' +
          '<td class="dim">' + esc(c.note || '—') + '</td>' +
        '</tr>';
      }).join('');
    } catch (err) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="7">' + esc(err.message) + '</td></tr>';
    }
  }

  $('#btnGenCode').onclick = async () => {
    const credits = parseInt($('#codeCredits').value, 10);
    const count = parseInt($('#codeCount').value, 10);
    const note = $('#codeNote').value.trim();
    if (!credits || credits < 1) { toast('面额需大于 0'); return; }
    if (!count || count < 1 || count > 100) { toast('数量需在 1~100 之间'); return; }
    const btn = $('#btnGenCode');
    btn.disabled = true;
    btn.textContent = '生成中…';
    try {
      const data = await api('/api/admin/codes', { method: 'POST', body: { credits, count, note } });
      state.lastCodes = data.codes || [];
      $('#genCount').textContent = state.lastCodes.length;
      $('#genCredits').textContent = data.credits;
      $('#genCodes').textContent = state.lastCodes.join('\n');
      $('#genResult').hidden = false;
      toast('已生成 ' + state.lastCodes.length + ' 张卡密');
      loadCodes();
      loadStats();
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = '生成';
    }
  };

  $('#btnCopyCodes').onclick = async () => {
    const text = state.lastCodes.join('\n');
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast('已复制 ' + state.lastCodes.length + ' 张卡密');
    } catch (e) {
      // 非安全上下文降级
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
      toast('已复制');
    }
  };

  $('#btnSaveCodes').onclick = () => {
    if (!state.lastCodes.length) return;
    const blob = new Blob([state.lastCodes.join('\n') + '\n'], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'mp3dl-codes-' + state.lastCodes.length + 'x' + $('#genCredits').textContent + '.txt';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  $('#btnCodeReload').onclick = loadCodes;
  $('#onlyUnused').onchange = loadCodes;

  /* ---------------- 流水 ---------------- */
  const KIND = { redeem: '卡密兑换', charge: '下载消费', refund: '失败退回', admin: '后台调整' };

  async function loadLedger() {
    const tbody = $('#ledgerTable tbody');
    const limit = $('#ledgerLimit').value;
    try {
      const data = await api('/api/admin/ledger?limit=' + limit);
      const rows = data.ledger || [];
      if (!rows.length) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="6">暂无流水</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map((r) => {
        const delta = Number(r.delta) || 0;
        return '<tr>' +
          '<td class="dim nowrap">' + timeText(r.created_at) + '</td>' +
          '<td>' + esc(r.email || ('用户 #' + r.user_id)) + '</td>' +
          '<td><span class="badge">' + esc(KIND[r.kind] || r.kind || '—') + '</span></td>' +
          '<td class="num ' + (delta > 0 ? 'up' : (delta < 0 ? 'down' : 'dim')) + '">' +
            (delta > 0 ? '+' : '') + num(delta) + '</td>' +
          '<td class="num dim">' + num(r.balance) + '</td>' +
          '<td class="dim">' + esc(r.note || '—') + '</td>' +
        '</tr>';
      }).join('');
    } catch (err) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="6">' + esc(err.message) + '</td></tr>';
    }
  }

  $('#btnLedgerReload').onclick = loadLedger;
  $('#ledgerLimit').onchange = loadLedger;

  /* 浏览器前进/后退、手改 #hash 都能切页 */
  window.addEventListener('hashchange', () => {
    if (!state.me) return;
    const name = (location.hash || '').replace('#', '');
    if (name && name !== state.tab) switchTab(name, true);
  });

  /* ---------------- 启动 ---------------- */
  (async function init() {
    let me = null;
    try {
      const data = await api('/api/auth/me');
      me = data.user;
    } catch (e) {
      me = null;
    }
    if (!me) {
      guard('需要登录', '管理后台只对管理员开放，请先回到首页用管理员账号登录。', '回到首页登录');
      return;
    }
    if (!me.is_admin) {
      guard('权限不足', '当前账号 ' + me.email + ' 不是管理员。请联系站点管理员授权。', '回到首页');
      return;
    }
    state.me = me;
    renderMe();
    const hash = (location.hash || '').replace('#', '');
    switchTab(hash || 'overview', true);
  })();
})();
