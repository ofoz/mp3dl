/**
 * SoundFlow Modern WebUI Frontend Logic
 * Powered by musicdl
 */

// State
const state = {
  sources: [],
  activeSources: new Set(),
  tracks: [],
  currentTrackIndex: -1,
  currentTrack: null,
  lyrics: [],
  currentLyricIndex: -1,
  eventSource: null,
  playlistTracks: [],
  pendingTrack: null,
  isSettingsMode: false,
  isFullscreenOpen: false,
  playMode: 'loop', // 'loop', 'one', 'shuffle'
  predictedNextIndex: -1,
  tracksSource: 'search', // 'search' or 'playlist'
};

const STORAGE_KEY_FORMAT = 'musicdl_pref_format';
const FORMAT_LABELS = {
  'original': '原始高保真',
  'mp3': 'MP3',
  'flac': 'FLAC',
  'wav': 'WAV',
  'm4a': 'M4A'
};

// 安全网络 JSON 解析器：捕获 502/504 等 HTML 异常页面，消除 Unexpected token '<' 报错
async function safeFetchJson(url, options = {}) {
  const res = await fetch(url, options);
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    if (res.status === 504 || res.status === 502) {
      throw new Error(`网关响应超时 (HTTP ${res.status})，反代已切断连接`);
    }
    throw new Error(`服务响应异常 (HTTP ${res.status})`);
  }
  return data;
}

// DOM Elements
const searchInput = document.getElementById('searchInput');
const searchBtn = document.getElementById('searchBtn');
const sourcesContainer = document.getElementById('sourcesContainer');
const sourcesToggleHeader = document.getElementById('sourcesToggleHeader');
const sourcesCollapsePanel = document.getElementById('sourcesCollapsePanel');
const sourcesArrowIcon = document.getElementById('sourcesArrowIcon');
const sourcesToggleHint = document.getElementById('sourcesToggleHint');
const sourcesCountBadge = document.getElementById('sourcesCountBadge');
const selectAllCoreBtn = document.getElementById('selectAllCoreBtn');
const selectAllSourcesBtn = document.getElementById('selectAllSourcesBtn');
const resetSourcesBtn = document.getElementById('resetSourcesBtn');
const resultsTableBody = document.getElementById('resultsTableBody');
const statusText = document.getElementById('statusText');
const sourceChips = document.getElementById('sourceChips');

const tabSearchBtn = document.getElementById('tabSearchBtn');
const tabPlaylistBtn = document.getElementById('tabPlaylistBtn');
const searchView = document.getElementById('searchView');
const playlistView = document.getElementById('playlistView');

const playlistUrlInput = document.getElementById('playlistUrlInput');
const parsePlaylistBtn = document.getElementById('parsePlaylistBtn');
const playlistResultCard = document.getElementById('playlistResultCard');
const playlistTableBody = document.getElementById('playlistTableBody');
const playlistCountText = document.getElementById('playlistCountText');
const playlistDownloadAllBtn = document.getElementById('playlistDownloadAllBtn');

const lyricModal = document.getElementById('lyricModal');
const footerLyricBtn = document.getElementById('footerLyricBtn');
const closeLyricBtn = document.getElementById('closeLyricBtn');
const lyricContainer = document.getElementById('lyricContainer');

const audioElement = document.getElementById('audioElement');
const playPauseBtn = document.getElementById('playPauseBtn');
const playIcon = document.getElementById('playIcon');
const pauseIcon = document.getElementById('pauseIcon');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');
const seekSlider = document.getElementById('seekSlider');
const currentTimeText = document.getElementById('currentTimeText');
const durationText = document.getElementById('durationText');
const volumeSlider = document.getElementById('volumeSlider');
const playerCover = document.getElementById('playerCover');
const playerTitle = document.getElementById('playerTitle');
const playerArtist = document.getElementById('playerArtist');
const downloadDirectBtn = document.getElementById('downloadDirectBtn');
const playerTrackInfo = document.getElementById('playerTrackInfo');
const expandPlayerBtn = document.getElementById('expandPlayerBtn');

// Fullscreen Player Elements
const fullscreenPlayer = document.getElementById('fullscreenPlayer');
const fsBgBlur = document.getElementById('fsBgBlur');
const fsCloseBtn = document.getElementById('fsCloseBtn');
const fsHeaderTitle = document.getElementById('fsHeaderTitle');
const fsHeaderArtist = document.getElementById('fsHeaderArtist');
const fsDownloadBtn = document.getElementById('fsDownloadBtn');
const vinylNeedle = document.getElementById('vinylNeedle');
const vinylDisc = document.getElementById('vinylDisc');
const fsCoverImg = document.getElementById('fsCoverImg');
const fsSourceBadge = document.getElementById('fsSourceBadge');
const fsExtBadge = document.getElementById('fsExtBadge');
const fsLyricContainer = document.getElementById('fsLyricContainer');
const fsCurrentTime = document.getElementById('fsCurrentTime');
const fsDuration = document.getElementById('fsDuration');
const fsSeekSlider = document.getElementById('fsSeekSlider');
const fsPlayModeBtn = document.getElementById('fsPlayModeBtn');
const modeLoopIcon = document.getElementById('modeLoopIcon');
const modeRepeatOneIcon = document.getElementById('modeRepeatOneIcon');
const modeShuffleIcon = document.getElementById('modeShuffleIcon');
const fsModeLabel = document.getElementById('fsModeLabel');
const fsPrevBtn = document.getElementById('fsPrevBtn');
const fsPlayPauseBtn = document.getElementById('fsPlayPauseBtn');
const fsPlayIcon = document.getElementById('fsPlayIcon');
const fsPauseIcon = document.getElementById('fsPauseIcon');
const fsNextBtn = document.getElementById('fsNextBtn');
const fsVolumeSlider = document.getElementById('fsVolumeSlider');

// Format Preference Modal & Badge Elements
const formatPrefBadge = document.getElementById('formatPrefBadge');
const currentFormatLabel = document.getElementById('currentFormatLabel');
const resetFormatBtn = document.getElementById('resetFormatBtn');
const downloadModal = document.getElementById('downloadModal');
const modalTrackName = document.getElementById('modalTrackName');
const modalOrigExtBadge = document.getElementById('modalOrigExtBadge');
const rememberFormatCheckbox = document.getElementById('rememberFormatCheckbox');
const closeModalBtn = document.getElementById('closeModalBtn');
const cancelModalBtn = document.getElementById('cancelModalBtn');
const confirmDownloadBtn = document.getElementById('confirmDownloadBtn');
const toastContainer = document.getElementById('toastContainer');

// Loading Icons for Play Buttons
const loadingIcon = document.getElementById('loadingIcon');
const fsLoadingIcon = document.getElementById('fsLoadingIcon');

// My Playlists Modal & Center Elements
const myPlaylistsBtn = document.getElementById('myPlaylistsBtn');
const myPlaylistsCountBadge = document.getElementById('myPlaylistsCountBadge');
const myPlaylistsModal = document.getElementById('myPlaylistsModal');
const modalPlTotalBadge = document.getElementById('modalPlTotalBadge');
const closePlaylistsModalBtn = document.getElementById('closePlaylistsModalBtn');
const exportConfigBtn = document.getElementById('exportConfigBtn');
const importConfigTriggerBtn = document.getElementById('importConfigTriggerBtn');
const importConfigFileInput = document.getElementById('importConfigFileInput');
const exportQrConfigBtn = document.getElementById('exportQrConfigBtn');
const scanQrConfigBtn = document.getElementById('scanQrConfigBtn');

// QR Export Modal Elements
const qrExportModal = document.getElementById('qrExportModal');
const closeQrExportModalBtn = document.getElementById('closeQrExportModalBtn');
const qrExportCanvasWrapper = document.getElementById('qrExportCanvasWrapper');
const qrExportSummaryText = document.getElementById('qrExportSummaryText');
const qrExportSubText = document.getElementById('qrExportSubText');
const qrExportNetBadge = document.getElementById('qrExportNetBadge');
const qrExportNetBadgeText = document.getElementById('qrExportNetBadgeText');
const downloadQrImgBtn = document.getElementById('downloadQrImgBtn');
const copyQrCodeTextBtn = document.getElementById('copyQrCodeTextBtn');

// QR Scan Modal Elements
const qrScanModal = document.getElementById('qrScanModal');
const closeQrScanModalBtn = document.getElementById('closeQrScanModalBtn');
const qrScanVideo = document.getElementById('qrScanVideo');
const qrScanCanvas = document.getElementById('qrScanCanvas');
const qrScanPromptMask = document.getElementById('qrScanPromptMask');
const qrScanPromptText = document.getElementById('qrScanPromptText');
const triggerImagePickerBtn = document.getElementById('triggerImagePickerBtn');
const qrScanStatusMsg = document.getElementById('qrScanStatusMsg');
const pickQrImageBtn = document.getElementById('pickQrImageBtn');
const qrImageFileInput = document.getElementById('qrImageFileInput');
const modalPlaylistUrlInput = document.getElementById('modalPlaylistUrlInput');
const modalPlaylistCustomName = document.getElementById('modalPlaylistCustomName');
const modalImportPlaylistBtn = document.getElementById('modalImportPlaylistBtn');
const myPlaylistsCardsContainer = document.getElementById('myPlaylistsCardsContainer');

// 1. Initial Load & Sources Setup
async function init() {
  updateFormatBadge();
  updateMyPlaylistsBadge();
  checkUrlSyncOnStartup();

  try {
    const res = await fetch('/api/sources');
    const data = await res.json();
    state.sources = data.sources || [];
    
    // Set default active sources
    state.sources.forEach(s => {
      if (s.default) state.activeSources.add(s.id);
    });
    
    renderSourcesPills();
  } catch (err) {
    statusText.innerText = '加载音源列表失败: ' + err.message;
  }
}

function updateSourcesCountBadge() {
  if (sourcesCountBadge) {
    sourcesCountBadge.innerText = `已激活 ${state.activeSources.size} 个音源`;
  }
}

if (sourcesToggleHeader && sourcesCollapsePanel) {
  sourcesToggleHeader.onclick = () => {
    const isHidden = sourcesCollapsePanel.classList.contains('hidden');
    if (isHidden) {
      sourcesCollapsePanel.classList.remove('hidden');
      if (sourcesArrowIcon) sourcesArrowIcon.classList.add('rotate-180');
      if (sourcesToggleHint) sourcesToggleHint.innerText = '点击收起';
    } else {
      sourcesCollapsePanel.classList.add('hidden');
      if (sourcesArrowIcon) sourcesArrowIcon.classList.remove('rotate-180');
      if (sourcesToggleHint) sourcesToggleHint.innerText = '点击展开';
    }
  };
}

function renderSourcesPills() {
  if (!sourcesContainer) return;
  sourcesContainer.innerHTML = '';
  state.sources.forEach(s => {
    const isActive = state.activeSources.has(s.id);
    const pill = document.createElement('button');
    pill.className = `source-pill px-3 py-1.5 rounded-xl text-xs font-medium border flex items-center gap-1.5 whitespace-nowrap ${
      isActive ? 'active' : 'inactive'
    }`;
    pill.innerHTML = `
      <span class="w-2 h-2 rounded-full ${isActive ? 'bg-emerald-500' : 'bg-slate-400'}"></span>
      <span>${s.label}</span>
      <span class="text-[10px] px-1.5 py-0.2 rounded ${isActive ? 'bg-emerald-100 text-emerald-800 font-semibold' : 'bg-slate-100 text-slate-500'}">${s.category}</span>
    `;
    pill.onclick = () => {
      if (state.activeSources.has(s.id)) {
        if (state.activeSources.size > 1) {
          state.activeSources.delete(s.id);
        }
      } else {
        state.activeSources.add(s.id);
      }
      renderSourcesPills();
    };
    sourcesContainer.appendChild(pill);
  });
  updateSourcesCountBadge();
}

// 2. Download Format & Lyrics Preferences & Modal Logic
const STORAGE_KEY_INCLUDE_LRC = 'musicdl_pref_include_lrc';
const STORAGE_KEY_EMBED_LYRIC = 'musicdl_pref_embed_lyric';

function getSavedFormat() {
  return localStorage.getItem(STORAGE_KEY_FORMAT);
}

function getSavedIncludeLrc() {
  const val = localStorage.getItem(STORAGE_KEY_INCLUDE_LRC);
  return val === null ? true : val === 'true';
}

function getSavedEmbedLyric() {
  const val = localStorage.getItem(STORAGE_KEY_EMBED_LYRIC);
  return val === null ? true : val === 'true';
}

function updateFormatBadge() {
  const saved = getSavedFormat();
  const formatDotBadge = document.getElementById('formatDotBadge');
  if (saved) {
    let text = FORMAT_LABELS[saved] || saved.toUpperCase();
    if (getSavedIncludeLrc()) text += ' + 词';
    if (currentFormatLabel) currentFormatLabel.innerText = text;
    if (formatDotBadge) formatDotBadge.classList.remove('hidden');
    formatPrefBadge.title = `当前格式偏好: [${text}] (点击更改)`;
    resetFormatBtn.classList.remove('hidden');
  } else {
    if (currentFormatLabel) currentFormatLabel.innerText = '每次询问';
    if (formatDotBadge) formatDotBadge.classList.add('hidden');
    formatPrefBadge.title = '设置默认下载格式与偏好 (当前: 每次询问)';
    resetFormatBtn.classList.add('hidden');
  }
}

formatPrefBadge.onclick = () => {
  openFormatModal(state.currentTrack || (state.tracks[0] || null), true);
};

resetFormatBtn.onclick = (e) => {
  e.stopPropagation();
  localStorage.removeItem(STORAGE_KEY_FORMAT);
  localStorage.removeItem(STORAGE_KEY_INCLUDE_LRC);
  localStorage.removeItem(STORAGE_KEY_EMBED_LYRIC);
  updateFormatBadge();
  showToast('已重置下载格式偏好，下次下载将弹出选项窗口');
};

function openFormatModal(track, forSettingsOnly = false) {
  state.pendingTrack = track;
  state.isSettingsMode = forSettingsOnly;

  const hasLyric = track ? Boolean(track.has_lyric) : true;

  if (track) {
    modalTrackName.innerText = `${track.song_name} - ${track.singers}`;
    const cleanExt = (track.ext && track.ext.toLowerCase() !== 'none' && track.ext.toLowerCase() !== 'null') ? track.ext.toUpperCase() : 'MP3';
    modalOrigExtBadge.innerText = cleanExt;
  } else {
    modalTrackName.innerText = '设置默认下载格式与歌词偏好';
    modalOrigExtBadge.innerText = 'ORIGINAL';
  }

  const saved = getSavedFormat() || 'original';
  const radio = document.querySelector(`input[name="downloadFormat"][value="${saved}"]`);
  if (radio) radio.checked = true;

  const includeLrcEl = document.getElementById('includeLrcCheckbox');
  const embedLyricEl = document.getElementById('embedLyricCheckbox');
  const lyricNoteEl = document.getElementById('modalLyricNote');

  if (includeLrcEl) {
    if (!hasLyric) {
      includeLrcEl.checked = false;
      includeLrcEl.disabled = true;
    } else {
      includeLrcEl.disabled = false;
      includeLrcEl.checked = getSavedIncludeLrc();
    }
  }

  if (embedLyricEl) {
    if (!hasLyric) {
      embedLyricEl.checked = false;
      embedLyricEl.disabled = true;
    } else {
      embedLyricEl.disabled = false;
      embedLyricEl.checked = getSavedEmbedLyric();
    }
  }

  if (lyricNoteEl) {
    if (!hasLyric) {
      lyricNoteEl.innerText = '⚠️ 此曲未收录歌词 (将仅下载音频)';
      lyricNoteEl.className = 'text-[11px] text-amber-400 font-medium';
    } else {
      lyricNoteEl.innerText = '同步LRC / 标签内嵌';
      lyricNoteEl.className = 'text-[10px] text-slate-500';
    }
  }

  const onlyLrcWrapper = document.getElementById('modalOnlyLrcWrapper');
  if (onlyLrcWrapper) {
    if (track && track.has_lyric) {
      onlyLrcWrapper.classList.remove('hidden');
      const onlyLrcText = document.querySelector('#modalOnlyLrcBtn span');
      if (onlyLrcText) {
        onlyLrcText.innerText = `仅下载《${track.song_name}》独立歌词 (.lrc)`;
      }
    } else {
      onlyLrcWrapper.classList.add('hidden');
    }
  }

  rememberFormatCheckbox.checked = Boolean(getSavedFormat());
  downloadModal.classList.remove('hidden');
}

function closeFormatModal() {
  downloadModal.classList.add('hidden');
  state.pendingTrack = null;
}

closeModalBtn.onclick = closeFormatModal;
cancelModalBtn.onclick = closeFormatModal;

const modalOnlyLrcBtn = document.getElementById('modalOnlyLrcBtn');
if (modalOnlyLrcBtn) {
  modalOnlyLrcBtn.onclick = async () => {
    if (state.pendingTrack) {
      const ok = await downloadLrcFile(state.pendingTrack);
      if (ok) {
        showToast(`已为您下载《${state.pendingTrack.song_name}》同步歌词 (.lrc)`);
      }
    }
  };
}

confirmDownloadBtn.onclick = () => {
  const selectedRadio = document.querySelector('input[name="downloadFormat"]:checked');
  const selectedFormat = selectedRadio ? selectedRadio.value : 'original';

  const includeLrcEl = document.getElementById('includeLrcCheckbox');
  const embedLyricEl = document.getElementById('embedLyricCheckbox');
  const includeLrc = includeLrcEl && !includeLrcEl.disabled ? includeLrcEl.checked : false;
  const embedLyric = embedLyricEl && !embedLyricEl.disabled ? embedLyricEl.checked : false;

  if (rememberFormatCheckbox.checked) {
    localStorage.setItem(STORAGE_KEY_FORMAT, selectedFormat);
    localStorage.setItem(STORAGE_KEY_INCLUDE_LRC, String(includeLrc));
    localStorage.setItem(STORAGE_KEY_EMBED_LYRIC, String(embedLyric));
  } else {
    localStorage.removeItem(STORAGE_KEY_FORMAT);
    localStorage.removeItem(STORAGE_KEY_INCLUDE_LRC);
    localStorage.removeItem(STORAGE_KEY_EMBED_LYRIC);
  }
  updateFormatBadge();

  if (!state.isSettingsMode && state.pendingTrack) {
    executeDownload(state.pendingTrack, selectedFormat, includeLrc, embedLyric);
  } else {
    showToast(`已更新下载偏好: [${FORMAT_LABELS[selectedFormat] || selectedFormat}] ${includeLrc ? '(含歌词)' : ''}`);
  }

  closeFormatModal();
};

function requestDownload(track) {
  if (!track) return;
  if (track.from_playlist || state.tracksSource === 'playlist') {
    showToast('歌单载入歌曲仅支持在线畅听');
    return;
  }
  const saved = getSavedFormat();
  if (saved) {
    const hasLyric = Boolean(track.has_lyric);
    const includeLrc = hasLyric ? getSavedIncludeLrc() : false;
    const embedLyric = hasLyric ? getSavedEmbedLyric() : false;
    executeDownload(track, saved, includeLrc, embedLyric);
  } else {
    openFormatModal(track, false);
  }
}

// 统一直接下载通道 (兼容 PC 与移动端 WebKit，规避不可见 iframe 与 display:none 导致事件被抑制)
function triggerDirectDownload(url, filename = '') {
  const a = document.createElement('a');
  a.href = url;
  if (filename) {
    a.download = filename;
  }
  a.style.position = 'fixed';
  a.style.top = '-9999px';
  a.style.left = '-9999px';
  a.style.opacity = '0';
  a.style.pointerEvents = 'none';
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    a.remove();
  }, 2000);
}

// 客户端内存 Blob 歌词导出器 (带 UTF-8 BOM，使用 application/octet-stream 规避手机系统强加 .txt 后缀)
async function downloadLrcFile(track) {
  if (!track || !track.has_lyric) return false;
  try {
    // 优先读取 track 对象中已有的歌词文本，避免二次网络请求导致手势状态失效
    let lyric = (track.lyric || '').trim();
    if (!lyric) {
      const p = new URLSearchParams();
      if (track.song_name) p.append('song_name', track.song_name);
      if (track.singers) p.append('singers', track.singers);
      if (track.identifier) p.append('song_id', track.identifier);
      const res = await fetch(`/api/lyric/${track.token}?${p.toString()}`);
      if (res.ok) {
        const data = await res.json();
        lyric = (data.lyric || '').trim();
        if (lyric) track.lyric = lyric;
      }
    }
    if (!lyric) return false;

    // 添加 UTF-8 BOM (\ufeff)，防止 Windows 记事本和车载系统乱码；
    // 强制使用 application/octet-stream，防止 iOS/Android 系统判定为纯文本并强制追加 .txt 后缀
    const blob = new Blob(['\ufeff' + lyric], { type: 'application/octet-stream' });
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = `${track.song_name} - ${track.singers}.lrc`;
    a.style.position = 'fixed';
    a.style.top = '-9999px';
    a.style.left = '-9999px';
    a.style.opacity = '0';
    a.style.pointerEvents = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      a.remove();
      URL.revokeObjectURL(blobUrl);
    }, 2000);
    return true;
  } catch (err) {
    console.warn('LRC download error:', err);
    return false;
  }
}

function executeDownload(track, format, includeLrc = true, embedLyric = true) {
  if (!track) return;
  const hasLyric = Boolean(track.has_lyric);
  const willEmbed = embedLyric && hasLyric;
  const willDownloadLrc = includeLrc && hasLyric;

  // 1. 发起音频下载 (顶层 <a> 手势直下，兼容 PC 与移动端，绝不打断当前播放)
  let targetExt = (format === 'original' ? (track.ext || 'mp3') : format).toLowerCase().replace(/^\./, '');
  if (!targetExt || targetExt === 'none' || targetExt === 'null') {
    targetExt = 'mp3';
  }
  const audioFilename = `${track.song_name} - ${track.singers}.${targetExt}`;
  let audioUrl = `/api/stream/${track.token}?download=1&format=${encodeURIComponent(format)}`;
  if (willEmbed) audioUrl += '&embed_lyric=1';
  triggerDirectDownload(audioUrl, audioFilename);

  const formatText = FORMAT_LABELS[format] || format.toUpperCase();
  const isMobile = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);

  if (isMobile) {
    // 移动端受 iOS/Android 单下载通道硬限制，必须全力保障音频本体（已完整内嵌歌词与封面）直接自动下入手机
    showToast(`正在以 [${formatText}] 格式下载《${track.song_name}》歌曲 (已内嵌歌词)...`);
  } else {
    // PC 端支持多文件并发，自动错峰保存外挂歌词文件
    if (willDownloadLrc) {
      showToast(`正在以 [${formatText}] 格式下载《${track.song_name}》音频与同步歌词...`);
      setTimeout(async () => {
        const ok = await downloadLrcFile(track);
        if (ok) {
          showToast(`已同时为您保存《${track.song_name}》同步歌词 (.lrc)`);
        }
      }, 1200);
    } else {
      showToast(`正在以 [${formatText}] 格式下载《${track.song_name}》音频...`);
    }
  }
}


function showToast(msg) {
  const toast = document.createElement('div');
  toast.className = 'bg-white/95 border border-emerald-200/80 text-slate-800 text-xs px-4 py-2.5 rounded-2xl shadow-xl shadow-emerald-950/5 backdrop-blur-md flex items-center gap-2.5 transform transition-all duration-300 translate-y-2 opacity-0 font-medium max-w-[90vw] pointer-events-none select-none';
  toast.innerHTML = `<span class="text-emerald-500 font-bold text-sm shrink-0">✦</span> <span class="truncate">${escapeHtml(msg)}</span>`;
  toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.classList.remove('translate-y-2', 'opacity-0');
  }, 10);

  setTimeout(() => {
    if (toast.parentNode) {
      toast.classList.add('opacity-0', 'translate-y-2');
      setTimeout(() => toast.remove(), 300);
    }
  }, 3200);
}

// 3. Tab Navigation
tabSearchBtn.onclick = () => {
  tabSearchBtn.classList.add('active');
  tabPlaylistBtn.classList.remove('active');
  searchView.classList.remove('hidden');
  playlistView.classList.add('hidden');
};

tabPlaylistBtn.onclick = () => {
  tabPlaylistBtn.classList.add('active');
  tabSearchBtn.classList.remove('active');
  playlistView.classList.remove('hidden');
  searchView.classList.add('hidden');
};

// Source Selection Shortcuts
selectAllCoreBtn.onclick = () => {
  state.activeSources.clear();
  state.sources.forEach(s => {
    if (s.category === '国内主流') state.activeSources.add(s.id);
  });
  renderSourcesPills();
};

selectAllSourcesBtn.onclick = () => {
  state.sources.forEach(s => state.activeSources.add(s.id));
  renderSourcesPills();
};

resetSourcesBtn.onclick = () => {
  state.activeSources.clear();
  state.sources.forEach(s => {
    if (s.default) state.activeSources.add(s.id);
  });
  renderSourcesPills();
};

// 4. Streaming Search Logic & Search Button States
let searchBtnResetTimer = null;

function resetSearchBtn() {
  if (searchBtnResetTimer) {
    clearTimeout(searchBtnResetTimer);
    searchBtnResetTimer = null;
  }
  if (!searchBtn) return;
  searchBtn.innerHTML = `<span>搜索</span>`;
  searchBtn.classList.remove('opacity-90');
}

function updateSearchBtnState(stateType, extra) {
  if (searchBtnResetTimer) {
    clearTimeout(searchBtnResetTimer);
    searchBtnResetTimer = null;
  }
  if (!searchBtn) return;

  if (stateType === 'idle') {
    resetSearchBtn();
  } else if (stateType === 'searching') {
    const text = extra ? `已找到 ${extra} 首` : '检索中...';
    searchBtn.innerHTML = `
      <svg class="animate-spin w-3.5 h-3.5 text-white shrink-0" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
      </svg>
      <span class="whitespace-nowrap text-xs sm:text-sm font-semibold">${text}</span>
    `;
    searchBtn.classList.add('opacity-90');
  } else if (stateType === 'done') {
    searchBtn.innerHTML = `
      <svg class="w-3.5 h-3.5 text-white shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/>
      </svg>
      <span class="whitespace-nowrap text-xs sm:text-sm font-semibold">搜索完成</span>
    `;
    searchBtn.classList.remove('opacity-90');
    // 搜索完成后保持 4 秒，随后自动平滑还原为“搜索”；若用户在此期间输入也会立即恢复
    searchBtnResetTimer = setTimeout(() => {
      resetSearchBtn();
    }, 4000);
  }
}

function performSearch() {
  const keyword = searchInput.value.trim();
  if (!keyword) return;

  if (state.eventSource) {
    state.eventSource.close();
  }

  state.tracksSource = 'search';
  state.tracks = [];
  resultsTableBody.innerHTML = '';
  if (sourceChips) sourceChips.innerHTML = '';
  
  // 状态直观呈现在搜索按钮上
  updateSearchBtnState('searching', 0);
  if (statusText) statusText.innerText = '';

  const sourcesParam = Array.from(state.activeSources).join(',');
  const url = `/api/search/stream?q=${encodeURIComponent(keyword)}&sources=${encodeURIComponent(sourcesParam)}`;

  const es = new EventSource(url);
  state.eventSource = es;

  let totalCount = 0;

  es.addEventListener('source_start', () => {});

  es.addEventListener('result', (e) => {
    const track = JSON.parse(e.data);
    track.from_playlist = false;
    state.tracks.push(track);
    totalCount++;
    appendTrackRow(track, totalCount - 1);
    // 实时更新：已找到X首
    updateSearchBtnState('searching', totalCount);
  });

  es.addEventListener('source_done', () => {});

  es.addEventListener('source_error', () => {});

  es.addEventListener('done', (e) => {
    es.close();
    state.eventSource = null;
    // 搜索完成
    updateSearchBtnState('done', totalCount);
    if (totalCount === 0) {
      resultsTableBody.innerHTML = `<tr><td colspan="7" class="py-12 text-center text-slate-400">未检索到相关曲目，请尝试更换关键词或勾选更多音源</td></tr>`;
    }
  });

  es.onerror = () => {
    es.close();
    state.eventSource = null;
    updateSearchBtnState('done', totalCount);
  };
}

function updateSourceChips(stats) {
  // 按需求去除后面展示具体平台的芯片展示
  if (sourceChips) sourceChips.innerHTML = '';
}

function getQualityBadgeHtml(track) {
  if (track.lossless) {
    return '<span class="px-1.5 py-0.5 rounded-md bg-amber-50 border border-amber-200 text-amber-700 text-[10px] font-bold shadow-xs" title="源站无损音质 (FLAC)">无损</span>';
  }
  const isHq = track.quality_type === 'hq' || (track.ext && ['m4a', 'aac'].includes(track.ext.toLowerCase())) || track.quality_label === 'HQ 320K' || track.quality_label === 'HQ' || track.quality_label === '320K';
  if (isHq) {
    const label = track.quality_label || 'HQ';
    return `<span class="px-1.5 py-0.5 rounded-md bg-sky-50 border border-sky-200 text-sky-700 text-[10px] font-semibold shadow-xs" title="超高保真品质 (320kbps / AAC)">${escapeHtml(label)}</span>`;
  }
  const cleanBadgeExt = (track.ext && track.ext.toLowerCase() !== 'none' && track.ext.toLowerCase() !== 'null') ? track.ext.toUpperCase() : 'MP3';
  return `<span class="px-1.5 py-0.5 rounded-md bg-slate-100 border border-slate-200 text-slate-500 text-[10px]" title="标准音质">${escapeHtml(cleanBadgeExt)}</span>`;
}

function getLyricBadgeHtml(hasLyric) {
  if (hasLyric) {
    return '<span class="px-1.5 py-0.5 rounded-md bg-emerald-50 border border-emerald-200 text-emerald-700 text-[10px] font-semibold flex items-center gap-1 shadow-xs" title="含同步LRC歌词"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>词</span>';
  }
  return '<span class="px-1.5 py-0.5 rounded-md bg-slate-100 border border-slate-200 text-slate-400 text-[10px]" title="暂无同步歌词">无词</span>';
}

function getMobileQualityBadgeHtml(track) {
  if (track.lossless) {
    return '<span class="text-[9px] px-1 rounded bg-amber-50 text-amber-700 border border-amber-200 font-bold">无损</span>';
  }
  const isHq = track.quality_type === 'hq' || (track.ext && ['m4a', 'aac'].includes(track.ext.toLowerCase())) || track.quality_label === 'HQ 320K' || track.quality_label === 'HQ' || track.quality_label === '320K';
  if (isHq) {
    return `<span class="text-[9px] px-1 rounded bg-sky-50 text-sky-700 border border-sky-200 font-medium">${escapeHtml(track.quality_label || 'HQ')}</span>`;
  }
  const cleanExt = (track.ext && track.ext.toLowerCase() !== 'none' && track.ext.toLowerCase() !== 'null') ? track.ext.toUpperCase() : 'MP3';
  return `<span class="text-[9px] px-1 rounded bg-slate-100 text-slate-500 border border-slate-200">${escapeHtml(cleanExt)}</span>`;
}

function getMobileLyricBadgeHtml(hasLyric) {
  if (hasLyric) {
    return '<span class="text-[9px] px-1 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-medium">词</span>';
  }
  return '<span class="text-[9px] px-1 rounded bg-slate-100 text-slate-400 border border-slate-200">无词</span>';
}

function updateTrackRowBadges(token, updatedData) {
  const index = state.tracks.findIndex(t => t.token === token);
  if (index === -1) return;
  const track = state.tracks[index];
  Object.assign(track, updatedData);

  const row = document.querySelector(`.track-row[data-index="${index}"]`);
  if (!row) return;

  const qualitySpan = row.querySelector('.track-quality-badge');
  if (qualitySpan) qualitySpan.innerHTML = getQualityBadgeHtml(track);

  const lyricSpan = row.querySelector('.track-lyric-badge');
  if (lyricSpan) lyricSpan.innerHTML = getLyricBadgeHtml(track.has_lyric);

  const mobileQ = row.querySelector('.mobile-quality-badge');
  if (mobileQ) mobileQ.innerHTML = getMobileQualityBadgeHtml(track);

  const mobileL = row.querySelector('.mobile-lyric-badge');
  if (mobileL) mobileL.innerHTML = getMobileLyricBadgeHtml(track.has_lyric);

  if (state.currentTrack && state.currentTrack.token === token) {
    const cleanExtName = (track.ext && track.ext.toLowerCase() !== 'none' && track.ext.toLowerCase() !== 'null') ? track.ext.toUpperCase() : 'HQ';
    const qualityDesc = track.lossless ? '无损原声' : (track.quality_type === 'hq' ? '超高品质' : '标准品质');
    fsExtBadge.innerText = `${cleanExtName} · ${qualityDesc}`;
  }
}

function appendTrackRow(track, index) {
  const tr = document.createElement('tr');
  tr.className = 'track-row cursor-pointer';
  tr.dataset.index = index;

  const qualityBadge = `<span class="track-quality-badge inline-flex items-center">${getQualityBadgeHtml(track)}</span>`;
  const lyricBadge = `<span class="track-lyric-badge inline-flex items-center">${getLyricBadgeHtml(track.has_lyric)}</span>`;

  const isFromPlaylist = Boolean(track.from_playlist || state.tracksSource === 'playlist');
  const downloadBtnHtml = isFromPlaylist ? '' : `
        <button class="row-download-btn p-1.5 rounded-lg text-slate-400 hover:text-emerald-700 hover:bg-emerald-100/80 transition" title="下载音频">
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
        </button>
  `;

  tr.innerHTML = `
    <td class="py-2.5 sm:py-3 px-2 sm:px-3 text-center text-slate-400 text-[11px] sm:text-xs font-mono whitespace-nowrap">${index + 1}</td>
    <td class="py-2.5 sm:py-3 px-3 sm:px-4 font-medium text-slate-800">
      <div class="min-w-0">
        <div class="text-xs sm:text-sm font-medium text-slate-800 hover:text-emerald-600 transition break-words" title="${escapeHtml(track.song_name)}">${escapeHtml(track.song_name)}</div>
        <div class="text-[11px] text-slate-500 sm:hidden flex flex-wrap items-center gap-1.5 mt-0.5">
          <span class="truncate max-w-[140px]">${escapeHtml(track.singers)}</span>
          <span class="text-[10px] px-1 py-0.2 rounded bg-emerald-50/90 text-emerald-800 border border-emerald-200/60 font-mono">${track.source_short}</span>
          <span class="mobile-quality-badge inline-flex items-center">${getMobileQualityBadgeHtml(track)}</span>
          <span class="mobile-lyric-badge inline-flex items-center">${getMobileLyricBadgeHtml(track.has_lyric)}</span>
        </div>
      </div>
    </td>
    <td class="py-2.5 sm:py-3 px-4 text-slate-600 truncate hidden sm:table-cell text-xs sm:text-sm" title="${escapeHtml(track.singers)}">${escapeHtml(track.singers)}</td>
    <td class="py-2.5 sm:py-3 px-4 text-slate-400 truncate hidden md:table-cell text-xs sm:text-sm" title="${escapeHtml(track.album || '-')}">${escapeHtml(track.album || '-')}</td>
    <td class="py-2.5 sm:py-3 px-4 hidden sm:table-cell whitespace-nowrap">
      <span class="px-2 py-0.5 rounded-lg text-xs bg-emerald-50/80 border border-emerald-200/70 text-emerald-800 font-mono whitespace-nowrap">${track.source_short}</span>
    </td>
    <td class="py-2.5 sm:py-3 px-4 hidden lg:table-cell text-xs text-slate-500 whitespace-nowrap">
      <div class="flex items-center gap-1.5 whitespace-nowrap">
        ${qualityBadge}
        ${lyricBadge}
        <span class="text-slate-400 text-[11px] font-mono">${track.file_size || track.duration}</span>
      </div>
    </td>
    <td class="py-2.5 sm:py-3 px-1 sm:px-4 text-center whitespace-nowrap">
      <div class="flex items-center justify-center gap-1">
        <button class="play-btn p-1.5 rounded-lg text-slate-400 hover:text-emerald-700 hover:bg-emerald-100/80 transition" title="立即试听">
          <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
        </button>
        ${downloadBtnHtml}
      </div>
    </td>
  `;

  // Row events
  tr.ondblclick = () => playTrack(index);
  tr.querySelector('.play-btn').onclick = (e) => {
    e.stopPropagation();
    playTrack(index);
  };
  const rowDlBtn = tr.querySelector('.row-download-btn');
  if (rowDlBtn) {
    rowDlBtn.onclick = (e) => {
      e.stopPropagation();
      requestDownload(track);
    };
  }

  resultsTableBody.appendChild(tr);
}

searchInput.onkeydown = (e) => {
  if (e.key === 'Enter') performSearch();
};
searchInput.oninput = () => {
  if (!state.eventSource) {
    resetSearchBtn();
  }
};
searchBtn.onclick = performSearch;

// 5. Fullscreen Player & Controller Logic
function openFullscreenPlayer() {
  if (state.isFullscreenOpen) return;
  fullscreenPlayer.classList.remove('hidden');
  fullscreenPlayer.scrollTop = 0;
  const fsMain = fullscreenPlayer.querySelector('main');
  if (fsMain) fsMain.scrollTop = 0;
  requestAnimationFrame(() => {
    fullscreenPlayer.classList.add('player-open');
  });
  state.isFullscreenOpen = true;
  if (audioElement && audioElement.currentTime) {
    syncLyric(audioElement.currentTime);
  }
}

function closeFullscreenPlayer() {
  if (!state.isFullscreenOpen) return;
  fullscreenPlayer.classList.remove('player-open');
  setTimeout(() => {
    if (!state.isFullscreenOpen) {
      fullscreenPlayer.classList.add('hidden');
    }
  }, 450);
  state.isFullscreenOpen = false;
}

function updatePlayerCover(coverUrl) {
  const finalCover = coverUrl || 'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 60 60%22><rect fill=%22%23e2e8f0%22 width=%2260%22 height=%2260%22/></svg>';
  if (playerCover) {
    playerCover.src = finalCover;
  }
  if (fsCoverImg) {
    fsCoverImg.src = finalCover;
  }
  if (fsBgBlur) {
    if (coverUrl && coverUrl.startsWith('http') || (coverUrl && coverUrl.startsWith('/api/cover/'))) {
      fsBgBlur.style.backgroundImage = `url('${coverUrl}')`;
    } else {
      fsBgBlur.style.backgroundImage = 'none';
    }
  }
}

function playTrack(index, autoOpenPlayer = true) {
  if (index < 0 || index >= state.tracks.length) return;
  state.currentTrackIndex = index;
  const track = state.tracks[index];
  state.currentTrack = track;
  track._healTried = false; // 用户主动点击播放，重置自愈状态，保证重试机会

  // 1. Update list highlight
  document.querySelectorAll('.track-row').forEach(r => r.classList.remove('playing'));
  const activeRow = document.querySelector(`.track-row[data-index="${index}"]`);
  if (activeRow) activeRow.classList.add('playing');

  // 2. Update mini footer player
  playerTitle.innerText = track.song_name;
  playerArtist.innerText = `${track.singers} · ${track.source_label || ''}`;
  const effectiveCover = track.cover_url || (track.token ? `/api/cover/${track.token}` : '');
  updatePlayerCover(effectiveCover);

  // 3. Update Fullscreen Player details
  fsHeaderTitle.innerText = track.song_name;
  fsHeaderArtist.innerText = `${track.singers} · ${track.source_label || ''}`;
  fsSourceBadge.innerText = track.source_label || '主流音源';
  const cleanExtName = (track.ext && track.ext.toLowerCase() !== 'none' && track.ext.toLowerCase() !== 'null') ? track.ext.toUpperCase() : 'HQ';
  const qualityDesc = track.lossless ? '无损原声' : (track.quality_type === 'hq' ? '超高品质' : '标准品质');
  fsExtBadge.innerText = `${cleanExtName} · ${qualityDesc}`;

  // 控制底部与全屏播放器下载按钮显隐：歌单曲目隐藏，搜索曲目显示
  const isFromPlaylist = Boolean(track.from_playlist || state.tracksSource === 'playlist');
  if (downloadDirectBtn) {
    if (isFromPlaylist) {
      downloadDirectBtn.classList.add('hidden');
    } else {
      downloadDirectBtn.classList.remove('hidden');
    }
  }
  if (fsDownloadBtn) {
    if (isFromPlaylist) {
      fsDownloadBtn.classList.add('hidden');
    } else {
      fsDownloadBtn.classList.remove('hidden');
    }
  }

  // 4. Set audio stream and start playing
  state.predictedNextIndex = -1;
  if (track.stream_url) {
    audioElement.src = track.stream_url;
    audioElement.play().then(() => {
      updatePlayPauseIcon(true);
      preloadAndHealNextTrack();
    }).catch(e => {
      console.error('Play error:', e);
      preloadAndHealNextTrack();
    });
  } else {
    // 尚未获取流链接（例如歌单刚秒开载入中），显示转圈缓冲态，绝不设空src避免浏览器触发假错误
    updatePlayPauseIcon(false, true);
    if (playerArtist) playerArtist.innerText = `🔄 正在准备音频流...`;
    if (fsHeaderArtist) fsHeaderArtist.innerText = `🔄 正在准备音频流...`;
  }

  // 5. Fetch lyrics
  if (track.token) {
    loadLyric(track.token);
    fetch(`/api/track/info/${track.token}`).then(r => r.json()).then(latest => {
      if (latest && !latest.error) {
        updateTrackRowBadges(track.token, latest);
        if (latest.cover_url && state.currentTrack && state.currentTrack.token === track.token) {
          updatePlayerCover(latest.cover_url);
        }
      }
    }).catch(() => {});
  }

  // 6. 核心需求：播放时自动进入播放器
  if (autoOpenPlayer) {
    openFullscreenPlayer();
  }
}

function updatePlayPauseIcon(isPlaying, isLoading = false) {
  if (isLoading) {
    playIcon.classList.add('hidden');
    pauseIcon.classList.add('hidden');
    loadingIcon.classList.remove('hidden');
    fsPlayIcon.classList.add('hidden');
    fsPauseIcon.classList.add('hidden');
    fsLoadingIcon.classList.remove('hidden');
    return;
  }
  loadingIcon.classList.add('hidden');
  fsLoadingIcon.classList.add('hidden');

  if (isPlaying) {
    playIcon.classList.add('hidden');
    pauseIcon.classList.remove('hidden');
    fsPlayIcon.classList.add('hidden');
    fsPauseIcon.classList.remove('hidden');

    vinylDisc.classList.add('spin-playing');
    vinylDisc.classList.remove('spin-paused');
    vinylNeedle.classList.add('needle-playing');
    vinylNeedle.classList.remove('needle-paused');
  } else {
    playIcon.classList.remove('hidden');
    pauseIcon.classList.add('hidden');
    fsPlayIcon.classList.remove('hidden');
    fsPauseIcon.classList.add('hidden');

    vinylDisc.classList.add('spin-paused');
    vinylNeedle.classList.remove('needle-playing');
    vinylNeedle.classList.add('needle-paused');
  }
}

playPauseBtn.onclick = () => {
  if (!audioElement.src) {
    if (state.tracks.length > 0) playTrack(0, true);
    return;
  }
  if (audioElement.paused) {
    audioElement.play();
    updatePlayPauseIcon(true);
  } else {
    audioElement.pause();
    updatePlayPauseIcon(false);
  }
};
fsPlayPauseBtn.onclick = playPauseBtn.onclick;

function setPlayMode(mode) {
  state.playMode = mode;
  modeLoopIcon.classList.toggle('hidden', mode !== 'loop');
  modeRepeatOneIcon.classList.toggle('hidden', mode !== 'one');
  modeShuffleIcon.classList.toggle('hidden', mode !== 'shuffle');
  if (mode === 'loop') fsModeLabel.innerText = '列表循环';
  else if (mode === 'one') fsModeLabel.innerText = '单曲循环';
  else if (mode === 'shuffle') fsModeLabel.innerText = '随机播放';
}

fsPlayModeBtn.onclick = () => {
  if (state.playMode === 'loop') setPlayMode('one');
  else if (state.playMode === 'one') setPlayMode('shuffle');
  else setPlayMode('loop');
  showToast(`播放模式: ${fsModeLabel.innerText}`);
  // 模式切换时重新确定下一首预定目标并触发预检
  resolveNextTrackIndex(true);
  preloadAndHealNextTrack();
};

function resolveNextTrackIndex(forceRecompute = false) {
  if (state.tracks.length === 0) return -1;
  if (state.tracks.length === 1) return 0;

  if (state.playMode === 'one') {
    return state.currentTrackIndex >= 0 ? state.currentTrackIndex : 0;
  }

  // 若已有预测缓存且未强制重新计算，且索引有效且不等于当前正在播放的曲目，则直接返回
  if (!forceRecompute && state.predictedNextIndex >= 0 && state.predictedNextIndex < state.tracks.length) {
    if (state.playMode === 'loop' || state.predictedNextIndex !== state.currentTrackIndex) {
      return state.predictedNextIndex;
    }
  }

  let nextIdx = -1;
  if (state.playMode === 'shuffle') {
    if (state.tracks.length > 1) {
      do {
        nextIdx = Math.floor(Math.random() * state.tracks.length);
      } while (nextIdx === state.currentTrackIndex);
    } else {
      nextIdx = 0;
    }
  } else {
    // 默认列表循环 loop
    if (state.currentTrackIndex < state.tracks.length - 1) {
      nextIdx = state.currentTrackIndex + 1;
    } else {
      nextIdx = 0;
    }
  }

  state.predictedNextIndex = nextIdx;
  return nextIdx;
}

let prehealTimer = null;
let prehealAbortController = null;

function preloadAndHealNextTrack() {
  if (prehealTimer) {
    clearTimeout(prehealTimer);
    prehealTimer = null;
  }
  if (prehealAbortController) {
    try { prehealAbortController.abort(); } catch (e) {}
    prehealAbortController = null;
  }

  // 单曲循环或曲目少于2首时无需预检不同曲目
  if (state.playMode === 'one' || state.tracks.length <= 1) return;

  prehealTimer = setTimeout(async () => {
    const nextIdx = resolveNextTrackIndex(false);
    if (nextIdx < 0 || nextIdx >= state.tracks.length || nextIdx === state.currentTrackIndex) return;

    const nextTrack = state.tracks[nextIdx];
    if (!nextTrack || !nextTrack.stream_url) return;

    // 若当前会话中该曲目已完成自愈标记，避免短时间内死循环重复请求
    if (nextTrack._healed) return;

    prehealAbortController = new AbortController();
    const { signal } = prehealAbortController;

    try {
      // 1. 发起极速轻量 Range 探测 (只拉取第 0 字节，流量 < 1KB)
      const testRes = await fetch(nextTrack.stream_url, {
        method: 'GET',
        headers: { 'Range': 'bytes=0-0' },
        signal
      });

      // 2. 如果返回 200 或 206，说明直链健康有效，静默待命
      if (testRes.ok) {
        return;
      }

      // 3. 链接失效 (404/403/502等)，启动后台静默自愈 (选项 A：完全静默无感知)
      console.log(`[Pre-Heal] 检测到下一首《${nextTrack.song_name}》直链失效 (${testRes.status})，正在后台自愈...`);
      const resolveRes = await fetch('/api/track/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          song_name: nextTrack.song_name,
          singers: nextTrack.singers,
          source: nextTrack.source
        }),
        signal
      });

      const resolveData = await resolveRes.json();
      if (resolveData.success && resolveData.track) {
        const healedTrack = resolveData.track;
        healedTrack._healed = true;

        // 更新 tracks 数组对应项为最新健康通道
        state.tracks[nextIdx] = healedTrack;
        // 同步更新本地歌单持久化存储
        updatePlaylistTrackCache(nextTrack, healedTrack);
        console.log(`[Pre-Heal] 下一首《${healedTrack.song_name}》后台自愈成功并已无缝刷新缓存`);
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.warn(`[Pre-Heal] 下一首《${nextTrack.song_name}》后台预检异常:`, err);
      }
    }
  }, 1500);
}

function playNextTrack() {
  if (state.tracks.length === 0) return;
  if (state.playMode === 'one') {
    audioElement.currentTime = 0;
    audioElement.play().catch(e => console.warn('Replay error:', e));
    return;
  }
  const nextIdx = resolveNextTrackIndex(false);
  state.predictedNextIndex = -1; // 消费后重置
  if (nextIdx >= 0) {
    playTrack(nextIdx, false);
  }
}

function playPrevTrack() {
  if (state.tracks.length === 0) return;
  state.predictedNextIndex = -1; // 手动切到上一首时重置预测目标
  if (state.currentTrackIndex > 0) {
    playTrack(state.currentTrackIndex - 1, false);
  } else {
    playTrack(state.tracks.length - 1, false);
  }
}

nextBtn.onclick = playNextTrack;
fsNextBtn.onclick = playNextTrack;
prevBtn.onclick = playPrevTrack;
fsPrevBtn.onclick = playPrevTrack;

function updatePlaylistTrackCache(oldTrack, newTrack) {
  try {
    const list = getMyPlaylists();
    let changed = false;
    list.forEach(pl => {
      if (Array.isArray(pl.tracks)) {
        pl.tracks.forEach((t, idx) => {
          if (t.token === oldTrack.token || (t.song_name === oldTrack.song_name && t.singers === oldTrack.singers)) {
            pl.tracks[idx] = { ...t, ...newTrack };
            changed = true;
          }
        });
      }
    });
    if (changed) {
      saveMyPlaylists(list);
    }
  } catch (e) {
    console.error('Update track cache error:', e);
  }
}

function showResolvingState(songName, isResolving, isSuccess = false, msg = '') {
  if (isResolving) {
    // 播放按钮切为 loading 旋转态
    updatePlayPauseIcon(false, true);

    // 底部与全屏副标题提示
    if (playerArtist) playerArtist.innerText = `🔄 正在获取歌曲链接...`;
    if (fsHeaderArtist) fsHeaderArtist.innerText = `🔄 正在获取歌曲链接，请稍候...`;

    // 若当前歌词未就绪，歌词区提示
    if (state.lyrics.length === 0) {
      if (fsLyricContainer) {
        fsLyricContainer.innerHTML = '<div class="text-emerald-700/80 font-medium text-base py-32 text-center animate-pulse">正在获取有效播放链接，请稍候...</div>';
      }
      if (lyricContainer) {
        lyricContainer.innerHTML = '<div class="text-emerald-700/80 font-medium text-sm py-20 text-center animate-pulse">正在获取有效播放链接...</div>';
      }
    }
  } else {
    if (!isSuccess) {
      updatePlayPauseIcon(false);
    }
  }
}

audioElement.onerror = async () => {
  if (!state.currentTrack) return;
  const track = state.currentTrack;
  if (track._healTried) {
    showResolvingState(track.song_name, false, false, '通道重连失败，可能源站已下架');
    showToast(`《${track.song_name}》音源通道重连失败，可能源站已下架`);
    updatePlayPauseIcon(false);
    return;
  }
  track._healTried = true;

  // 醒目提示：显示居中横幅、副标题动态更新、播放按钮转圈
  showResolvingState(track.song_name, true);
  showToast(`正在智能恢复《${track.song_name}》的可用音源通道...`);

  try {
    const data = await safeFetchJson('/api/track/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        song_name: track.song_name,
        singers: track.singers,
        source: track.source
      })
    });
    if (data.success && data.track) {
      const newTrack = data.track;
      newTrack._healTried = true;
      state.tracks[state.currentTrackIndex] = newTrack;
      state.currentTrack = newTrack;
      updatePlaylistTrackCache(track, newTrack);

      playerTitle.innerText = newTrack.song_name;
      playerArtist.innerText = `${newTrack.singers} · ${newTrack.source_label}`;
      fsHeaderTitle.innerText = newTrack.song_name;
      fsHeaderArtist.innerText = `${newTrack.singers} · ${newTrack.source_label}`;
      if (newTrack.cover_url) {
        playerCover.src = newTrack.cover_url;
        fsCoverImg.src = newTrack.cover_url;
        fsBgBlur.style.backgroundImage = `url('${newTrack.cover_url}')`;
      }

      showResolvingState(newTrack.song_name, false, true, '最新通道已连接并开始播放');
      audioElement.src = newTrack.stream_url;
      audioElement.play().then(() => {
        updatePlayPauseIcon(true);
        showToast(`已成功恢复《${newTrack.song_name}》最新通道并开始播放`);
        preloadAndHealNextTrack();
      }).catch(err => {
        console.warn('Autoplay error:', err);
        updatePlayPauseIcon(false);
      });
      loadLyric(newTrack.token);
    } else {
      showResolvingState(track.song_name, false, false, '音源暂无法自动重连');
      showToast(`《${track.song_name}》音源暂无法自动重连，可在【我的歌单】点击“刷新同步”`);
      playerArtist.innerText = `${track.singers} · ${track.source_label}`;
      fsHeaderArtist.innerText = `${track.singers} · ${track.source_label}`;
      updatePlayPauseIcon(false);
    }
  } catch (err) {
    showResolvingState(track.song_name, false, false, err.message || '网络连接异常');
    showToast(`《${track.song_name}》连接异常: ${err.message}`);
    playerArtist.innerText = `${track.singers} · ${track.source_label}`;
    fsHeaderArtist.innerText = `${track.singers} · ${track.source_label}`;
    updatePlayPauseIcon(false);
  }
};

audioElement.onplay = () => {
  updatePlayPauseIcon(true);
  if (state.currentTrack) {
    const t = state.currentTrack;
    const artistText = `${t.singers} · ${t.source_label || '主流音源'}`;
    if (playerArtist) playerArtist.innerText = artistText;
    if (fsHeaderArtist) fsHeaderArtist.innerText = artistText;
  }
};

audioElement.onpause = () => {
  updatePlayPauseIcon(false);
};

audioElement.onended = () => {
  playNextTrack();
};

audioElement.ontimeupdate = () => {
  if (!audioElement.duration) return;
  const current = audioElement.currentTime;
  const duration = audioElement.duration;
  const percent = (current / duration) * 100;
  
  seekSlider.value = percent;
  fsSeekSlider.value = percent;

  const currentFormatted = formatTime(current);
  const durationFormatted = formatTime(duration);

  currentTimeText.innerText = currentFormatted;
  fsCurrentTime.innerText = currentFormatted;
  durationText.innerText = durationFormatted;
  fsDuration.innerText = durationFormatted;

  syncLyric(current);
};

const handleSeek = (slider) => {
  if (!audioElement.duration) return;
  const target = (slider.value / 100) * audioElement.duration;
  audioElement.currentTime = target;
};

seekSlider.oninput = () => handleSeek(seekSlider);
fsSeekSlider.oninput = () => handleSeek(fsSeekSlider);

volumeSlider.oninput = () => {
  audioElement.volume = volumeSlider.value;
  fsVolumeSlider.value = volumeSlider.value;
};

fsVolumeSlider.oninput = () => {
  audioElement.volume = fsVolumeSlider.value;
  volumeSlider.value = fsVolumeSlider.value;
};

if (downloadDirectBtn) {
  downloadDirectBtn.onclick = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (state.currentTrack) {
      requestDownload(state.currentTrack);
    } else if (state.tracks.length > 0) {
      requestDownload(state.tracks[0]);
    }
  };
}

if (fsDownloadBtn) {
  fsDownloadBtn.onclick = () => {
    if (state.currentTrack) {
      requestDownload(state.currentTrack);
    }
  };
}

// 交互唤出与收起大播放器
fsCloseBtn.onclick = closeFullscreenPlayer;
playerTrackInfo.onclick = openFullscreenPlayer;
if (expandPlayerBtn) {
  expandPlayerBtn.onclick = openFullscreenPlayer;
}

// 快捷键支持
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (!myPlaylistsModal.classList.contains('hidden')) {
      closePlaylistsModal();
    } else if (state.isFullscreenOpen) {
      closeFullscreenPlayer();
    }
  } else if (e.code === 'Space' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
    e.preventDefault();
    playPauseBtn.click();
  }
});

// 6. Lyrics Parser & Synchronizer
async function loadLyric(token) {
  state.lyrics = [];
  state.currentLyricIndex = -1;

  const track = state.currentTrack;

  // 1. 若当前曲目已带有歌词缓存，优先秒级预渲染
  if (track && track.lyric) {
    parseLyric(track.lyric);
    renderLyric();
  } else {
    lyricContainer.innerHTML = '<div class="text-slate-400 font-medium text-sm py-20 text-center flex items-center justify-center gap-2"><svg class="animate-spin h-4 w-4 text-emerald-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg>正在同步高品质歌词...</div>';
    fsLyricContainer.innerHTML = '<div class="text-slate-400 font-medium text-base py-32 text-center flex items-center justify-center gap-2"><svg class="animate-spin h-5 w-5 text-emerald-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg>正在同步高品质歌词...</div>';
  }

  // 2. 从服务端取回或更新（携带曲目元数据作为多重兜底，防 token 失效）
  try {
    let url = `/api/lyric/${token}`;
    if (track) {
      const p = new URLSearchParams();
      if (track.song_name) p.append('song_name', track.song_name);
      if (track.singers) p.append('singers', track.singers);
      if (track.identifier) p.append('song_id', track.identifier);
      if (track.source) p.append('source', track.source);
      const qs = p.toString();
      if (qs) url += `?${qs}`;
    }

    const res = await fetch(url);
    const data = await res.json();
    if (data && data.lyric) {
      if (state.currentTrack) {
        state.currentTrack.lyric = data.lyric;
        state.currentTrack.has_lyric = true;
      }
      updateTrackRowBadges(token, { lyric: data.lyric, has_lyric: true });
      parseLyric(data.lyric);
      renderLyric();
      return;
    }

    // 3. 客户端双轨直通自愈：若境外服务器接口偶发受限，国内用户浏览器直连高可用通道
    if (track && track.identifier && /^\d+$/.test(track.identifier)) {
      try {
        const clientRes = await fetch(`https://api.injahow.cn/meting/?type=lrc&id=${track.identifier}`);
        if (clientRes.ok) {
          const clientLrc = await clientRes.text();
          if (clientLrc && clientLrc.length > 20 && clientLrc.includes('[')) {
            if (state.currentTrack) {
              state.currentTrack.lyric = clientLrc;
              state.currentTrack.has_lyric = true;
            }
            updateTrackRowBadges(token, { lyric: clientLrc, has_lyric: true });
            parseLyric(clientLrc);
            renderLyric();
            return;
          }
        }
      } catch (e) {
        // ignore client fallback error
      }
    }

    if (!state.lyrics.length) {
      if (state.currentTrack && state.currentTrack.token === token) {
        state.currentTrack.has_lyric = false;
      }
      updateTrackRowBadges(token, { has_lyric: false });
      const retryBtn = `<button type="button" class="ml-2 text-emerald-400 hover:text-emerald-300 underline font-medium cursor-pointer" onclick="loadLyric('${token}')">点击重试</button>`;
      lyricContainer.innerHTML = `<div class="text-slate-400 font-medium text-sm py-20 text-center">暂未提供同步歌词 ${retryBtn}</div>`;
      fsLyricContainer.innerHTML = `<div class="text-slate-400 font-medium text-base py-32 text-center">暂未提供同步歌词 ${retryBtn}</div>`;
    }
  } catch (err) {
    // 若请求发生网络故障，也尝试客户端直连兜底
    if (track && track.identifier && /^\d+$/.test(track.identifier)) {
      try {
        const clientRes = await fetch(`https://api.injahow.cn/meting/?type=lrc&id=${track.identifier}`);
        if (clientRes.ok) {
          const clientLrc = await clientRes.text();
          if (clientLrc && clientLrc.length > 20 && clientLrc.includes('[')) {
            if (state.currentTrack) {
              state.currentTrack.lyric = clientLrc;
              state.currentTrack.has_lyric = true;
            }
            updateTrackRowBadges(token, { lyric: clientLrc, has_lyric: true });
            parseLyric(clientLrc);
            renderLyric();
            return;
          }
        }
      } catch (e) {
        // ignore
      }
    }
    if (!state.lyrics.length) {
      if (state.currentTrack && state.currentTrack.token === token) {
        state.currentTrack.has_lyric = false;
      }
      updateTrackRowBadges(token, { has_lyric: false });
      const retryBtn = `<button type="button" class="ml-2 text-emerald-400 hover:text-emerald-300 underline font-medium cursor-pointer" onclick="loadLyric('${token}')">点击重试</button>`;
      lyricContainer.innerHTML = `<div class="text-rose-400 text-sm py-20 text-center">获取歌词失败 ${retryBtn}</div>`;
      fsLyricContainer.innerHTML = `<div class="text-rose-400 text-base py-32 text-center">获取歌词失败 ${retryBtn}</div>`;
    }
  }
}

function parseLyric(lrcText) {
  if (!lrcText || typeof lrcText !== 'string') {
    state.lyrics = [];
    return;
  }
  const lines = lrcText.split(/\r?\n/);
  const result = [];
  let offsetMs = 0;

  // 1. 预扫描 offset 时间偏移量标签（标准毫秒偏移，彻底修复整体快慢偏差）
  for (let line of lines) {
    const offsetMatch = line.trim().match(/^\[offset:\s*([+-]?\d+)\]/i);
    if (offsetMatch) {
      offsetMs = parseInt(offsetMatch[1], 10) || 0;
      break;
    }
  }

  // 智能匹配形如 [00:12.34], [0:12.345], [01:23:45], [00:12] 等格式
  const timeRegex = /\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]/g;

  for (let line of lines) {
    line = line.trim();
    if (!line) continue;
    // 忽略元数据标签行
    if (/^\[(ti|ar|al|by|offset|length|re|ve):/i.test(line)) {
      continue;
    }

    const times = [];
    let match;
    timeRegex.lastIndex = 0; // 关键：循环每次强制重置正则游标，彻底消灭漏行！
    while ((match = timeRegex.exec(line)) !== null) {
      const min = parseInt(match[1], 10);
      const sec = parseInt(match[2], 10);
      let ms = 0;
      if (match[3]) {
        ms = parseInt(match[3].padEnd(3, '0').slice(0, 3), 10);
      }
      // LRC 标准规范：根据 offset 偏移量毫秒级校准真实播放时间轴
      const totalSec = min * 60 + sec + ms / 1000 + offsetMs / 1000;
      times.push(Math.max(0, totalSec));
    }

    // 剔除时间戳后的纯文本
    const text = line.replace(/\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]/g, '').trim();
    if (text && times.length > 0) {
      times.forEach(t => result.push({ time: t, text }));
    }
  }

  result.sort((a, b) => a.time - b.time);
  state.lyrics = result;
}

function renderLyric() {
  lyricContainer.innerHTML = '';
  fsLyricContainer.innerHTML = '';

  if (state.lyrics.length === 0) {
    lyricContainer.innerHTML = '<div class="text-slate-400 font-medium text-sm py-20 text-center">纯音乐或无歌词</div>';
    fsLyricContainer.innerHTML = '<div class="text-slate-400 font-medium text-base py-32 text-center">纯音乐或无歌词</div>';
    return;
  }

  state.lyrics.forEach((item, idx) => {
    // 侧边栏歌词
    const p = document.createElement('p');
    p.className = 'lyric-line';
    p.dataset.index = idx;
    p.innerText = item.text;
    p.onclick = () => {
      audioElement.currentTime = item.time;
    };
    lyricContainer.appendChild(p);

    // 全屏沉浸式大歌词
    const fsP = document.createElement('p');
    fsP.className = 'fs-lyric-line';
    fsP.dataset.fsIndex = idx;
    fsP.innerText = item.text;
    fsP.onclick = () => {
      audioElement.currentTime = item.time;
    };
    fsLyricContainer.appendChild(fsP);
  });
}

function syncLyric(currentTime) {
  if (state.lyrics.length === 0) return;
  let idx = 0;
  for (let i = 0; i < state.lyrics.length; i++) {
    if (currentTime >= state.lyrics[i].time) {
      idx = i;
    } else {
      break;
    }
  }

  if (idx !== state.currentLyricIndex) {
    state.currentLyricIndex = idx;
    
    // 1. 侧边栏小抽屉歌词同步
    document.querySelectorAll('.lyric-line').forEach(el => el.classList.remove('active'));
    const target = document.querySelector(`.lyric-line[data-index="${idx}"]`);
    if (target && lyricContainer) {
      target.classList.add('active');
      const containerH = lyricContainer.clientHeight;
      const targetTop = target.offsetTop;
      const targetH = target.clientHeight;
      lyricContainer.scrollTo({
        top: Math.max(0, targetTop - (containerH / 2) + (targetH / 2)),
        behavior: 'smooth'
      });
    }

    // 2. 全屏大播放器歌词同步高亮与居中滚动 (容器级精准滚动，绝不连带滚动外层页面)
    document.querySelectorAll('.fs-lyric-line').forEach(el => el.classList.remove('fs-lyric-active'));
    const fsTarget = document.querySelector(`.fs-lyric-line[data-fs-index="${idx}"]`);
    if (fsTarget && fsLyricContainer) {
      fsTarget.classList.add('fs-lyric-active');
      const containerH = fsLyricContainer.clientHeight;
      const targetTop = fsTarget.offsetTop;
      const targetH = fsTarget.clientHeight;
      fsLyricContainer.scrollTo({
        top: Math.max(0, targetTop - (containerH / 2) + (targetH / 2)),
        behavior: 'smooth'
      });
    }
  }
}

// 侧边栏抽屉歌词按钮保留支持
if (footerLyricBtn) {
  footerLyricBtn.onclick = () => lyricModal.classList.toggle('translate-x-full');
}
if (closeLyricBtn) {
  closeLyricBtn.onclick = () => lyricModal.classList.add('translate-x-full');
}


// 7. Playlist Parsing
parsePlaylistBtn.onclick = async () => {
  const url = playlistUrlInput.value.trim();
  if (!url) return;

  parsePlaylistBtn.disabled = true;
  parsePlaylistBtn.innerText = '正在解析中...';

  try {
    const data = await safeFetchJson('/api/playlist/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    if (data.error) {
      alert(data.error);
      return;
    }

    state.playlistTracks = data.tracks || [];
    playlistCountText.innerText = `解析成功：来自 ${data.source_label || data.source}，共 ${state.playlistTracks.length} 首歌曲`;
    playlistResultCard.classList.remove('hidden');
    renderPlaylistTable();
  } catch (err) {
    alert('解析歌单请求出错: ' + err.message);
  } finally {
    parsePlaylistBtn.disabled = false;
    parsePlaylistBtn.innerText = '解析歌单';
  }
};

function renderPlaylistTable() {
  playlistTableBody.innerHTML = '';
  state.playlistTracks.forEach((t, i) => {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-emerald-50/70 transition cursor-pointer text-xs';
    tr.innerHTML = `
      <td class="py-2.5 px-4 text-slate-400 font-mono">${i + 1}</td>
      <td class="py-2.5 px-4 font-medium text-slate-800">
        <div class="flex items-center gap-1.5">
          <span class="truncate font-semibold text-slate-800">${escapeHtml(t.song_name)}</span>
          ${t.has_lyric ? '<span class="px-1.5 py-0.2 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 text-[10px] shrink-0 font-medium">词</span>' : '<span class="text-slate-400 text-[10px] shrink-0">无词</span>'}
        </div>
      </td>
      <td class="py-2.5 px-4 text-slate-600">${escapeHtml(t.singers)}</td>
      <td class="py-2.5 px-4 text-slate-400 font-mono">${t.duration}</td>
      <td class="py-2.5 px-4 text-right">
        <button class="playlist-dl-btn text-emerald-600 hover:text-emerald-700 font-medium hover:underline">下载</button>
      </td>
    `;
    tr.querySelector('.playlist-dl-btn').onclick = (e) => {
      e.stopPropagation();
      requestDownload(t);
    };
    playlistTableBody.appendChild(tr);
  });
}

async function loadAndPlayPlaylist(tracks, targetIdx = 0) {
  if (!tracks || tracks.length === 0) {
    showToast('该歌单内暂无曲目');
    return;
  }
  targetIdx = Math.max(0, Math.min(targetIdx, tracks.length - 1));

  // 1.【0毫秒瞬间响应】：立即关闭弹窗，切到主页展示区，铺满表格，打开全屏播放界面！
  closePlaylistsModal();
  tabSearchBtn.click();
  state.tracksSource = 'playlist';
  const playlistTracks = (tracks || []).map(t => ({ ...t, from_playlist: true }));
  state.tracks = playlistTracks;
  resultsTableBody.innerHTML = '';
  state.tracks.forEach((t, i) => appendTrackRow(t, i));
  playTrack(targetIdx, true);

  // 2.【后台毫秒级静默激活】：换取会话令牌并无缝接入正式音频流与歌词
  try {
    const res = await safeFetchJson('/api/playlist/activate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tracks: tracks })
    });
    if (res && res.tracks && res.tracks.length > 0) {
      state.tracks = res.tracks.map(t => ({ ...t, from_playlist: true }));
      // 重新渲染表格
      resultsTableBody.innerHTML = '';
      state.tracks.forEach((t, i) => appendTrackRow(t, i));
      const activeRow = document.querySelector(`.track-row[data-index="${targetIdx}"]`);
      if (activeRow) activeRow.classList.add('playing');

      const curTrack = state.tracks[targetIdx];
      state.currentTrack = curTrack;
      if (curTrack) {
        const activeCover = curTrack.cover_url || `/api/cover/${curTrack.token}`;
        updatePlayerCover(activeCover);
        curTrack.cover_url = activeCover;
        updatePlaylistTrackCache(curTrack, { cover_url: activeCover });

        if (curTrack.stream_url) {
          const artistText = `${curTrack.singers} · ${curTrack.source_label || '主流音源'}`;
          if (playerArtist) playerArtist.innerText = artistText;
          if (fsHeaderArtist) fsHeaderArtist.innerText = artistText;

          audioElement.src = curTrack.stream_url;
          audioElement.play().then(() => {
            updatePlayPauseIcon(true);
            preloadAndHealNextTrack();
          }).catch(err => {
            console.warn('Autoplay failed:', err);
            updatePlayPauseIcon(false);
          });
          loadLyric(curTrack.token);
          fetch(`/api/track/info/${curTrack.token}`).then(r => r.json()).then(latest => {
            if (latest && !latest.error) {
              updateTrackRowBadges(curTrack.token, latest);
              if (latest.cover_url && state.currentTrack && state.currentTrack.token === curTrack.token) {
                updatePlayerCover(latest.cover_url);
              }
            }
          }).catch(() => {});
        }
      }
    }
  } catch (e) {
    console.error('Playlist activate error:', e);
  }
}

playlistDownloadAllBtn.onclick = () => {
  loadAndPlayPlaylist(state.playlistTracks, 0);
};

// 8. 我的歌单管理与跨设备数据中心 (Local Storage 纯元数据持久化)
const STORAGE_KEY_MY_PLAYLISTS = 'soundflow_my_playlists';

function cleanTrackForStorage(track) {
  if (!track || typeof track !== 'object') return null;
  return {
    song_name: String(track.song_name || '未知曲目').trim(),
    singers: String(track.singers || '未知歌手').trim(),
    album: String(track.album || '').trim(),
    source: String(track.source || 'QQMusicClient').trim(),
    source_label: String(track.source_label || '').trim(),
    source_short: String(track.source_short || '').trim(),
    identifier: String(track.identifier || '').trim(),
    duration: String(track.duration || '00:00').trim(),
    cover_url: String(track.cover_url || '').trim(),
    ext: String(track.ext || 'mp3').trim(),
    quality_label: String(track.quality_label || '').trim(),
    quality_type: String(track.quality_type || 'standard').trim(),
    lossless: Boolean(track.lossless),
    has_lyric: Boolean(track.has_lyric)
  };
}

function getMyPlaylists() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_MY_PLAYLISTS);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return [];
  }
}

function saveMyPlaylists(list) {
  try {
    const cleaned = (list || []).map(pl => {
      const copy = { ...pl };
      if (Array.isArray(copy.tracks)) {
        copy.tracks = copy.tracks.map(cleanTrackForStorage).filter(Boolean);
      }
      return copy;
    });
    localStorage.setItem(STORAGE_KEY_MY_PLAYLISTS, JSON.stringify(cleaned));
  } catch (e) {
    console.error('Save playlists error:', e);
  }
  updateMyPlaylistsBadge();
}

function updateMyPlaylistsBadge() {
  const list = getMyPlaylists();
  if (list.length > 0) {
    myPlaylistsCountBadge.innerText = list.length;
    myPlaylistsCountBadge.classList.remove('hidden');
    modalPlTotalBadge.innerText = list.length;
  } else {
    myPlaylistsCountBadge.classList.add('hidden');
    modalPlTotalBadge.innerText = '0';
  }
}

// 全局解析任务防关闭守卫 (动态唤起强提醒与浏览器关闭拦截)
function updateParsingGuard() {
  const playlists = getMyPlaylists();
  const hasParsingTask = playlists.some(p => p.status === 'parsing');
  const alertEl = document.getElementById('playlistParsingAlert');
  
  if (alertEl) {
    if (hasParsingTask) {
      alertEl.classList.remove('hidden');
    } else {
      alertEl.classList.add('hidden');
    }
  }

  if (hasParsingTask) {
    // 激活原生浏览器关页/刷新拦截保护 (物理级强拦截)
    window.onbeforeunload = function (e) {
      const msg = '⚠️ 当前有歌单正在后台解析中！如果在解析完成前关闭或刷新网页，解析传输将被强制中断。确定要离开吗？';
      e.preventDefault();
      e.returnValue = msg;
      return msg;
    };
  } else {
    // 全部解析完毕，自动解除拦截
    window.onbeforeunload = null;
  }
}

function openPlaylistsModal() {
  myPlaylistsModal.classList.remove('hidden');
  try {
    renderMyPlaylistsCards();
  } catch (err) {
    console.error('Failed to render playlist cards:', err);
  }
}

function closePlaylistsModal() {
  myPlaylistsModal.classList.add('hidden');
  const playlists = getMyPlaylists();
  if (playlists.some(p => p.status === 'parsing')) {
    showToast('⚠️ 提示：歌单仍在后台持续解析中，请保持当前网页开启直至完成！');
  }
}

myPlaylistsBtn.onclick = openPlaylistsModal;
closePlaylistsModalBtn.onclick = closePlaylistsModal;

function detectSourceMeta(url) {
  if (url.includes('163.com')) return '网易云音乐';
  if (url.includes('qq.com')) return 'QQ音乐';
  if (url.includes('kugou.com')) return '酷狗音乐';
  if (url.includes('kuwo.cn')) return '酷我音乐';
  if (url.includes('migu.cn')) return '咪咕音乐';
  if (url.includes('apple.com')) return 'Apple Music';
  if (url.includes('spotify.com')) return 'Spotify';
  if (url.includes('bilibili.com')) return 'B站音乐';
  return '在线歌单';
}

function renderMyPlaylistsCards() {
  const playlists = getMyPlaylists();
  updateMyPlaylistsBadge();
  updateParsingGuard();
  myPlaylistsCardsContainer.innerHTML = '';

  if (playlists.length === 0) {
    myPlaylistsCardsContainer.innerHTML = `
      <div class="py-12 text-center text-slate-400 border border-dashed border-emerald-200/80 bg-white/60 rounded-2xl p-6">
        <svg class="w-12 h-12 mx-auto stroke-emerald-400 mb-3" fill="none" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"/>
        </svg>
        <div class="text-sm font-semibold text-slate-700 mb-1">暂未收录任何歌单</div>
        <p class="text-xs text-slate-500">在上方粘贴网易云音乐、QQ音乐、酷狗等歌单链接，添加后任务将在后台自动并发解析</p>
      </div>
    `;
    return;
  }

  playlists.forEach((pl, plIdx) => {
    const card = document.createElement('div');
    const isParsing = pl.status === 'parsing';
    const isError = pl.status === 'error';

    let borderClass = 'border-slate-200/90 bg-white/90 shadow-xs hover:shadow-md hover:border-emerald-300 transition';
    if (isParsing) borderClass = 'border-emerald-300 bg-emerald-50/50 shadow-md shadow-emerald-600/5';
    else if (isError) borderClass = 'border-rose-200 bg-rose-50/40';

    card.className = `playlist-card border rounded-2xl p-4 space-y-3 ${borderClass}`;
    
    // 首曲封面或默认
    const firstCover = (pl.tracks && pl.tracks[0] && pl.tracks[0].cover_url) ? pl.tracks[0].cover_url : '';
    const coverSrc = firstCover || 'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 60 60%22><rect fill=%22%23e2e8f0%22 width=%2260%22 height=%2260%22/></svg>';

    // 头部状态描述与操作按钮
    let statusBadgeHtml = '';
    let actionButtonsHtml = '';

    if (isParsing) {
      statusBadgeHtml = `
        <div class="text-xs text-emerald-800 flex items-center gap-1.5 mt-0.5 font-medium">
          <svg class="animate-spin w-3.5 h-3.5 text-emerald-600" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
          </svg>
          <span class="font-bold text-emerald-700">正在后台解析中（请保持当前网页开启，勿关闭！）</span>
          <span class="text-slate-400">·</span>
          <span class="text-slate-500">${pl.source_label || pl.source}</span>
        </div>
      `;
      actionButtonsHtml = `
        <button class="pl-del-btn px-2.5 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-xl text-xs font-medium transition" title="取消并移除该任务">
          <span>取消任务</span>
        </button>
      `;
    } else if (isError) {
      statusBadgeHtml = `
        <div class="text-xs text-rose-600 flex items-center gap-1.5 mt-0.5">
          <span class="font-bold">!</span>
          <span class="truncate max-w-xs sm:max-w-md">解析失败: ${escapeHtml(pl.errorMsg || '链接无效或受限')}</span>
        </div>
      `;
      actionButtonsHtml = `
        <button class="pl-retry-btn px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold shadow-xs transition flex items-center gap-1">
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
          <span>重试</span>
        </button>
        <button class="pl-del-btn p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition" title="移除该歌单">
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
          </svg>
        </button>
      `;
    } else {
      // 就绪状态
      statusBadgeHtml = `
        <div class="text-xs text-slate-500 flex items-center gap-2 mt-0.5">
          <span class="text-emerald-700 font-bold font-mono">${pl.tracks ? pl.tracks.length : 0} 首曲目</span>
          <span>·</span>
          <span class="px-1.5 py-0.2 rounded bg-emerald-50 text-emerald-700 border border-emerald-200/80 text-[10px] font-medium">${pl.source_label || pl.source || '在线歌单'}</span>
          <span>·</span>
          <span class="text-slate-400 text-[11px]">${pl.createTime || ''}</span>
        </div>
      `;
      actionButtonsHtml = `
        <button class="pl-play-all-btn px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold shadow-xs transition flex items-center gap-1.5">
          <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
          <span>播放此歌单</span>
        </button>
        <button class="pl-toggle-tracks-btn px-2.5 py-1.5 bg-slate-50 hover:bg-slate-100 text-slate-700 rounded-xl text-xs font-medium border border-slate-200 transition flex items-center gap-1">
          <span>曲目清单</span>
          <span class="pl-arrow text-[10px]">▼</span>
        </button>
        <button class="pl-del-btn p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition" title="删除此歌单">
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
          </svg>
        </button>
      `;
    }

    card.innerHTML = `
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div class="flex items-center gap-3 min-w-0">
          ${isParsing ? `
            <div class="w-12 h-12 rounded-xl bg-emerald-50 border border-emerald-200 flex items-center justify-center shrink-0 text-emerald-600">
              <svg class="animate-spin w-5 h-5" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
              </svg>
            </div>
          ` : `
            <img src="${coverSrc}" class="w-12 h-12 rounded-xl object-cover border border-emerald-100 shrink-0 bg-slate-100" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 60 60%22><rect fill=%22%23e2e8f0%22 width=%2260%22 height=%2260%22/></svg>'">
          `}
          <div class="min-w-0 flex-1">
            <!-- 歌单标题展示态 -->
            <div class="pl-name-view-box flex items-center gap-1.5 min-w-0">
              <span class="pl-name-text text-sm font-bold text-slate-800 truncate" title="${escapeHtml(pl.name)}">${escapeHtml(pl.name)}</span>
              ${(!isParsing && !isError) ? `
                <button type="button" class="pl-rename-btn p-1 text-slate-400 hover:text-emerald-700 hover:bg-emerald-50 rounded-lg transition shrink-0" title="重命名此歌单">
                  <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                  </svg>
                </button>
              ` : ''}
              ${isParsing ? '<span class="text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300 font-medium shrink-0">解析中</span>' : ''}
              ${isError ? '<span class="text-[10px] px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 border border-rose-300 font-medium shrink-0">失败</span>' : ''}
            </div>

            <!-- 内联重命名编辑态 (默认隐藏) -->
            <div class="pl-name-edit-box hidden items-center gap-1.5 min-w-0 my-0.5">
              <input type="text" class="pl-name-input px-2.5 py-1 text-xs border border-emerald-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500/30 text-slate-800 font-semibold w-40 sm:w-56" value="${escapeHtml(pl.name)}" maxlength="40" placeholder="请输入歌单名称">
              <button type="button" class="pl-rename-save-btn px-2 py-1 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold rounded-lg shadow-xs transition">保存</button>
              <button type="button" class="pl-rename-cancel-btn px-2 py-1 bg-slate-100 hover:bg-slate-200 text-slate-600 text-xs font-medium rounded-lg transition">取消</button>
            </div>

            ${statusBadgeHtml}
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-1.5 sm:gap-2 shrink-0">
          ${actionButtonsHtml}
        </div>
      </div>

      <!-- 展开的曲目清单面板 (仅就绪时支持展开) -->
      ${(!isParsing && !isError) ? `
        <div class="pl-tracks-panel hidden border-t border-slate-100 pt-3 mt-2">
          <div class="max-h-60 overflow-y-auto space-y-1 pr-1 fs-lyric-scroll">
            ${(pl.tracks || []).map((t, tIdx) => `
              <div class="playlist-track-item flex items-center justify-between p-2 rounded-xl text-xs hover:bg-emerald-50/70 transition cursor-pointer" data-track-idx="${tIdx}">
                <div class="flex items-center gap-2.5 min-w-0">
                  <span class="text-slate-400 font-mono w-5 text-right shrink-0">${tIdx + 1}</span>
                  <span class="font-medium text-slate-800 truncate">${escapeHtml(t.song_name)}</span>
                  <span class="text-slate-500 truncate"> - ${escapeHtml(t.singers)}</span>
                  ${t.has_lyric ? '<span class="text-[9px] px-1.5 py-0.2 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 shrink-0 font-medium">词</span>' : ''}
                </div>
                <div class="flex items-center gap-3 shrink-0 text-slate-400">
                  <span class="font-mono text-[11px]">${t.duration || ''}</span>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      ` : ''}
    `;

    // 绑定卡片交互
    const playAllBtn = card.querySelector('.pl-play-all-btn');
    const toggleTracksBtn = card.querySelector('.pl-toggle-tracks-btn');
    const tracksPanel = card.querySelector('.pl-tracks-panel');
    const arrowSpan = card.querySelector('.pl-arrow');
    const delBtn = card.querySelector('.pl-del-btn');
    const retryBtn = card.querySelector('.pl-retry-btn');
    // 内联重命名事件绑定
    const renameBtn = card.querySelector('.pl-rename-btn');
    const nameViewBox = card.querySelector('.pl-name-view-box');
    const nameEditBox = card.querySelector('.pl-name-edit-box');
    const nameInput = card.querySelector('.pl-name-input');
    const nameSaveBtn = card.querySelector('.pl-rename-save-btn');
    const nameCancelBtn = card.querySelector('.pl-rename-cancel-btn');
    const nameTextSpan = card.querySelector('.pl-name-text');

    if (renameBtn && nameViewBox && nameEditBox && nameInput) {
      const openEdit = () => {
        nameViewBox.classList.add('hidden');
        nameEditBox.classList.remove('hidden');
        nameEditBox.classList.add('flex');
        nameInput.value = pl.name;
        nameInput.focus();
        nameInput.select();
      };

      const closeEdit = () => {
        nameEditBox.classList.add('hidden');
        nameEditBox.classList.remove('flex');
        nameViewBox.classList.remove('hidden');
      };

      const saveRename = () => {
        const newName = nameInput.value.trim();
        if (!newName) {
          showToast('歌单名称不能为空');
          nameInput.focus();
          return;
        }
        if (newName !== pl.name) {
          pl.name = newName;
          pl.hasCustomName = true;
          const curList = getMyPlaylists();
          const target = curList.find(p => p.id === pl.id);
          if (target) {
            target.name = newName;
            target.hasCustomName = true;
          }
          saveMyPlaylists(curList);
          nameTextSpan.innerText = newName;
          nameTextSpan.title = newName;
          showToast(`已重命名为《${newName}》`);
        }
        closeEdit();
      };

      renameBtn.onclick = (e) => {
        e.stopPropagation();
        openEdit();
      };

      if (nameSaveBtn) {
        nameSaveBtn.onclick = (e) => {
          e.stopPropagation();
          saveRename();
        };
      }

      if (nameCancelBtn) {
        nameCancelBtn.onclick = (e) => {
          e.stopPropagation();
          closeEdit();
        };
      }

      nameInput.onkeydown = (e) => {
        e.stopPropagation();
        if (e.key === 'Enter') {
          saveRename();
        } else if (e.key === 'Escape') {
          closeEdit();
        }
      };

      nameInput.onclick = (e) => e.stopPropagation();
    }

    if (playAllBtn) {
      playAllBtn.onclick = () => {
        loadAndPlayPlaylist(pl.tracks, 0);
      };
    }

    if (toggleTracksBtn && tracksPanel) {
      toggleTracksBtn.onclick = () => {
        const isHidden = tracksPanel.classList.contains('hidden');
        if (isHidden) {
          tracksPanel.classList.remove('hidden');
          arrowSpan.innerText = '▲';
        } else {
          tracksPanel.classList.add('hidden');
          arrowSpan.innerText = '▼';
        }
      };
    }

    if (retryBtn) {
      retryBtn.onclick = () => {
        pl.status = 'parsing';
        pl.errorMsg = '';
        saveMyPlaylists(getMyPlaylists());
        renderMyPlaylistsCards();
        runPlaylistTask(pl);
      };
    }

    if (delBtn) {
      delBtn.onclick = () => {
        const promptMsg = isParsing ? `确定要取消并移除正在解析的任务吗？` : `确定要从我的歌单中移除《${pl.name}》吗？`;
        if (confirm(promptMsg)) {
          const curList = getMyPlaylists();
          const idx = curList.findIndex(p => p.id === pl.id);
          if (idx !== -1) {
            curList.splice(idx, 1);
            saveMyPlaylists(curList);
            renderMyPlaylistsCards();
            showToast(`已移除任务/歌单《${pl.name}》`);
          }
        }
      };
    }

    // 单曲点击播放（全端单点即播，0毫秒瞬间进入播放器）
    card.querySelectorAll('.playlist-track-item').forEach(itemEl => {
      const tIdx = parseInt(itemEl.dataset.trackIdx, 10);
      itemEl.onclick = () => {
        loadAndPlayPlaylist(pl.tracks, tIdx);
      };
    });

    myPlaylistsCardsContainer.appendChild(card);
  });
}

// 后台异步任务执行器 (并发不阻塞)
function runPlaylistTask(taskItem) {
  safeFetchJson('/api/playlist/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: taskItem.url })
  })
  .then(data => {
    const curList = getMyPlaylists();
    const target = curList.find(p => p.id === taskItem.id);
    if (!target) return;

    if (data.error || !data.tracks || data.tracks.length === 0) {
      target.status = 'error';
      target.errorMsg = data.error || '未获取到可解析的有效歌曲';
      showToast(`! 歌单《${target.name}》解析失败: ${target.errorMsg}`);
    } else {
      target.status = 'ready';
      target.tracks = data.tracks;
      target.source = data.source || target.source;
      target.source_label = data.source_label || detectSourceMeta(target.url) || target.source;
      const originalTitle = data.title || data.playlist_name;
      if (!taskItem.hasCustomName && originalTitle) {
        target.name = originalTitle;
      }
      showToast(`✓ 歌单《${target.name}》已在后台解析完成（共 ${data.tracks.length} 首）`);
    }
    saveMyPlaylists(curList);
    renderMyPlaylistsCards();
  })
  .catch(err => {
    const curList = getMyPlaylists();
    const target = curList.find(p => p.id === taskItem.id);
    if (target) {
      target.status = 'error';
      target.errorMsg = err.message || '网络连接超时';
      saveMyPlaylists(curList);
      renderMyPlaylistsCards();
      showToast(`! 歌单《${target.name}》解析异常: ${target.errorMsg}`);
    }
  });
}

// 快速连续添加歌单：秒级清空输入框，后台任务并发执行
function submitPlaylistTask() {
  const url = modalPlaylistUrlInput.value.trim();
  const customName = modalPlaylistCustomName.value.trim();
  if (!url) {
    showToast('请输入歌单完整链接');
    return;
  }

  const sourceLabel = detectSourceMeta(url);
  const taskId = 'pl_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6);
  const taskItem = {
    id: taskId,
    name: customName || `${sourceLabel}歌单`,
    hasCustomName: Boolean(customName),
    source: sourceLabel,
    source_label: sourceLabel,
    url: url,
    createTime: new Date().toLocaleDateString(),
    status: 'parsing',
    tracks: [],
    errorMsg: ''
  };

  // 1. 立即清空输入框并保持光标聚焦，用户可以立即粘贴添加第2个、第3个！
  modalPlaylistUrlInput.value = '';
  modalPlaylistCustomName.value = '';
  modalPlaylistUrlInput.focus();

  // 2. 立即将任务插入列表顶端并渲染，状态为“解析中”
  const curList = getMyPlaylists();
  curList.unshift(taskItem);
  saveMyPlaylists(curList);
  renderMyPlaylistsCards();
  showToast(`⚠️ 已加入后台解析队列！请保持当前网页开启，全部解析完毕前切勿关闭！`);

  // 3. 异步非阻塞执行后台解析
  runPlaylistTask(taskItem);
}

modalImportPlaylistBtn.onclick = submitPlaylistTask;
modalPlaylistUrlInput.onkeydown = (e) => {
  if (e.key === 'Enter') submitPlaylistTask();
};
modalPlaylistCustomName.onkeydown = (e) => {
  if (e.key === 'Enter') submitPlaylistTask();
};

// 页面加载时自动恢复或续跑可能存在的未完成解析任务，并激活防关闭守卫
getMyPlaylists().forEach(pl => {
  if (pl.status === 'parsing') {
    runPlaylistTask(pl);
  }
});
updateParsingGuard();


// 一键导出全部配置为 .json 备份文件
exportConfigBtn.onclick = () => {
  const playlists = getMyPlaylists();
  const backupData = {
    app: 'SoundFlow (musicdl)',
    version: '2.14',
    export_time: new Date().toISOString(),
    export_date_str: new Date().toLocaleString(),
    playlists_count: playlists.length,
    playlists: playlists,
    preferences: {
      format: getSavedFormat(),
      include_lrc: getSavedIncludeLrc(),
      embed_lyric: getSavedEmbedLyric()
    }
  };

  const jsonStr = JSON.stringify(backupData, null, 2);
  const blob = new Blob([jsonStr], { type: 'application/json;charset=utf-8' });
  const blobUrl = URL.createObjectURL(blob);
  
  const now = new Date();
  const timestamp = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}_${String(now.getHours()).padStart(2,'0')}${String(now.getMinutes()).padStart(2,'0')}`;
  const filename = `SoundFlow_Playlists_Backup_${timestamp}.json`;

  const a = document.createElement('a');
  a.href = blobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    a.remove();
    URL.revokeObjectURL(blobUrl);
  }, 1000);

  showToast(`已成功导出 ${playlists.length} 个歌单及配置为 [${filename}]，请妥善保管`);
};

// 导入配置恢复
importConfigTriggerBtn.onclick = () => {
  importConfigFileInput.click();
};

importConfigFileInput.onchange = (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (event) => {
    try {
      const data = JSON.parse(event.target.result);
      if (!data || !Array.isArray(data.playlists)) {
        showToast('导入失败：该文件不是有效的 SoundFlow 歌单备份文件');
        return;
      }

      const existing = getMyPlaylists();
      const existingIds = new Set(existing.map(p => p.id || p.name));
      let addedCount = 0;

      data.playlists.forEach(pl => {
        if (!existingIds.has(pl.id || pl.name)) {
          existing.push(pl);
          addedCount++;
        }
      });

      saveMyPlaylists(existing);

      if (data.preferences) {
        if (data.preferences.format) localStorage.setItem(STORAGE_KEY_FORMAT, data.preferences.format);
        if (data.preferences.include_lrc !== undefined) localStorage.setItem(STORAGE_KEY_INCLUDE_LRC, String(data.preferences.include_lrc));
        if (data.preferences.embed_lyric !== undefined) localStorage.setItem(STORAGE_KEY_EMBED_LYRIC, String(data.preferences.embed_lyric));
        updateFormatBadge();
      }

      renderMyPlaylistsCards();
      showToast(`导入成功！共收录 ${existing.length} 个歌单（新载入 ${addedCount} 个）`);
    } catch (err) {
      showToast('文件解析失败，请检查是否为标准 JSON 格式');
    } finally {
      importConfigFileInput.value = '';
    }
  };
  reader.readAsText(file, 'utf-8');
};

// ==========================================
// 8.1 二维码配置导出与跨端同步恢复 (服务端即时中继 + 端到端光学解析)
// ==========================================
const QR_CONFIG_PREFIX = 'SF1:';
let currentQrInstance = null;
let scanVideoStream = null;
let scanAnimationReq = null;

function getFullBackupPayload() {
  const playlists = getMyPlaylists();
  return {
    playlists: playlists,
    preferences: {
      format: getSavedFormat(),
      include_lrc: getSavedIncludeLrc(),
      embed_lyric: getSavedEmbedLyric()
    }
  };
}

async function showQrExportModal() {
  if (typeof QRCode === 'undefined') {
    showToast('二维码渲染引擎未就绪，请刷新重试');
    return;
  }
  const playlists = getMyPlaylists();
  const totalTracks = playlists.reduce((acc, p) => acc + (p.tracks ? p.tracks.length : 0), 0);

  if (qrExportNetBadge) qrExportNetBadge.classList.add('hidden');
  qrExportSummaryText.innerText = '正在智能研判网络环境并生成同步码...';
  qrExportCanvasWrapper.innerHTML = '<div class="flex items-center justify-center h-full text-xs text-slate-400">正在生成二维码...</div>';
  qrExportModal.classList.remove('hidden');

  try {
    const payload = getFullBackupPayload();
    // 服务端全自动研判局域网还是云端服务器，彻底防呆
    const res = await safeFetchJson('/api/sync/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res && res.success && res.token && res.sync_url) {
      qrExportCanvasWrapper.innerHTML = '';
      currentQrInstance = new QRCode(qrExportCanvasWrapper, {
        text: res.sync_url,
        width: 220,
        height: 220,
        colorDark: '#0f172a',
        colorLight: '#ffffff',
        correctLevel: QRCode.CorrectLevel.M
      });

      // 智能网络只读徽标呈现
      if (qrExportNetBadge && qrExportNetBadgeText) {
        qrExportNetBadge.classList.remove('hidden');
        if (res.env_type === 'server') {
          qrExportNetBadge.className = 'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-sky-50 text-sky-800 border border-sky-200 shadow-2xs';
        } else {
          qrExportNetBadge.className = 'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200 shadow-2xs';
        }
        qrExportNetBadgeText.innerText = res.badge_text || '已就绪';
      }

      if (qrExportSubText) {
        qrExportSubText.innerText = res.sub_text || '手机相机或微信扫码打开，秒级自动合并歌单';
      }

      qrExportSummaryText.innerText = `已生成同步码（收录 ${playlists.length} 个歌单，共 ${totalTracks} 首歌）`;
      qrExportModal.dataset.qrText = res.sync_url;
    } else {
      throw new Error(res.error || '创建同步码失败');
    }
  } catch (err) {
    console.warn('Sync relay failed, fallback to local packing:', err);
    if (qrExportNetBadge && qrExportNetBadgeText) {
      qrExportNetBadge.classList.remove('hidden');
      qrExportNetBadge.className = 'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-800 border border-amber-200 shadow-2xs';
      qrExportNetBadgeText.innerText = '📦 离线纯文本模式';
    }
    if (qrExportSubText) qrExportSubText.innerText = '离线模式：需使用本站内置的【扫码恢复】摄像头取景器识别';
    // 降级为离线纯文本压缩
    try {
      const qrDataText = packCompactQrData();
      qrExportCanvasWrapper.innerHTML = '';
      currentQrInstance = new QRCode(qrExportCanvasWrapper, {
        text: qrDataText,
        width: 220,
        height: 220,
        colorDark: '#0f172a',
        colorLight: '#ffffff',
        correctLevel: QRCode.CorrectLevel.L
      });
      qrExportSummaryText.innerText = `离线模式：已打包 ${playlists.length} 个歌单（${totalTracks} 首歌）`;
      qrExportModal.dataset.qrText = qrDataText;
    } catch (e2) {
      qrExportCanvasWrapper.innerHTML = '<div class="p-4 text-center text-xs text-rose-500">无法连接服务端同步通道，且离线数据超出上限。建议使用【文件导出】。</div>';
      qrExportSummaryText.innerText = '生成失败';
    }
  }
}

function packCompactQrData() {
  const playlists = getMyPlaylists();
  const compactLists = (playlists || []).map(pl => ({
    n: String(pl.name || '歌单').trim(),
    t: (pl.tracks || []).map(t => [
      String(t.song_name || '').trim(),
      String(t.singers || '').trim(),
      String(t.source || 'QQMusicClient').trim(),
      String(t.identifier || '').trim(),
      String(t.duration || '00:00').trim(),
      String(t.album || '').trim()
    ])
  }));
  const payload = {
    p: { f: getSavedFormat(), l: getSavedIncludeLrc(), e: getSavedEmbedLyric() },
    l: compactLists
  };
  return QR_CONFIG_PREFIX + btoa(encodeURIComponent(JSON.stringify(payload)));
}

function closeQrExportModal() {
  qrExportModal.classList.add('hidden');
  qrExportCanvasWrapper.innerHTML = '';
  currentQrInstance = null;
}

if (exportQrConfigBtn) exportQrConfigBtn.onclick = showQrExportModal;
if (closeQrExportModalBtn) closeQrExportModalBtn.onclick = closeQrExportModal;

if (downloadQrImgBtn) {
  downloadQrImgBtn.onclick = () => {
    const canvas = qrExportCanvasWrapper.querySelector('canvas');
    const img = qrExportCanvasWrapper.querySelector('img');
    let dataUrl = '';
    if (canvas) {
      dataUrl = canvas.toDataURL('image/png');
    } else if (img && img.src) {
      dataUrl = img.src;
    }
    if (!dataUrl) {
      showToast('暂无可保存的二维码图像');
      return;
    }
    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = `SoundFlow_Sync_QR_${Date.now()}.png`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 500);
    showToast('已保存同步二维码图片');
  };
}

if (copyQrCodeTextBtn) {
  copyQrCodeTextBtn.onclick = () => {
    const text = qrExportModal.dataset.qrText;
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        showToast('已复制同步链接至剪贴板');
      }).catch(() => fallbackCopy(text));
    } else {
      fallbackCopy(text);
    }
  };
}

function fallbackCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
    showToast('已复制同步链接至剪贴板');
  } catch (e) {
    showToast('复制失败，请手动选择复制');
  }
  document.body.removeChild(ta);
}

// 启动检测与 URL Hash 自动恢复 (iPhone/微信系统相机扫码即开)
async function checkUrlSyncOnStartup() {
  const hash = window.location.hash || '';
  if (!hash.startsWith('#sync=')) return;
  const token = hash.replace('#sync=', '').trim();
  if (!token) return;

  showToast('正在从服务端拉取歌单与配置...', 4000);
  try {
    const res = await safeFetchJson(`/api/sync/get/${token}`);
    if (res && res.success && res.data) {
      applyRestoredConfig(res.data);
      history.replaceState(null, document.title, window.location.pathname + window.location.search);
    } else {
      showToast(res.error || '该同步码已失效或已过期');
    }
  } catch (e) {
    showToast('从服务端拉取同步数据失败: ' + e.message);
  }
}

// 扫码恢复
async function startQrScanner() {
  qrScanModal.classList.remove('hidden');
  qrScanPromptMask.classList.add('hidden');
  qrScanStatusMsg.innerText = '将摄像头对准另一台屏幕上的配置二维码';

  // 检测是否具备原生摄像头调用环境 (iOS Safari 在非 HTTPS 局域网下不存在或抛出安全拒绝)
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    qrScanPromptMask.classList.remove('hidden');
    qrScanPromptText.innerText = 'iPhone 在非 HTTPS 局域网下受苹果安全策略限制实时取景，推荐直接用 iPhone 系统相机扫码打开，或点击下方拍照识别';
    qrScanStatusMsg.innerText = '摄像头受限，推荐使用手机自带相机扫码或下方拍照识别';
    return;
  }

  try {
    const constraints = {
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }
    };
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    scanVideoStream = stream;
    qrScanVideo.srcObject = stream;
    qrScanVideo.setAttribute('playsinline', true);
    await qrScanVideo.play();
    requestAnimationFrame(scanVideoFrame);
  } catch (err) {
    console.warn('Camera open failed (likely iOS HTTP policy):', err);
    qrScanPromptMask.classList.remove('hidden');
    qrScanPromptText.innerText = 'iPhone 在非 HTTPS 局域网下受苹果安全策略限制实时取景，推荐直接用 iPhone 系统相机扫码打开，或点击下方拍照识别';
    qrScanStatusMsg.innerText = '摄像头不可用，请使用手机自带相机扫码或点击下方拍照识别';
  }
}

function stopQrScanner() {
  if (scanAnimationReq) {
    cancelAnimationFrame(scanAnimationReq);
    scanAnimationReq = null;
  }
  if (scanVideoStream) {
    scanVideoStream.getTracks().forEach(t => t.stop());
    scanVideoStream = null;
  }
  if (qrScanVideo) {
    qrScanVideo.srcObject = null;
  }
  qrScanModal.classList.add('hidden');
}

function scanVideoFrame() {
  if (!qrScanVideo || qrScanVideo.readyState !== qrScanVideo.HAVE_ENOUGH_DATA) {
    scanAnimationReq = requestAnimationFrame(scanVideoFrame);
    return;
  }

  const canvas = qrScanCanvas;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = qrScanVideo.videoWidth;
  canvas.height = qrScanVideo.videoHeight;
  ctx.drawImage(qrScanVideo, 0, 0, canvas.width, canvas.height);

  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  if (typeof jsQR !== 'undefined') {
    const code = jsQR(imageData.data, imageData.width, imageData.height, {
      inversionAttempts: 'dontInvert'
    });
    if (code && code.data) {
      handleScannedResult(code.data);
      stopQrScanner();
      return;
    }
  }

  scanAnimationReq = requestAnimationFrame(scanVideoFrame);
}

function decodeQrFromImage(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0);
      const imgData = ctx.getImageData(0, 0, img.width, img.height);
      if (typeof jsQR !== 'undefined') {
        const code = jsQR(imgData.data, imgData.width, imgData.height);
        if (code && code.data) {
          handleScannedResult(code.data);
          stopQrScanner();
          return;
        }
      }
      showToast('未能从所选图片中识别出有效的二维码');
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
}

async function handleScannedResult(rawText) {
  if (!rawText || typeof rawText !== 'string') return;
  const trimmed = rawText.trim();

  // 1. 若扫到的是包含 #sync= 的同步 URL
  if (trimmed.includes('#sync=')) {
    const token = trimmed.split('#sync=')[1].split('&')[0].trim();
    if (token) {
      showToast('正在从服务端拉取完整配置与歌单...', 3000);
      try {
        const res = await safeFetchJson(`/api/sync/get/${token}`);
        if (res && res.success && res.data) {
          applyRestoredConfig(res.data);
          return;
        } else {
          showToast(res.error || '该同步码已失效或已过期');
        }
      } catch (err) {
        showToast('拉取配置失败: ' + err.message);
      }
      return;
    }
  }

  // 2. 若扫到的是离线紧凑码 SF1:
  if (trimmed.startsWith(QR_CONFIG_PREFIX)) {
    try {
      const rawBase64 = trimmed.slice(QR_CONFIG_PREFIX.length);
      const jsonStr = decodeURIComponent(atob(rawBase64));
      const payload = JSON.parse(jsonStr);
      if (payload && Array.isArray(payload.l)) {
        const restoredPlaylists = payload.l.map((item, idx) => ({
          id: `pl_qr_${Date.now()}_${idx}`,
          name: item.n || `同步歌单 ${idx + 1}`,
          status: 'done',
          tracks: (item.t || []).map(arr => ({
            song_name: arr[0] || '未知曲目',
            singers: arr[1] || '未知歌手',
            source: arr[2] || 'QQMusicClient',
            identifier: arr[3] || '',
            duration: arr[4] || '00:00',
            album: arr[5] || '',
            source_short: (arr[2] || '').replace('MusicClient', '').toUpperCase(),
            source_label: arr[2] || '主流音源',
            ext: 'mp3',
            quality_type: 'standard',
            quality_label: 'MP3'
          }))
        }));
        applyRestoredConfig({ playlists: restoredPlaylists, preferences: payload.p || {} });
        return;
      }
    } catch (e) {
      console.error('Compact unpack error:', e);
    }
  }

  // 3. 若为标准 JSON 格式
  try {
    const raw = JSON.parse(trimmed);
    if (raw && Array.isArray(raw.playlists)) {
      applyRestoredConfig(raw);
      return;
    }
  } catch (e) {}

  showToast('该二维码不是有效的 SoundFlow 歌单配置');
}

function applyRestoredConfig(data) {
  if (!data || !Array.isArray(data.playlists)) {
    showToast('该数据不是有效的 SoundFlow 歌单配置');
    return false;
  }

  const existing = getMyPlaylists();
  const existingNames = new Set(existing.map(p => p.name));
  let addedCount = 0;

  data.playlists.forEach(pl => {
    if (!existingNames.has(pl.name)) {
      existing.push(pl);
      addedCount++;
    } else {
      const target = existing.find(p => p.name === pl.name);
      if (target && Array.isArray(target.tracks) && Array.isArray(pl.tracks)) {
        const tSet = new Set(target.tracks.map(t => t.song_name + '|' + t.singers));
        pl.tracks.forEach(nt => {
          if (!tSet.has(nt.song_name + '|' + nt.singers)) {
            target.tracks.push(nt);
          }
        });
      }
    }
  });

  saveMyPlaylists(existing);

  if (data.preferences) {
    if (data.preferences.format) localStorage.setItem(STORAGE_KEY_FORMAT, data.preferences.format);
    if (data.preferences.f) localStorage.setItem(STORAGE_KEY_FORMAT, data.preferences.f);
    if (data.preferences.include_lrc !== undefined) localStorage.setItem(STORAGE_KEY_INCLUDE_LRC, String(data.preferences.include_lrc));
    if (data.preferences.l !== undefined) localStorage.setItem(STORAGE_KEY_INCLUDE_LRC, String(data.preferences.l));
    if (data.preferences.embed_lyric !== undefined) localStorage.setItem(STORAGE_KEY_EMBED_LYRIC, String(data.preferences.embed_lyric));
    if (data.preferences.e !== undefined) localStorage.setItem(STORAGE_KEY_EMBED_LYRIC, String(data.preferences.e));
    updateFormatBadge();
  }

  renderMyPlaylistsCards();
  showToast(`同步恢复成功！已合并收录 ${existing.length} 个歌单（新载入 ${addedCount} 个）`);
  return true;
}

if (scanQrConfigBtn) scanQrConfigBtn.onclick = startQrScanner;
if (closeQrScanModalBtn) closeQrScanModalBtn.onclick = stopQrScanner;

if (pickQrImageBtn && qrImageFileInput) {
  pickQrImageBtn.onclick = () => qrImageFileInput.click();
  qrImageFileInput.onchange = (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) decodeQrFromImage(file);
    qrImageFileInput.value = '';
  };
}

if (triggerImagePickerBtn && qrImageFileInput) {
  triggerImagePickerBtn.onclick = () => qrImageFileInput.click();
}

// Utilities
function formatTime(seconds) {
  if (isNaN(seconds)) return '00:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/[&<>'"]/g, 
    tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
  );
}

// Run
init();
