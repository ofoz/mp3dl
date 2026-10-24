/* MP3库 前端（原生 JS，无第三方依赖） */
(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const state = {
    user: null,
    platforms: [],
    selected: new Set(),
    results: new Map(),      // platform -> {label,color,count,tracks,error}
    playlist: null,
    picked: new Set(),       // 歌单页勾选
    spicked: new Set(),      // 搜索结果勾选
    expanded: new Set(),     // 任务列表里展开的 job
    jobs: new Map(),         // job_id -> detail（仅轮询中的）
    polling: null,
    searching: false,        // 搜索进行中（防重入 + 驱动搜索栏边框）
    searchResetTimer: null,
    searchSeq: 0,            // 结果到达顺序，用于「谁先有资源谁靠前」排序
  };

  const pickSet = (name) => (name === 'search' ? state.spicked : state.picked);

  /* ---------------- 基础工具 ---------------- */
  function toast(msg, ms) {
    const el = $('#toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('show'), ms || 2200);
  }

  async function api(path, options) {
    const opt = Object.assign({ headers: {} }, options || {});
    if (opt.body && typeof opt.body !== 'string') {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(opt.body);
    }
    const resp = await fetch(path, Object.assign({ credentials: 'same-origin' }, opt));
    let data = null;
    try { data = await resp.json(); } catch (e) { data = {}; }
    if (!resp.ok) {
      const err = new Error(data.error || ('请求失败 ' + resp.status));
      err.payload = data;
      err.status = resp.status;
      throw err;
    }
    return data;
  }

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));

  function fmtDuration(sec) {
    sec = Number(sec) || 0;
    if (!sec) return '';
    const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
    return m + ':' + String(s).padStart(2, '0');
  }

  /* ---------------- 标签切换 ---------------- */
  function switchTab(name) {
    $$('.tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    ['search', 'playlist', 'jobs'].forEach((t) => { $('#tab-' + t).hidden = t !== name; });
    if (name === 'jobs') loadJobs();
  }
  $$('.tabs button').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));

  /* ---------------- 用户区 ---------------- */
  function walletOf() {
    const w = (state.user && state.user.wallet) || {};
    return {
      credits: w.credits || 0,
      free_left: w.free_left || 0,
      free_limit: w.free_limit || 0,
      prices: w.prices || {},
    };
  }

  /* 后端每次下载都会回一份钱包快照，前端直接对齐，避免自己去猜 */
  function applyWallet(w) {
    if (!state.user || !w) return;
    state.user.wallet = w;
    renderUser();
    if (state.results.size) renderResults();
    updateSelBar();
  }

  function renderUser() {
    const box = $('#userArea');
    if (!state.user) {
      box.innerHTML = '<button class="btn sm" id="btnLogin">登录</button>' +
        '<button class="btn sm primary" id="btnRegister">注册</button>';
      $('#btnLogin').onclick = () => openAuth('login');
      $('#btnRegister').onclick = () => openAuth('register');
      return;
    }
    const u = state.user;
    const w = walletOf();
    const initial = (u.nickname || u.email || '?').slice(0, 1).toUpperCase();
    box.innerHTML =
      '<div class="userbox">' +
        '<span class="badge credits" title="积分余额">' + w.credits + ' 积分</span>' +
        '<span class="badge free" title="今日免费额度剩余 / 每日上限">免费 ' + w.free_left + '/' + w.free_limit + '</span>' +
        '<button class="btn sm gold" id="btnPay">卡密充值</button>' +
        (u.is_admin ? '<a class="btn sm admin-link" href="/admin" title="管理后台">后台</a>' : '') +
        '<div class="usermenu">' +
          '<button class="user-trigger" id="btnMenu" aria-haspopup="true" aria-expanded="false" title="账号菜单">' +
            '<span class="avatar">' + esc(initial) + '</span>' +
            '<span class="uname">' + esc(u.nickname || u.email) + '</span>' +
            '<svg class="caret" viewBox="0 0 12 12" aria-hidden="true">' +
              '<path d="M2.5 4.5 6 8l3.5-3.5"/></svg>' +
          '</button>' +
          '<div class="user-menu" id="userMenu" role="menu" hidden>' +
            '<div class="um-head">' +
              '<span class="avatar lg">' + esc(initial) + '</span>' +
              '<div class="um-id">' +
                '<div class="um-name">' + esc(u.nickname || '未命名') + '</div>' +
                '<div class="um-mail">' + esc(u.email) + '</div>' +
              '</div>' +
            '</div>' +
            '<div class="um-stat">' +
              '<span>积分 <b>' + w.credits + '</b></span>' +
              '<span>今日免费 <b>' + w.free_left + '/' + w.free_limit + '</b></span>' +
            '</div>' +
            '<div class="um-sep"></div>' +
            '<button class="um-item" data-act="wallet" role="menuitem">积分明细 / 卡密充值</button>' +
            (u.is_admin ? '<a class="um-item" href="/admin" role="menuitem">管理后台</a>' : '') +
            '<button class="um-item danger" data-act="logout" role="menuitem">退出登录</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    $('#btnPay').onclick = () => openPay('');
    bindUserMenu();
  }

  /* 账号下拉菜单：点头像/昵称展开，点别处或按 Esc 收起 */
  function closeUserMenu() {
    const menu = $('#userMenu');
    const btn = $('#btnMenu');
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    if (btn) btn.setAttribute('aria-expanded', 'false');
  }

  function bindUserMenu() {
    const btn = $('#btnMenu');
    const menu = $('#userMenu');
    if (!btn || !menu) return;
    btn.onclick = (e) => {
      e.stopPropagation();
      const willOpen = menu.hidden;
      menu.hidden = !willOpen;
      btn.setAttribute('aria-expanded', String(willOpen));
    };
    menu.onclick = (e) => {
      const item = e.target.closest('[data-act]');
      if (!item) return;
      const act = item.dataset.act;
      closeUserMenu();
      if (act === 'wallet') openPay('');
      else if (act === 'logout') doLogout();
    };
  }

  document.addEventListener('click', (e) => {
    if (!e.target.closest('.usermenu')) closeUserMenu();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeUserMenu();
  });

  async function refreshMe() {
    try {
      const data = await api('/api/auth/me');
      state.user = data.user;
    } catch (e) { state.user = null; }
    renderUser();
  }

  async function doLogout() {
    // 会话可能已经在服务端过期，这里失败也照样按「已退出」处理
    try { await api('/api/auth/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
    state.user = null;
    renderUser();
    renderChips();
    if (state.results.size) renderResults();
    toast('已退出登录');
  }

  /* ---------------- 登录 / 注册弹窗 ---------------- */
  let authMode = 'login';
  function openAuth(mode) {
    const next = mode || 'login';
    // 切换模式时清空密码，避免「注册填的密码」残留到登录框（反之亦然）
    if (next !== authMode) {
      $('#authPassword').value = '';
      $('#authPassword2').value = '';
    }
    authMode = next;
    const isReg = authMode === 'register';
    $('#authTitle').textContent = isReg ? '注册' : '登录';
    $('#authSub').textContent = isReg
      ? '注册即可下载，每天 10 首免费额度'
      : '登录后可下载，每天 10 首免费 MP3';
    $('#nickField').hidden = !isReg;
    $('#confirmField').hidden = !isReg;
    // 注册要让浏览器提示「生成强密码」，登录则用已保存的口令
    $('#authPassword').autocomplete = isReg ? 'new-password' : 'current-password';
    $('#authPassword').placeholder = isReg ? '至少 6 位' : '请输入密码';
    $('#authSubmit').textContent = isReg ? '注册并登录' : '登录';
    $('#authSwitch').textContent = isReg ? '已有账号？登录' : '没有账号？注册';
    $('#authMsg').className = 'msg';
    $('#authMask').hidden = false;
    setTimeout(() => $('#authEmail').focus(), 50);
  }
  function closeAuth() { $('#authMask').hidden = true; }

  function authError(text) {
    const msg = $('#authMsg');
    msg.className = 'msg err';
    msg.textContent = text;
  }

  $('#authSwitch').onclick = (e) => {
    e.preventDefault();
    openAuth(authMode === 'login' ? 'register' : 'login');
  };
  $('#authMask').onclick = (e) => { if (e.target.id === 'authMask') closeAuth(); };

  /* 注册时实时比对两次密码，输错立刻提示，不用等提交 */
  $('#authPassword2').oninput = () => {
    const p1 = $('#authPassword').value;
    const p2 = $('#authPassword2').value;
    const msg = $('#authMsg');
    if (!p2) { msg.className = 'msg'; msg.textContent = ''; return; }
    if (p1 !== p2) authError('两次输入的密码不一致');
    else { msg.className = 'msg'; msg.textContent = ''; }
  };
  $('#authPassword').oninput = () => {
    if ($('#authPassword2').value) $('#authPassword2').oninput();
  };

  async function submitAuth() {
    const email = $('#authEmail').value.trim();
    const password = $('#authPassword').value;
    const password2 = $('#authPassword2').value;
    const nickname = $('#authNick').value.trim();
    const isReg = authMode === 'register';

    if (isReg) {
      if (!password) { authError('请设置登录密码'); return; }
      if (password.length < 6) { authError('密码至少 6 位'); return; }
      if (password.length > 64) { authError('密码不能超过 64 位'); return; }
      if (!password2) { authError('请再输入一次密码'); $('#authPassword2').focus(); return; }
      if (password !== password2) {
        authError('两次输入的密码不一致，请重新确认');
        $('#authPassword2').focus();
        return;
      }
    }

    const btn = $('#authSubmit');
    if (btn.disabled) return;
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = isReg ? '注册中…' : '登录中…';
    try {
      const path = isReg ? '/api/auth/register' : '/api/auth/login';
      const data = await api(path, { method: 'POST', body: { email, password, nickname } });
      state.user = data.user;
      renderUser();
      if (state.results.size) renderResults();
      closeAuth();
      toast(isReg ? '注册成功，今日可免费下载 10 首' : '欢迎回来');
    } catch (err) {
      authError(err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  $('#authSubmit').onclick = submitAuth;
  // 在弹窗里按回车直接提交（避免焦点在确认密码框时回车没反应）
  $('#authMask').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); submitAuth(); }
  });

  /* ---------------- 积分 / 卡密弹窗 ---------------- */
  const KIND_TEXT = { redeem: '卡密兑换', charge: '下载消费', refund: '失败退回', admin: '后台调整' };

  function walletHtml(w, ledger) {
    const p = w.prices || {};
    let html = '<div class="wallet-nums">' +
      '<div><b>' + (w.credits || 0) + '</b><span>积分余额</span></div>' +
      '<div><b>' + (w.free_left || 0) + '<i>/' + (w.free_limit || 0) + '</i></b><span>今日免费</span></div>' +
      '</div>';
    if (ledger && ledger.length) {
      html += '<div class="ledger">' + ledger.slice(0, 5).map((r) => (
        '<div class="row"><span>' + esc(KIND_TEXT[r.kind] || r.kind) + '</span>' +
        '<span class="' + (r.delta > 0 ? 'up' : 'down') + '">' + (r.delta > 0 ? '+' : '') + r.delta + '</span></div>'
      )).join('') + '</div>';
    }
    return html;
  }

  function syncPriceRules(w) {
    const p = w.prices || {};
    if (p.mp3 != null) $('#ruleMp3').textContent = p.mp3;
    if (p.transcode != null) $('#ruleTc').textContent = p.transcode;
    if (p.flac != null) $('#ruleFlac').textContent = p.flac;
    if (w.free_limit != null) $('#ruleFree').textContent = w.free_limit;
  }

  async function openPay(reason) {
    if (!state.user) {
      if (reason) toast(reason);
      openAuth('login');
      return;
    }
    const msg = $('#payMsg');
    msg.className = reason ? 'msg err' : 'msg';
    msg.textContent = reason || '';
    const box = $('#payWallet');
    box.innerHTML = walletHtml(walletOf(), []);
    syncPriceRules(walletOf());
    $('#payMask').hidden = false;
    try {
      const d = await api('/api/auth/wallet');
      applyWallet(d.wallet);
      box.innerHTML = walletHtml(d.wallet, d.ledger);
      syncPriceRules(d.wallet);
    } catch (e) { /* 打开弹窗失败不阻塞 */ }
  }

  $('#payClose').onclick = (e) => { e.preventDefault(); $('#payMask').hidden = true; };
  $('#payMask').onclick = (e) => { if (e.target.id === 'payMask') $('#payMask').hidden = true; };

  $('#btnRedeem').onclick = async () => {
    if (!state.user) { $('#payMask').hidden = true; openAuth('login'); return; }
    const code = $('#payCode').value.trim();
    if (!code) { toast('请输入卡密'); return; }
    const msg = $('#payMsg');
    msg.className = 'msg';
    try {
      const data = await api('/api/auth/redeem', { method: 'POST', body: { code } });
      state.user = data.user;
      renderUser();
      $('#payCode').value = '';
      msg.className = 'msg ok';
      msg.textContent = '兑换成功：+' + data.added + ' 积分，当前余额 ' + data.balance;
      $('#payWallet').innerHTML = walletHtml(data.user.wallet, []);
      toast('已到账 ' + data.added + ' 积分');
    } catch (err) {
      msg.className = 'msg err';
      msg.textContent = err.message;
    }
  };

  /* ---------------- 平台 chips ---------------- */
  async function loadPlatforms() {
    const data = await api('/api/platforms');
    state.platforms = data.platforms;
    if (data.site && data.site.name) {
      $('#siteName').textContent = data.site.name;
      document.title = data.site.name + ' · 搜歌即得 MP3，歌单一键打包';
    }
    state.selected = new Set(state.platforms.filter((p) => p.default).map((p) => p.key));
    renderChips();
  }

  function renderChips() {
    const wrap = $('#chips');
    wrap.innerHTML = state.platforms.map((p) => {
      const res = state.results.get(p.key);
      const cnt = res ? (res.error ? '超时' : res.count) : '';
      return '<button class="chip' + (state.selected.has(p.key) ? ' on' : '') + '" data-key="' + p.key + '"' +
        (p.note ? ' title="' + esc(p.note) + '"' : '') + '>' +
        '<span class="dot" style="background:' + p.color + '"></span>' + esc(p.short) +
        (p.free_ok ? '' : (p.credits ? '<span class="chip-price">' + p.credits + '分</span>' : '')) +
        (cnt !== '' ? '<span class="cnt">' + cnt + '</span>' : '') + '</button>';
    }).join('');
    $$('#chips .chip').forEach((el) => {
      el.onclick = () => {
        const key = el.dataset.key;
        const meta = state.platforms.find((x) => x.key === key) || {};
        if (state.selected.has(key)) state.selected.delete(key);
        else {
          state.selected.add(key);
          if (meta.note) toast(meta.label + '：' + meta.note, 3200);
        }
        if (!state.selected.size) state.selected.add(key);
        renderChips();
      };
    });
  }

  /* ---------------- 搜索（SSE 流式） ---------------- */
  function trackRow(t, opts) {
    opts = opts || {};
    const pickName = opts.pick || 'playlist';
    const pickedSet = pickSet(pickName);
    const badges =
      (t.file_size ? '<span class="badge">' + esc(t.file_size) + '</span>' : '') +
      (t.ext ? '<span class="badge soft">' + esc(t.ext.toUpperCase()) + '</span>' : '') +
      (t.duration ? '<span class="badge">' + fmtDuration(t.duration_s) + '</span>' : '');
    const cover = t.cover_url
      ? '<img class="cover" loading="lazy" src="' + esc(t.cover_url) + '" alt="" onerror="this.style.display=\'none\'">'
      : '<div class="cover">♪</div>';

    // 价签：有免费额度就标「免费」，否则标这首的积分价
    const price = t.price || {};
    const mp3p = price.mp3 || { credits: 0, free_ok: false };
    const flacp = price.flac || { credits: 0, free_ok: false };
    const freeNow = walletOf().free_left > 0;
    const mp3Free = mp3p.free_ok && freeNow;
    const mp3Tag = mp3Free
      ? '<span class="tag-free">免费</span>'
      : (mp3p.credits ? '<span class="tag-price">' + mp3p.credits + '分</span>' : '');
    const flacTag = flacp.credits ? '<span class="tag-price">' + flacp.credits + '分</span>' : '';
    const mp3Cls = mp3Free ? 'btn sm primary' : 'btn sm gold';

    return '<div class="track' + (opts.selectable && pickedSet.has(t.track_key) ? ' sel' : '') +
      '" data-key="' + esc(t.track_key) + '">' +
      (opts.selectable ? '<input type="checkbox" class="check" data-key="' + esc(t.track_key) +
        '" data-pick="' + pickName + '"' + (pickedSet.has(t.track_key) ? ' checked' : '') + '>' : '') +
      cover +
      '<div class="info">' +
        '<div class="name">' + esc(t.song_name) + '</div>' +
        '<div class="sub">' + esc(t.singers || '未知歌手') + (t.album ? ' · ' + esc(t.album) : '') + '</div>' +
      '</div>' +
      '<div class="tags">' + badges + '</div>' +
      '<div class="acts">' +
        '<button class="' + mp3Cls + '" data-dl="mp3" data-key="' + esc(t.track_key) + '"' +
          (t.transcode ? ' title="该音源需服务端转码"' : (mp3Free ? ' title="消耗今日免费额度"' : '')) + '>MP3' + mp3Tag + '</button>' +
        '<button class="btn sm gold" data-dl="flac" data-key="' + esc(t.track_key) + '"' +
          ' title="无损 FLAC">无损' + flacTag + '</button>' +
      '</div>' +
    '</div>';
  }

  function bindTrackButtons(root) {
    $$('[data-dl]', root).forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        requestDownload(btn.dataset.key, btn.dataset.dl, btn);
      };
    });
    $$('.check[data-key]', root).forEach((cb) => {
      cb.onchange = () => {
        const name = cb.dataset.pick || 'playlist';
        const set = pickSet(name);
        const row = cb.closest('.track');
        if (cb.checked) set.add(cb.dataset.key);
        else set.delete(cb.dataset.key);
        if (row) row.classList.toggle('sel', cb.checked);
        if (name === 'search') syncSearchPicks();
        else updateSelBar();
      };
    });
  }

  /* 搜索栏 + 按钮的状态机：idle / searching（已发出请求）/ streaming（已开始收到结果）/ done */
  function setSearchPhase(phase, info) {
    const bar = $('#searchBar');
    const btn = $('#btnSearch');
    if (!bar || !btn) return;
    const opt = info || {};
    if (state.searchResetTimer) { clearTimeout(state.searchResetTimer); state.searchResetTimer = null; }

    if (phase === 'reset') phase = 'idle';
    const busy = phase === 'searching' || phase === 'streaming';
    state.searching = busy;

    bar.classList.toggle('is-searching', phase === 'searching');
    bar.classList.toggle('is-streaming', phase === 'streaming');
    btn.classList.toggle('is-busy', busy);
    btn.disabled = busy;
    btn.setAttribute('aria-busy', busy ? 'true' : 'false');

    const txt = btn.querySelector('.btn-txt') || btn;
    if (phase === 'searching') txt.textContent = '搜索中';
    else if (phase === 'streaming') txt.textContent = '已找到 ' + (opt.total || 0) + ' 首';
    else if (phase === 'done') {
      txt.textContent = '共 ' + (opt.total || 0) + ' 首';
      state.searchResetTimer = setTimeout(() => { setSearchPhase('idle'); }, 1400);
    } else txt.textContent = '搜索';
  }

  function searchTotals() {
    let n = 0, hit = 0;
    state.results.forEach((r) => {
      const c = (r.tracks || []).length;
      n += c;
      if (c) hit += 1;
    });
    return { total: n, platforms: state.results.size, hit };
  }

  function renderSearchHead(final, srcCount) {
    const status = $('#searchStatus');
    if (!status) return;
    const t = searchTotals();
    if (!t.platforms) { status.innerHTML = ''; return; }
    let meta;
    if (final) {
      if (!t.total) meta = '暂无结果';
      else {
        meta = '共 ' + t.total + ' 首 · 来自 ' + t.hit + ' 个平台';
        if (t.platforms > t.hit) meta += ' · ' + (t.platforms - t.hit) + ' 个平台无结果';
      }
    } else {
      meta = '已找到 ' + t.total + ' 首 · ' + t.platforms + '/' + (srcCount || t.platforms) + ' 个平台已返回';
    }
    status.innerHTML = '<div class="section-head"><h2>搜索结果</h2><span class="meta">' + meta + '</span></div>';
  }

  async function doSearch() {
    const q = $('#q').value.trim();
    if (!q) { toast('请输入歌名或歌手'); return; }
    if (state.searching) return;
    const starter = $('#starter');
    if (starter) starter.hidden = true;
    const feats = $('#feats');
    if (feats) feats.hidden = true;
    const hero = $('#tab-search .hero');
    if (hero) hero.classList.add('compact');
    state.results.clear();
    state.picked.clear();
    state.spicked.clear();
    state.searchSeq = 0;
    $('#results').innerHTML = '';
    $('#batchBar').innerHTML = '';
    const status = $('#searchStatus');
    // 搜索中的状态由按钮 + 搜索栏边框表达，这里先留空，等首个平台返回再出结果头
    status.innerHTML = '';
    setSearchPhase('searching');
    renderChips();

    const sources = Array.from(state.selected);
    const url = '/api/search/stream?q=' + encodeURIComponent(q) + '&platforms=' + encodeURIComponent(sources.join(','));

    if (!window.EventSource) { return searchFallback(q, sources); }

    const es = new EventSource(url);
    let settled = false;   // done / error 只会生效一次，避免 onerror 覆盖已完成的状态
    es.addEventListener('track', (ev) => {
      // 逐首到达：先在对应平台分组里落一首，立刻重绘
      const data = JSON.parse(ev.data);
      const meta = state.platforms.find((x) => x.key === data.platform) || {};
      let res = state.results.get(data.platform);
      if (!res) {
        res = { platform: data.platform, label: data.track.platform_label || meta.label || data.platform,
                count: 0, tracks: [], seq: ++state.searchSeq };
        state.results.set(data.platform, res);
      }
      if ((res.tracks || []).some((t) => t.track_key === data.track.track_key)) return;
      res.tracks.push(data.track);
      res.count = res.tracks.length;
      renderChips();
      renderResults();
      renderSearchHead(false, sources.length);
      if (!settled) setSearchPhase('streaming', { total: searchTotals().total });
    });
    es.addEventListener('platform', (ev) => {
      // 该平台搜完了：补上耗时 / 超时 / 空结果的最终态
      const data = JSON.parse(ev.data);
      const cur = state.results.get(data.platform);
      if (cur) {
        // 已经推过来的曲目是有效的：超时/异常只影响「还没出结果」，不能把已出的标成失败
        cur.count = (cur.tracks || []).length || (data.count || 0);
        if (data.elapsed) cur.elapsed = data.elapsed;
        if (data.error && !(cur.tracks || []).length) cur.error = data.error;
      } else {
        state.results.set(data.platform, {
          platform: data.platform, label: data.label, count: data.count || 0,
          elapsed: data.elapsed, error: data.error, tracks: data.tracks || [],
          seq: ++state.searchSeq,
        });
      }
      renderChips();
      renderResults();
      renderSearchHead(false, sources.length);
    });
    es.addEventListener('done', () => {
      settled = true;
      es.close();
      const t = searchTotals();
      setSearchPhase('done', { total: t.total });
      renderSearchHead(true, sources.length);
      if (!t.total) {
        $('#results').innerHTML = '<div class="card empty">没有找到相关歌曲，换个关键词或换几个平台试试</div>';
      }
    });
    es.onerror = () => {
      es.close();
      if (settled) return;
      settled = true;
      const t = searchTotals();
      if (!t.platforms) { searchFallback(q, sources); return; }
      // 已经收到部分结果就当作完成，不要退回空白
      setSearchPhase('done', { total: t.total });
      renderSearchHead(true, sources.length);
    };
  }

  async function searchFallback(q, sources) {
    setSearchPhase('searching');
    try {
      const data = await api('/api/search?q=' + encodeURIComponent(q) + '&platforms=' + encodeURIComponent(sources.join(',')));
      data.results.forEach((r, i) => { r.seq = i + 1; state.results.set(r.platform, r); });
      renderChips();
      renderResults();
      const total = data.results.reduce((n, r) => n + (r.count || 0), 0);
      setSearchPhase('done', { total });
      renderSearchHead(true, sources.length);
    } catch (err) {
      setSearchPhase('idle');
      $('#searchStatus').innerHTML = '<div class="card empty">' + esc(err.message) + '</div>';
    }
  }

  function allSearchTracks() {
    const list = [];
    state.platforms.forEach((p) => {
      const res = state.results.get(p.key);
      (res && res.tracks || []).forEach((t) => list.push(t));
    });
    return list;
  }

  function pickedSearchTracks() {
    return allSearchTracks().filter((t) => state.spicked.has(t.track_key));
  }

  /* 本地预估：免费额度先抵 MP3，剩下的按积分，和服务端 pricing.quote 同一套规则 */
  function quoteLocal(list, quality) {
    const w = walletOf();
    let left = w.free_left || 0;
    let credits = 0;
    let frees = 0;
    list.forEach((t) => {
      const price = (t.price || {})[quality] || {};
      if (quality === 'mp3' && price.free_ok && left > 0) { left -= 1; frees += 1; }
      else credits += price.credits || 0;
    });
    return {
      count: list.length, free: frees, credits: credits,
      balance: w.credits || 0, short: Math.max(0, credits - (w.credits || 0)),
    };
  }

  function planBits(plan) {
    const out = [];
    if (plan.free) out.push('免费额度抵 ' + plan.free + ' 首');
    if (plan.credits) out.push('扣 ' + plan.credits + ' 积分');
    if (!out.length) out.push('不消耗额度');
    return out.join(' · ');
  }

  function orderedResults() {
    // 「谁先出结果谁靠前」：有曲目的按到达顺序在前，超时/空的沉底
    const items = [];
    state.results.forEach((res, key) => items.push([key, res]));
    items.sort((a, b) => {
      const ae = (a[1].tracks || []).length ? 0 : 1;
      const be = (b[1].tracks || []).length ? 0 : 1;
      if (ae !== be) return ae - be;
      return (a[1].seq || 0) - (b[1].seq || 0);
    });
    return items;
  }

  function renderResults() {
    const wrap = $('#results');
    let html = '';
    orderedResults().forEach(([key, res]) => {
      const p = state.platforms.find((x) => x.key === key) || {};
      const tracks = res.tracks || [];
      const allOn = tracks.length > 0 && tracks.every((t) => state.spicked.has(t.track_key));
      const head = '<div class="group-head">' +
        '<span class="dot" style="width:8px;height:8px;border-radius:50%;background:' + (p.color || '#999') + '"></span>' +
        '<span class="pname">' + esc(res.label || p.label || key) + '</span>' +
        (res.error ? '<span class="badge err">' + (res.error === 'timeout' ? '超时' : '不可用') + '</span>'
                   : '<span class="badge">' + res.count + ' 首</span>') +
        (res.elapsed ? '<span class="elapsed">' + res.elapsed + 's</span>' : '') +
        (tracks.length
          ? '<label class="pickall"><input type="checkbox" class="check gcheck" data-plat="' + key + '"' +
            (allOn ? ' checked' : '') + '>全选</label>'
          : '') +
        '</div>';
      const rows = tracks.map((t) => trackRow(t, { selectable: true, pick: 'search' })).join('');
      html += '<div class="card group">' + head + (rows || '<div class="empty">此平台暂无结果</div>') + '</div>';
    });
    wrap.innerHTML = html || '';
    bindTrackButtons(wrap);
    $$('.gcheck', wrap).forEach((cb) => {
      cb.onchange = () => {
        const res = state.results.get(cb.dataset.plat) || {};
        (res.tracks || []).forEach((t) => {
          if (cb.checked) state.spicked.add(t.track_key);
          else state.spicked.delete(t.track_key);
        });
        renderResults();
      };
    });
    renderBatchBar();
  }

  function renderBatchBar() {
    const bar = $('#batchBar');
    if (!bar) return;
    const all = allSearchTracks();
    if (!all.length) { bar.innerHTML = ''; return; }
    const picked = pickedSearchTracks();
    const n = picked.length;
    const mp3 = quoteLocal(picked, 'mp3');
    const flac = quoteLocal(picked, 'flac');
    const over = n > 0 && mp3.short > 0;
    const allOn = n > 0 && n === all.length;
    bar.innerHTML = '<div class="selbar batchbar">' +
      '<input type="checkbox" class="check" id="searchPickAll"' + (allOn ? ' checked' : '') + '>' +
      '<span class="seltext">已选 <b>' + n + '</b> / ' + all.length + ' 首</span>' +
      '<span class="price' + (over ? ' over' : '') + '">' +
        (n ? 'MP3：' + planBits(mp3) + (over ? '（还差 ' + mp3.short + ' 积分）' : '')
           : '勾选后浏览器直连音源、逐首保存，不走服务器带宽') +
      '</span>' +
      '<span class="spacer"></span>' +
      '<button class="btn sm" id="btnPickClear"' + (n ? '' : ' disabled') + '>清空</button>' +
      '<button class="btn sm gold" id="btnBatchFlac"' + (n ? '' : ' disabled') +
        ' title="' + esc(n ? '无损：' + planBits(flac) : '先勾选歌曲') + '">批量无损' +
        (n && flac.credits ? '<span class="tag-price">总 ' + flac.credits + '分</span>' : '') + '</button>' +
      '<button class="btn sm primary" id="btnBatchMp3"' + (n ? '' : ' disabled') + '>批量下载 MP3</button>' +
      '</div>';

    $('#searchPickAll').onchange = (e) => {
      if (e.target.checked) all.forEach((t) => state.spicked.add(t.track_key));
      else state.spicked.clear();
      renderResults();
    };
    $('#btnPickClear').onclick = () => { state.spicked.clear(); renderResults(); };
    $('#btnBatchMp3').onclick = () => batchDownloadSearch('mp3');
    $('#btnBatchFlac').onclick = () => batchDownloadSearch('flac');
  }

  function syncSearchPicks() {
    renderBatchBar();
    $$('.gcheck').forEach((cb) => {
      const res = state.results.get(cb.dataset.plat) || {};
      const tracks = res.tracks || [];
      cb.checked = tracks.length > 0 && tracks.every((t) => state.spicked.has(t.track_key));
    });
  }

  /* ---------------- 下载 ---------------- */
  function chargeText(c) {
    if (!c) return '';
    if (c.free) return c.amount ? '用了 1 次免费额度' : '';
    return c.amount ? '扣 ' + c.amount + ' 积分' : '';
  }

  async function requestDownload(trackKey, quality, btn, reuseId) {
    if (!state.user) {
      toast('下载需要先登录，登录后每天 10 首免费');
      openAuth('login');
      return;
    }
    if (btn) {
      if (!btn.dataset.label) btn.dataset.label = btn.innerHTML;
      btn.disabled = true;
    }
    try {
      const body = { track_key: trackKey, quality: quality };
      if (reuseId) body.reuse_charge_id = reuseId;
      const data = await api('/api/download', { method: 'POST', body });
      if (data.wallet) applyWallet(data.wallet);

      if (data.mode === 'browser') {
        // 浏览器直连音源 → 本地写标签 → 落盘，服务器不走音频字节
        toast('正在从音源直连下载…');
        try {
          await downloadInBrowser(data, btn);
          const note = chargeText(data.charged);
          toast('已保存：' + data.filename + (note ? ' · ' + note : ''));
        } catch (err) {
          console.warn('直连失败，改用服务端中转：', err);
          toast('直连不可用，改用服务器中转…');
          // 带上 charge_id：服务端复用这笔扣费，不会重复收
          const fallback = await api('/api/download', {
            method: 'POST',
            body: {
              track_key: trackKey, quality: quality, mode: 'server',
              reuse_charge_id: data.charge_id,
            },
          });
          if (fallback.wallet) applyWallet(fallback.wallet);
          if (fallback.mode === 'job') {
            watchJob(fallback.job_id, quality);
          } else if (fallback.mode === 'direct') {
            triggerDirect(fallback.url);
          }
        }
      } else if (data.mode === 'direct') {
        toast('正在直连下载…' + (chargeText(data.charged) ? '（' + chargeText(data.charged) + '）' : ''));
        triggerDirect(data.url);
      } else if (data.mode === 'job') {
        watchJob(data.job_id, quality);
        const note = chargeText(data.charged);
        toast((quality === 'flac' ? '正在准备无损文件…' : '正在准备 MP3…') + (note ? '（' + note + '）' : ''));
      }
    } catch (err) {
      const code = err.payload && err.payload.code;
      if (code === 'login_required') {
        toast(err.message);
        openAuth('login');
        return;
      }
      if (code === 'credits_insufficient') {
        if (err.payload.wallet) applyWallet(err.payload.wallet);
        openPay(err.message);
        return;
      }
      if (err.status === 402) { openPay(err.message); return; }
      toast(err.message);
    } finally {
      if (btn) {
        btn.disabled = false;
        if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
      }
    }
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /* 批量交付时把顶部批量栏临时变成进度条 */
  function setBatchTip(text, pct) {
    const bar = $('#batchBar');
    if (!bar) return;
    bar.innerHTML = '<div class="selbar batchbar">' +
      '<span class="seltext">' + esc(text) + '</span>' +
      '<span class="spacer"></span>' +
      '<div style="width:130px"><div class="bar"><i style="width:' +
        Math.max(2, Math.min(100, Math.round(pct || 0))) + '%"></i></div></div></div>';
  }

  /* 搜索结果的批量：优先「浏览器串行直连 + 本地打标」，服务端零音频流量；
     拿不到直连（需转码 / 无 CORS）或直连失败的，再统一交给服务端任务兜底。 */
  async function batchDownloadSearch(quality) {
    if (!state.user) {
      toast('批量下载需要先登录，登录后每天 10 首免费');
      openAuth('login');
      return;
    }
    const keys = pickedSearchTracks().map((t) => t.track_key);
    if (!keys.length) { toast('请先勾选歌曲'); return; }
    const btn = quality === 'flac' ? $('#btnBatchFlac') : $('#btnBatchMp3');
    const label = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.textContent = '准备中…'; }

    try {
      setBatchTip('正在解析音源…', 3);
      const prep = await api('/api/download/batch/direct', {
        method: 'POST',
        body: { track_keys: keys, quality: quality },
      });
      if (prep.wallet) applyWallet(prep.wallet);

      const ready = prep.ready || [];
      const needServer = prep.need_server || [];
      const failed = [];
      let saved = 0;

      if (ready.length) {
        toast('开始下载 ' + ready.length + ' 首，若浏览器提示「允许多个下载」请点允许', 4200);
        for (let i = 0; i < ready.length; i++) {
          const item = ready[i];
          const tag = (item.tags && item.tags.title) || item.filename || '';
          const base = '交付 ' + (i + 1) + '/' + ready.length + ' · ' + tag;
          setBatchTip(base, ((i) / ready.length) * 100);
          try {
            if (item.mode === 'browser') {
              await downloadInBrowser(item, null, (text) => {
                setBatchTip(base + ' · ' + text, ((i + 0.5) / ready.length) * 100);
              });
            } else {
              triggerDirect(item.url);
            }
            saved += 1;
          } catch (err) {
            console.warn('直连失败，转服务端：', item.track_key, err);
            failed.push(item);
          }
          if (i < ready.length - 1) await sleep(quality === 'flac' ? 1200 : 320);
        }
      }

      // 直连没覆盖到的曲目 → 服务端任务；已扣的那笔挂过去，不会重复收钱
      const reuse = {};
      failed.forEach((f) => { if (f.charge_id) reuse[f.track_key] = f.charge_id; });
      const serverKeys = needServer.map((x) => x.track_key).concat(failed.map((f) => f.track_key));

      let jobInfo = null;
      if (serverKeys.length) {
        setBatchTip('转服务端处理 ' + serverKeys.length + ' 首…', 96);
        jobInfo = await api('/api/download/batch', {
          method: 'POST',
          body: { track_keys: serverKeys, quality: quality, reuse_charge_ids: reuse },
        });
        if (jobInfo.wallet) applyWallet(jobInfo.wallet);
        state.jobs.set(jobInfo.job_id, { id: jobInfo.job_id, quality: quality, autoDone: false });
        startPolling();
      }

      state.spicked.clear();
      renderResults();

      const bits = [];
      if (saved) bits.push('已保存 ' + saved + ' 首');
      if (serverKeys.length) bits.push(serverKeys.length + ' 首转服务端处理');
      if (prep.skipped && prep.skipped.length) bits.push(prep.skipped.length + ' 首已失效');
      toast(bits.length ? bits.join('，') : '没有可下载的曲目', 4200);
      if (serverKeys.length) switchTab('jobs');
    } catch (err) {
      renderResults();
      const code = err.payload && err.payload.code;
      if (code === 'login_required') { toast(err.message); openAuth('login'); return; }
      if (code === 'credits_insufficient') {
        if (err.payload.wallet) applyWallet(err.payload.wallet);
        openPay(err.message);
        return;
      }
      toast(err.message);
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = label; }
    }
  }

  /* 直连取流 → 本地注入 ID3 → 触发保存（btn 可为 null，批量时用 onProgress 报进度） */
  async function downloadInBrowser(data, btn, onProgress) {
    const resp = await fetch(data.url, {
      credentials: 'same-origin',
      referrerPolicy: 'no-referrer',
      cache: 'no-store',
    });
    if (!resp.ok) throw new Error('直连返回 ' + resp.status);

    const total = Number(data.size_hint) || 0;
    const show = (text) => {
      if (btn) btn.textContent = text;
      if (onProgress) onProgress(text);
    };

    let audio;
    if (resp.body && resp.body.getReader) {
      const reader = resp.body.getReader();
      const chunks = [];
      let got = 0;
      let lastAt = 0;
      for (;;) {
        const step = await reader.read();
        if (step.done) break;
        chunks.push(step.value);
        got += step.value.length;
        const now = Date.now();
        if (now - lastAt > 350) {
          lastAt = now;
          show(total > got ? Math.min(99, Math.floor((got / total) * 100)) + '%'
                           : (got / 1048576).toFixed(1) + 'M');
        }
      }
      audio = new Uint8Array(got);
      let off = 0;
      chunks.forEach((c) => { audio.set(c, off); off += c.length; });
    } else {
      audio = new Uint8Array(await resp.arrayBuffer());
    }
    if (!audio.length) throw new Error('音源返回空数据');

    let cover = null;
    let mime = 'image/jpeg';
    const coverUrl = data.tags && data.tags.cover;
    if (coverUrl) {
      try {
        const cr = await fetch(coverUrl, { credentials: 'same-origin', referrerPolicy: 'no-referrer' });
        if (cr.ok) {
          const buf = new Uint8Array(await cr.arrayBuffer());
          if (buf.length > 512) {
            cover = buf;
            mime = window.MP3ID3.sniffMime(buf);
          }
        }
      } catch (e) { /* 封面拿不到不影响下载 */ }
    }

    show('写入标签…');
    const out = window.MP3ID3.attach(audio, data.tags || {}, cover, mime);
    saveBlob(new Blob([out], { type: 'audio/mpeg' }), data.filename || 'track.mp3');
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  function triggerDirect(url) {
    const a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener';
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  /* 逐首交付：隔开一点触发，避免浏览器把连续下载当成弹窗而拦掉 */
  function downloadAllFiles(fileIds) {
    const ids = (fileIds || []).filter(Boolean);
    if (!ids.length) { toast('还没有可下载的文件'); return; }
    ids.forEach((fid, i) => {
      setTimeout(() => triggerDirect('/api/files/' + fid), i * 900);
    });
    if (ids.length > 1) {
      toast('开始下载 ' + ids.length + ' 个文件，若浏览器提示「允许多个下载」请点击允许', 4200);
    }
  }

  /* 任务轮询 */
  function watchJob(jobId, quality) {
    if (!state.jobs.has(jobId)) {
      state.jobs.set(jobId, { id: jobId, quality: quality, autoDone: quality !== 'flac' });
    }
    startPolling();
  }

  function startPolling() {
    if (state.polling) return;
    state.polling = setInterval(pollJobs, 1200);
    pollJobs();
  }

  async function syncWallet() {
    if (!state.user) return;
    try {
      const d = await api('/api/auth/me');
      if (d.user) { state.user = d.user; applyWallet(d.user.wallet); }
    } catch (e) { /* 忽略 */ }
  }

  async function pollJobs() {
    const ids = Array.from(state.jobs.keys());
    if (!ids.length) {
      clearInterval(state.polling);
      state.polling = null;
      return;
    }
    let settled = false;
    for (const id of ids) {
      try {
        const detail = await api('/api/jobs/' + id);
        const prev = state.jobs.get(id) || {};
        state.jobs.set(id, Object.assign({}, prev, detail));
        if (['done', 'partial', 'failed'].includes(detail.status)) {
          if (!prev.settled) {
            state.jobs.get(id).settled = true;
            settled = true;   // 失败曲目会退回额度/积分，结算后刷新钱包
          }
          const doneItems = (detail.items || []).filter((i) => i.status === 'done' && i.file_id);
          if (prev.autoDone && detail.kind === 'single') {
            // 单曲：直接落盘
            if (doneItems[0]) triggerDirect('/api/files/' + doneItems[0].file_id);
            if (detail.status !== 'done') toast('下载失败：' + (((detail.items || [])[0] || {}).error || '未知原因'));
          } else if (detail.kind === 'batch') {
            // 批量：不自动连发下载（浏览器会拦），提示到任务列表里点
            toast(detail.status === 'done'
              ? '批量任务完成：' + doneItems.length + ' 首都好了，去任务列表点「下载」'
              : '批量任务结束：成功 ' + doneItems.length + ' 首，失败 ' + (detail.failed || 0) + ' 首', 3800);
          }
          state.jobs.delete(id);   // 结束后交给 /api/jobs 列表，不再轮询
        }
      } catch (e) {
        state.jobs.delete(id);
      }
    }
    if (settled) syncWallet();
    renderActiveJobs();
  }

  function renderActiveJobs() {
    if (!$('#tab-jobs').hidden) loadJobs();
  }

  /* ---------------- 歌单 ---------------- */
  async function parsePlaylist() {
    const url = $('#playlistUrl').value.trim();
    if (!url) { toast('请先粘贴歌单链接'); return; }
    const status = $('#playlistStatus');
    status.innerHTML = '<div class="card pad" style="margin-top:14px">' +
      '<div style="font-size:13px;color:var(--text-2);margin-bottom:8px">正在解析歌单，大歌单可能需要 10-60 秒…</div>' +
      '<div class="bar"><i style="width:20%;animation:sk 1.3s infinite"></i></div></div>';
    $('#playlistResult').innerHTML = '';
    try {
      const data = await api('/api/playlist/parse', { method: 'POST', body: { url: url } });
      pollParse(data.task_id);
    } catch (err) {
      status.innerHTML = '<div class="card empty" style="margin-top:14px">' + esc(err.message) +
        (err.payload && err.payload.hint ? '<div class="hint">' + esc(err.payload.hint) + '</div>' : '') + '</div>';
    }
  }

  function pollParse(taskId) {
    const status = $('#playlistStatus');
    const timer = setInterval(async () => {
      let data;
      try { data = await api('/api/playlist/parse/' + taskId); } catch (e) {
        clearInterval(timer);
        status.innerHTML = '<div class="card empty" style="margin-top:14px">解析任务已过期，请重新提交</div>';
        return;
      }
      if (data.status === 'running') {
        status.innerHTML = '<div class="card pad" style="margin-top:14px">' +
          '<div style="font-size:13px;color:var(--text-2);margin-bottom:8px">解析中… 已用 ' + data.elapsed + 's</div>' +
          '<div class="bar"><i style="width:' + Math.min(90, 10 + data.elapsed) + '%"></i></div></div>';
        return;
      }
      clearInterval(timer);
      if (data.status === 'failed' || data.status === 'empty' || !data.tracks.length) {
        status.innerHTML = '<div class="card empty" style="margin-top:14px">' + esc(data.error || '没有解析到曲目') + '</div>';
        return;
      }
      status.innerHTML = '';
      state.playlist = data;
      state.picked = new Set(data.tracks.map((t) => t.track_key));
      renderPlaylist();
    }, 1500);
  }

  function renderPlaylist() {
    const data = state.playlist;
    if (!data) return;
    const feats = $('#playlistFeats');
    if (feats) feats.hidden = true;
    const wrap = $('#playlistResult');
    const allChecked = state.picked.size === data.tracks.length;
    wrap.innerHTML = '<div class="card" style="margin-top:14px">' +
      '<div class="selbar">' +
        '<input type="checkbox" class="check" id="pickAll"' + (allChecked ? ' checked' : '') + '>' +
        '<span id="selCount">已选 ' + state.picked.size + ' / ' + data.tracks.length + ' 首</span>' +
        '<span class="badge">' + esc(data.title || '歌单') + '</span>' +
        '<span class="spacer"></span>' +
        '<button class="btn sm primary" id="btnBatch">批量下载 MP3</button>' +
        '<button class="btn sm" id="btnZip" disabled>打包 ZIP</button>' +
      '</div>' +
      data.tracks.map((t) => trackRow(t, { selectable: true })).join('') +
    '</div>';

    $('#pickAll').onchange = (e) => {
      state.picked = e.target.checked ? new Set(data.tracks.map((t) => t.track_key)) : new Set();
      renderPlaylist();
    };
    bindTrackButtons(wrap);
    $('#btnBatch').onclick = batchDownload;
    $('#btnZip').onclick = (e) => {
      const jobId = e.target.dataset.job;
      if (jobId) triggerDirect('/api/jobs/' + jobId + '/zip');
    };
  }

  function updateSelBar() {
    const el = $('#selCount');
    if (el && state.playlist) el.textContent = '已选 ' + state.picked.size + ' / ' + state.playlist.tracks.length + ' 首';
  }

  async function batchDownload() {
    if (!state.playlist) return;
    if (!state.user) {
      toast('批量下载需要先登录');
      openAuth('login');
      return;
    }
    const keys = Array.from(state.picked);
    if (!keys.length) { toast('请先勾选歌曲'); return; }
    const btn = $('#btnBatch');
    btn.disabled = true;
    try {
      const data = await api('/api/playlist/download', {
        method: 'POST',
        body: { track_keys: keys, quality: 'mp3', title: state.playlist.title || '歌单' },
      });
      if (data.wallet) applyWallet(data.wallet);
      state.jobs.set(data.job_id, { id: data.job_id, quality: 'mp3', autoDone: false });
      startPolling();
      const zipBtn = $('#btnZip');
      zipBtn.disabled = false;
      zipBtn.dataset.job = data.job_id;

      const plan = data.plan || {};
      const bits = [];
      if (plan.free) bits.push('免费额度抵 ' + plan.free + ' 首');
      if (plan.credits) bits.push('扣 ' + plan.credits + ' 积分');
      toast('已开始批量下载 ' + data.total + ' 首' + (bits.length ? '（' + bits.join('，') + '）' : ''));
      switchTab('jobs');
    } catch (err) {
      const code = err.payload && err.payload.code;
      if (code === 'login_required') { toast(err.message); openAuth('login'); return; }
      if (code === 'credits_insufficient') {
        if (err.payload.wallet) applyWallet(err.payload.wallet);
        openPay(err.message);
        return;
      }
      toast(err.message);
    } finally {
      btn.disabled = false;
    }
  }

  /* ---------------- 任务列表 ---------------- */
  const JOB_STATUS = { queued: '排队中', running: '下载中', done: '已完成', partial: '部分完成', failed: '失败' };
  const ITEM_STATUS = { queued: '排队中', running: '下载中', done: '已完成', failed: '失败' };

  function jobRowHtml(j) {
    const items = j.items || [];
    const ready = items.filter((i) => i.status === 'done' && i.file_id);
    const pct = j.total ? Math.round(((j.finished || 0) / j.total) * 100) : 0;
    const cls = j.status === 'done' ? 'ok' : (j.status === 'failed' ? 'err' : '');
    const open = state.expanded.has(j.id);
    const expandable = items.length > 1;

    let html = '<div class="jobrow">' +
      '<div class="jobline">' +
        (expandable
          ? '<button class="caret' + (open ? ' open' : '') + '" data-exp="' + j.id + '" title="展开曲目">▸</button>'
          : '<span class="caret-space"></span>') +
        '<div class="t">' + esc(j.title || '单曲下载') +
          ' <span class="badge ' + cls + '">' + (JOB_STATUS[j.status] || j.status) + '</span>' +
          (j.failed && j.total > 1 ? ' <span class="badge err">失败 ' + j.failed + '</span>' : '') +
          (expandable ? ' <span class="badge soft">' + j.total + ' 首</span>' : '') +
        '</div>' +
        '<div style="width:90px"><div class="bar' + (j.status === 'done' ? ' ok' : '') + '">' +
          '<i style="width:' + pct + '%"></i></div></div>' +
        '<span style="width:56px;text-align:right;color:var(--text-3)">' + (j.finished || 0) + '/' + (j.total || 0) + '</span>' +
        (ready.length ? '<button class="btn sm primary" data-getall="' + j.id + '">下载 ' + ready.length + ' 首</button>' : '') +
        (j.zip && j.finished ? '<button class="btn sm" data-zip="' + j.id + '">ZIP</button>' : '') +
      '</div>';

    if (open && items.length) {
      html += '<div class="jobitems">' + items.map((it) => {
        const ok = it.status === 'done' && it.file_id;
        const icon = ok ? '✓' : (it.status === 'failed' ? '✕' : '·');
        const stCls = ok ? 'ok' : (it.status === 'failed' ? 'err' : 'wait');
        const name = (it.song_name || '') + (it.singers ? ' - ' + it.singers : '');
        return '<div class="jobitem">' +
          '<span class="ic ' + stCls + '">' + icon + '</span>' +
          '<span class="n">' + esc(name || '未知曲目') + '</span>' +
          (ok
            ? '<button class="btn sm" data-file="' + esc(it.file_id) + '">下载</button>'
            : '<span class="e">' + esc(it.error || ITEM_STATUS[it.status] || '') + '</span>') +
        '</div>';
      }).join('') + '</div>';
    }
    return html + '</div>';
  }

  function bindJobRows(wrap, jobs) {
    const byId = new Map(jobs.map((j) => [j.id, j]));
    $$('[data-exp]', wrap).forEach((b) => {
      b.onclick = () => {
        const id = b.dataset.exp;
        if (state.expanded.has(id)) state.expanded.delete(id);
        else state.expanded.add(id);
        loadJobs();
      };
    });
    $$('[data-getall]', wrap).forEach((b) => {
      b.onclick = () => {
        const j = byId.get(b.dataset.getall) || {};
        downloadAllFiles((j.items || [])
          .filter((i) => i.status === 'done' && i.file_id)
          .map((i) => i.file_id));
      };
    });
    $$('[data-file]', wrap).forEach((b) => {
      b.onclick = () => triggerDirect('/api/files/' + b.dataset.file);
    });
    $$('[data-zip]', wrap).forEach((b) => {
      b.onclick = () => triggerDirect('/api/jobs/' + b.dataset.zip + '/zip');
    });
  }

  async function loadJobs() {
    const wrap = $('#jobsList');
    try {
      const data = await api('/api/jobs');
      const jobs = data.jobs || [];
      // 合并本地进行中的任务详情（服务端列表里的 finished 可能差一次轮询）
      const merged = jobs.map((j) => Object.assign({}, j, state.jobs.get(j.id) || {}));
      state.jobs.forEach((v, k) => { if (!merged.find((m) => m.id === k)) merged.unshift(v); });
      if (!merged.length) {
        wrap.innerHTML = '<div class="empty">' +
          '<div class="empty-ic">♪</div>' +
          '<div class="empty-t">还没有下载任务</div>' +
          '<div class="empty-s">搜一首歌，点一下「MP3」就会出现在这里</div>' +
          '<button class="btn sm primary" id="btnGoSearch">去搜歌</button>' +
          '</div>';
        $('#jobsMeta').textContent = '';
        const go = $('#btnGoSearch');
        if (go) go.onclick = () => switchTab('search');
        return;
      }
      wrap.innerHTML = merged.map(jobRowHtml).join('');
      bindJobRows(wrap, merged);
      $('#jobsMeta').textContent = '共 ' + merged.length + ' 个';
    } catch (e) {
      wrap.innerHTML = '<div class="empty">任务列表加载失败</div>';
    }
  }

  /* ---------------- 事件绑定 ---------------- */
  $('#btnSearch').onclick = doSearch;
  $('#q').addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });
  $$('#starter .sug').forEach((b) => {
    b.onclick = () => { $('#q').value = b.dataset.q; doSearch(); };
  });
  $('#btnParse').onclick = parsePlaylist;
  $('#playlistUrl').addEventListener('keydown', (e) => { if (e.key === 'Enter') parsePlaylist(); });
  $('#btnPaste').onclick = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) { $('#playlistUrl').value = text.trim(); toast('已粘贴'); }
    } catch (e) { toast('浏览器不允许读取剪贴板，请手动粘贴'); }
  };

  /* ---------------- 启动 ---------------- */
  (async function boot() {
    await refreshMe();
    try { await loadPlatforms(); } catch (e) { toast('平台列表加载失败'); }
  })();
})();
