const $ = (selector) => document.querySelector(selector);
const SLIDER_SETTING_KEYS = new Set(['Brightness', 'Color', 'Contrast', 'Sharpness', 'Blur']);
let bindAdjustControls = () => {};
let syncAdjustControls = () => {};
let bindEnhanceControls = () => {};
let syncEnhanceControls = () => {};
let bindCanvasControls = () => {};
let bindVideoControls = () => {};
const unavailableFeatures = new Set();

async function loadFeatureModules() {
  const modules = [
    ['adjust', './modules/adjust.js'],
    ['enhance', './modules/enhance.js'],
    ['canvas', './modules/canvas.js'],
    ['video', './modules/video.js'],
  ];
  const status = {};
  await Promise.all(modules.map(async ([name, path]) => {
    try {
      const loaded = await import(path);
      if (name === 'adjust') {
        ({ bindAdjustControls, syncAdjustControls } = loaded);
      } else if (name === 'enhance') {
        ({ bindEnhanceControls, syncEnhanceControls } = loaded);
      } else if (name === 'canvas') {
        ({ bindCanvasControls } = loaded);
      } else {
        ({ bindVideoControls } = loaded);
      }
      status[name] = true;
    } catch (error) {
      status[name] = false;
      console.error(`Could not load ${name} UI module.`, error);
    }
  }));
  return status;
}

function disableUnavailableFeature(name) {
  unavailableFeatures.add(name);
  const selectors = {
    adjust: '#effects-controls input, #inversion, #denoise-button',
    enhance: '#enhance-controls input, #enhance-controls select, #upscale-button, #factor-options button',
    canvas: '#crop-button, #reset-scale-button, #fit-button, #scale-slider',
    video: '#video-toolbar button, #video-toolbar input, #video-toolbar select, #video-tools-bottom button, #video-tools-bottom input, #video-tools-bottom select, #video-controls button, #video-controls select',
  };
  document.querySelectorAll(selectors[name]).forEach((control) => {
    control.disabled = true;
  });
}
let state = null;
let pan = { x: 0, y: 0 };
let videoNativeSize = false;
const panById = new Map();
const videoPlayer = document.querySelector('#video-player');
let toastTimer = null;
let settingTimer = null;
let scaleTimer = null;
let pendingScale = null;
const pendingSettings = new Map();
let settingsFlushInProgress = false;
let stateRefreshQueued = false;
let stateRefreshPromise = null;
let imageLoading = false;
let imageLoadToken = 0;
let resultPreviewId = null;
let jobPollTimer = null;
let jobPollInFlight = false;

function callApi(method, ...args) {
  const api = window.pywebview?.api;
  if (!api) return Promise.reject(new Error('The Python bridge is not ready yet.'));
  return api[method](...args);
}

function logUserAction(event, details = {}) {
  const api = window.pywebview?.api;
  if (!api?.log_event) return;
  api.log_event(event, details).catch(() => {});
}

async function runAction(method, ...args) {
  logUserAction('api_action_requested', {
    method,
    argument_count: args.length,
  });
  try {
    const result = await callApi(method, ...args);
    logUserAction('api_action_completed', {
      method,
      result: result === false ? 'rejected' : 'accepted',
    });
    await refreshState();
    return result;
  } catch (error) {
    logUserAction('api_action_failed', { method, error: error.message });
    setToast(error.message, 'error');
    return false;
  }
}

function setToast(message, type = '') {
  const toast = $('#toast');
  toast.textContent = message;
  toast.className = `toast visible ${type}`;
  const logToast = window.pywebview?.api?.log_toast;
  if (logToast) logToast(type, message).catch(() => {});
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.className = 'toast'; }, 8000);
}

async function pauseCurrentVideoForHistoryChange() {
  if (!state?.video) return true;
  videoPlayer.pause();
  if (state.video.realtime_running) {
    return callApi('set_video_realtime_paused', true);
  }
  return callApi('set_video_position', videoPlayer.currentTime);
}

function setBusy(busy) {
  const imageUnavailable = !state?.has_image;
  const blocked = busy || imageLoading || resultPreviewId || state?.image_loading;
  document.querySelectorAll('.controls input, .controls select, .controls button, .video-toolbar input, .video-toolbar button, .video-tools-bottom input, .video-tools-bottom button, .history-item, #remove-button, #open-button, #empty-open-button, #export-button, #crop-button, #reset-scale-button, #fit-button, #reset-module')
    .forEach((control) => {
      const importAction = control.id === 'open-button' || control.id === 'empty-open-button';
      control.disabled = blocked || (imageUnavailable && !importAction);
    });
  if (state?.has_image) {
    $('#open-button').disabled = blocked;
    $('#empty-open-button').disabled = blocked;
    $('#export-button').disabled = blocked;
  }
  unavailableFeatures.forEach(disableUnavailableFeature);
}

document.addEventListener('click', (event) => {
  const control = event.target.closest('button, .history-item');
  if (control?.id || control?.classList.contains('history-item')) {
    logUserAction('ui_click', {
      control: control.id || 'history-item',
      history_id: control.dataset.historyId || undefined,
    });
  }
});

document.addEventListener('change', (event) => {
  const control = event.target;
  if (control.id) {
    logUserAction('ui_change', {
      control: control.id,
      value: control.type === 'checkbox' ? control.checked : control.value,
    });
  }
});

function syncVideoTimeline() {
  const realtime = Boolean(state?.video?.realtime_running);
  const duration = Number.isFinite(videoPlayer.duration)
    ? (realtime ? state.video.duration : videoPlayer.duration)
    : state?.video?.duration || 0;
  const current = realtime
    ? Math.max(0, Math.min(duration, state.video.realtime_position || 0))
    : Number.isFinite(videoPlayer.currentTime) ? videoPlayer.currentTime : 0;
  const formatTime = (seconds) => {
    const value = Math.max(0, Math.floor(seconds));
    return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
  };
  $('#video-time').textContent = `${formatTime(current)} / ${formatTime(duration)}`;
  if (document.activeElement !== $('#video-seek')) {
    $('#video-seek').value = duration ? Math.round((current / duration) * 1000) : 0;
  }
  const isPaused = realtime ? state.video.realtime_paused : videoPlayer.paused;
  $('#video-play').textContent = isPaused ? '▶' : 'Ⅱ';
  $('#video-play').setAttribute('aria-label', isPaused ? 'Play video' : 'Pause video');
  const volume = $('#video-volume');
  if (document.activeElement !== volume) {
    volume.value = videoPlayer.muted ? 0 : videoPlayer.volume;
  }
  $('#video-mute').textContent = videoPlayer.muted ? '🔇' : '🔊';
  $('#video-mute').title = videoPlayer.muted ? 'Unmute' : 'Mute';
  $('#video-mute').setAttribute('aria-label', $('#video-mute').title);
}

function showVideoUpscaleStarting() {
  $('#job-overlay').hidden = false;
  $('#job-status').textContent = 'Starting video upscale';
  $('#job-percent').textContent = '0%';
  $('#progress-fill').style.width = '0%';
  $('.progress-track').classList.remove('indeterminate');
  $('#cancel-job').hidden = false;
  $('#cancel-job').disabled = false;
  $('#cancel-job').textContent = 'Cancel';
  $('#job-detail').textContent = 'Preparing video frames';
}

function syncJobOverlay(job) {
  const exporting = job.kind === 'export';
  $('#job-overlay').hidden = !(job.running || job.status === 'Cancelling');
  $('#job-status').textContent = exporting
    ? `Exporting ${state?.kind === 'video' ? 'video' : 'image'}`
    : job.status || 'Processing image';
  $('#job-percent').textContent = exporting ? 'Saving' : `${job.progress || 0}%`;
  $('#progress-fill').style.width = `${job.progress || 0}%`;
  $('.progress-track').classList.toggle('indeterminate', exporting);
  $('#cancel-job').hidden = exporting || !job.running;
  $('#cancel-job').disabled = job.status === 'Cancelling';
  $('#cancel-job').textContent = job.status === 'Cancelling' ? 'Cancelling…' : 'Cancel';
  $('#job-detail').textContent = exporting
    ? `Writing ${state?.kind === 'video' ? 'video' : 'image'}`
    : job.kind === 'video_export'
      ? `${job.current || 0}/${job.total || 0} frames · ${Number(job.fps || 0).toFixed(2)} FPS · ${formatDuration(job.duration)}`
      : job.total
        ? `${String(job.stage || 'processing').replaceAll('-', ' ')} · ${job.current}/${job.total} ${job.unit || 'items'}${job.total === 1 ? '' : 's'}`
        : 'Preparing image';
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return '00:00';
  const value = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
}

function formatDebugSize(size) {
  return size ? `${size[0]} × ${size[1]} px` : '—';
}

function formatDebugDuration(seconds) {
  if (!Number.isFinite(seconds)) return '—';
  const value = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(value / 3600)).padStart(2, '0')}:${String(Math.floor((value % 3600) / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
}

function formatDebugBytes(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 'B';
  for (const nextUnit of units) {
    value /= 1024;
    unit = nextUnit;
    if (value < 1024 || nextUnit === units[units.length - 1]) break;
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${unit}`;
}

function syncDebugPanel(next) {
  const panel = $('#debug-panel');
  panel.hidden = !$('#debug-toggle').checked;
  if (!panel.hidden) {
    const info = next.media_info;
    $('#debug-status').textContent = info ? info.type.toUpperCase() : 'No media';
    const rows = info ? [
      ['Name', info.name],
      ['Type', info.type],
      ['Native resolution', formatDebugSize(info.native_size)],
      ['Current resolution', formatDebugSize(info.current_size)],
      ['Duration', formatDebugDuration(info.duration)],
      ['FPS', Number.isFinite(info.fps) ? info.fps.toFixed(3) : '—'],
      ['Frames', Number.isFinite(info.frame_count) ? info.frame_count.toLocaleString() : '—'],
      ['File size', formatDebugBytes(info.file_size)],
      ['Format', info.extension ? info.extension.toUpperCase() : '—'],
      ['Path', info.path || '—'],
    ] : [];
    const debug = next.debug;
    if (debug) {
      rows.push(
        ['Processing FPS', Number.isFinite(debug.fps) ? debug.fps.toFixed(2) : '—'],
        ['Processing device', debug.device || '—'],
        ['Process RAM', formatDebugBytes(debug.ram_bytes)],
        ['GPU memory', formatDebugBytes(debug.gpu_memory_bytes)],
        ['Cached frames', Number.isFinite(debug.cache_frames) ? debug.cache_frames.toLocaleString() : '—'],
        ['Cache hits / misses', Number.isFinite(debug.cache_hits) && Number.isFinite(debug.cache_misses)
          ? `${debug.cache_hits} / ${debug.cache_misses}` : '—'],
      );
    }
    const grid = $('#debug-grid');
    grid.replaceChildren();
    rows.forEach(([label, value]) => {
      const key = document.createElement('dt');
      key.textContent = label;
      const data = document.createElement('dd');
      data.textContent = value;
      grid.append(key, data);
    });
  }
}

function applyPreview(next) {
  const stage = $('#stage');
  const image = $('#preview-image');
  const realtimeVideo = $('#realtime-video');
  const video = $('#video-player');
  if (!next?.has_image) {
    video.pause();
    video.hidden = true;
    image.hidden = true;
    realtimeVideo.hidden = true;
    $('#realtime-loading').hidden = true;
    $('#empty-state').hidden = false;
    $('#stage-info').hidden = true;
    return;
  }
  $('#empty-state').hidden = true;
  const [width, height] = next.image_size;
  const inset = 64;
  const fit = Math.min((stage.clientWidth - inset) / width, (stage.clientHeight - inset) / height, 1);
  const zoom = next.scale || 1;
  if (next.kind === 'video' && next.video?.url) {
    const realtime = Boolean(next.video.realtime_url && next.video.realtime_running);
    $('#realtime-loading').hidden = !next.video.realtime_loading;
    image.hidden = true;
    realtimeVideo.hidden = !realtime;
    video.hidden = realtime;
    const changedEntry = video.dataset.entryId !== next.current_id;
    if (changedEntry) {
      videoNativeSize = false;
      video.dataset.entryId = next.current_id;
    }
    if (video.dataset.source !== next.video.url) {
      video.pause();
      video.crossOrigin = 'anonymous';
      video.dataset.source = next.video.url;
      video.src = next.video.url;
      video.load();
    } else if (changedEntry && video.readyState >= 1) {
      video.pause();
      video.currentTime = next.video.position || 0;
    }
    const outputOption = next.video.output_options?.find(
      (option) => option.factor === next.settings.enhancement.factor,
    );
    const videoWidth = realtime ? outputOption?.width || width : video.videoWidth || width;
    const videoHeight = realtime ? outputOption?.height || height : video.videoHeight || height;
    const displayFit = realtime
      ? Math.min(
        (stage.clientWidth - inset) / videoWidth,
        (stage.clientHeight - inset) / videoHeight,
        1,
      )
      : fit;
    const videoScale = videoNativeSize ? 1 : displayFit * zoom;
    const target = realtime ? realtimeVideo : video;
    if (realtime && realtimeVideo.dataset.source !== next.video.realtime_url) {
      realtimeVideo.dataset.source = next.video.realtime_url;
      realtimeVideo.src = next.video.realtime_url;
    }
    target.style.width = `${Math.max(1, videoWidth * videoScale)}px`;
    target.style.height = `${Math.max(1, videoHeight * videoScale)}px`;
    target.style.left = `calc(50% + ${pan.x}px)`;
    target.style.top = `calc(50% + ${pan.y}px)`;
    target.style.transform = 'translate(-50%, -50%)';
  } else {
    video.pause();
    video.hidden = true;
    image.hidden = false;
    $('#realtime-loading').hidden = true;
    if (next.image) image.src = next.image;
    image.style.width = `${Math.max(1, width * fit * zoom)}px`;
    image.style.height = `${Math.max(1, height * fit * zoom)}px`;
    image.style.left = `calc(50% + ${pan.x}px)`;
    image.style.top = `calc(50% + ${pan.y}px)`;
    image.style.transform = 'translate(-50%, -50%)';
  }
  $('#stage-info').textContent = `${width} × ${height}`;
  $('#stage-info').hidden = false;
}

function renderHistory(next) {
  const list = $('#history-list');
  $('#history-count').textContent = next.history.length;
  list.replaceChildren();
  next.history.forEach((item) => {
    const button = document.createElement('button');
      button.className = `history-item${item.id === next.current_id ? ' active' : ''}`;
    button.dataset.historyId = item.id;
    button.dataset.kind = item.kind;
    button.type = 'button';
    button.disabled = imageLoading || resultPreviewId || next.image_loading || next.job.running;
    button.title = `${item.name}, ${item.size[0]} × ${item.size[1]}`;
    const thumb = document.createElement('span');
    thumb.className = 'history-thumb';
      const image = document.createElement('img');
      image.src = item.thumbnail;
      image.alt = '';
      thumb.append(image);
    const name = document.createElement('span');
    name.className = 'history-name';
    name.textContent = item.name;
    if (item.kind === 'video') {
      const kind = document.createElement('span');
      kind.className = 'history-kind';
      kind.textContent = 'VIDEO';
      button.append(thumb, kind, name);
    } else {
      button.append(thumb, name);
    }
    const size = document.createElement('span');
    size.className = 'history-size';
    size.textContent = `${item.size[0]} × ${item.size[1]}`;
    button.append(size);
    button.addEventListener('click', async () => {
      updateHistorySelection(item.id);
      await pauseCurrentVideoForHistoryChange();
      videoPlayer.pause();
      $('#realtime-video').hidden = true;
      $('#realtime-video').removeAttribute('src');
      $('#realtime-video').dataset.source = '';
      $('#realtime-loading').hidden = true;
      await withImageLoader(() => callApi('select_history', item.id), 450);
    });
    list.append(button);
  });
}

function updateHistorySelection(currentId) {
  document.querySelectorAll('.history-item').forEach((button) => {
    button.classList.toggle('active', button.dataset.historyId === currentId);
  });
}

async function withImageLoader(action, minimumDuration) {
  const token = ++imageLoadToken;
  const loaderStartedAt = performance.now();
  imageLoading = true;
  $('#image-loading').hidden = false;
  setBusy(false);
  try {
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const completed = await action();
    if (!completed) return false;
    do {
      await refreshState();
      if (token !== imageLoadToken) return false;
      if (!state?.preview_loading && !state?.image_loading) break;
      await new Promise((resolve) => setTimeout(resolve, 50));
    } while (true);
    const remainingLoaderTime = minimumDuration - (performance.now() - loaderStartedAt);
    if (remainingLoaderTime > 0) {
      await new Promise((resolve) => setTimeout(resolve, remainingLoaderTime));
    }
    return true;
  } catch (error) {
    setToast(error.message, 'error');
    return false;
  } finally {
    if (token === imageLoadToken) {
      imageLoading = false;
      $('#image-loading').hidden = true;
      setBusy(state?.job.running ?? false);
    }
  }
}

async function importImage() {
  if (imageLoading) return;
  try {
    await pauseCurrentVideoForHistoryChange();
    const selected = await callApi('open_image');
    if (selected) {
      await withImageLoader(() => callApi('load_selected_image'), 800);
    }
  } catch (error) {
    setToast(error.message, 'error');
  }
}

function syncControls(next) {
  syncAdjustControls(next, pendingSettings);
  syncEnhanceControls(next, pendingSettings);
  const isVideo = next.kind === 'video';
  $('#effects-controls').hidden = isVideo;
  $('#enhance-controls').hidden = isVideo;
  $('#video-controls').hidden = !isVideo;
  $('#image-toolbar').hidden = isVideo;
  $('#video-toolbar').hidden = !isVideo;
  $('#video-tools-bottom').hidden = !isVideo;
  $('#inspector-title').textContent = isVideo ? 'Video' : 'Image';
  $('#inspector-kicker').textContent = isVideo ? 'VIDEO TOOLS' : 'IMAGE TOOLS';
  $('#editor-context').textContent = isVideo ? 'Video' : 'Image';
  $('#image-name').textContent = next.image_name || 'No image loaded';
  $('#export-button').disabled = !next.has_image || next.image_loading || next.job.running;
  $('#remove-button').disabled = !next.has_image || next.image_loading || next.job.running;
  $('#reset-module').disabled = !next.has_image || next.image_loading || next.job.running;
  $('#scale-slider').disabled = !next.has_image || next.image_loading || next.job.running;
  const scale = pendingScale?.entryId === next.current_id ? pendingScale.value : next.scale || 1;
  $('#scale-slider').value = Math.round(scale * 100);
  $('#scale-label').textContent = `${Math.round(scale * 100)}%`;
  $('#dimensions').textContent = next.image_size ? `${next.image_size[0]} × ${next.image_size[1]}` : '-- × --';
  syncDebugPanel(next);

  const job = next.job;
  syncJobOverlay(job);
  const previewHandoff = Boolean(resultPreviewId);
  $('#image-loading').hidden = !(imageLoading || previewHandoff);
  setBusy(job.running);
  $('#crop-button').disabled = !next.has_image || next.image_loading || job.running;
  $('#video-play').textContent = videoPlayer.paused ? '▶' : 'Ⅱ';
  $('#video-play').setAttribute('aria-label', videoPlayer.paused ? 'Play video' : 'Pause video');
  if (next.video) {
    const resolution = $('#video-output-resolution');
    const currentOptions = next.video.output_options || [];
    resolution.replaceChildren(
      ...currentOptions.map((option) => new Option(option.label, option.factor)),
    );
    resolution.value = String(next.settings.enhancement.factor);
    resolution.disabled = job.running || next.video.realtime_running;
    const videoModel = $('#video-model-select');
    if (videoModel.dataset.factor !== String(next.settings.enhancement.factor)) {
      videoModel.replaceChildren(...next.models.map((name) => new Option(name, name)));
      videoModel.dataset.factor = String(next.settings.enhancement.factor);
    }
    videoModel.value = next.settings.enhancement.model;
    syncVideoTimeline();
    const videoScale = pendingScale?.entryId === next.current_id ? pendingScale.value : next.scale || 1;
    if (document.activeElement !== $('#video-zoom')) {
      $('#video-zoom').value = Math.round(videoScale * 100);
    }
    $('#video-zoom-label').textContent = `${Math.round(videoScale * 100)}%`;
    $('#video-zoom').disabled = job.running;
    $('#video-size').textContent = videoNativeSize ? 'Fit' : '1:1';
    $('#video-size').title = videoNativeSize ? 'Fit video to canvas' : 'View at original pixel size';
    $('#video-size').setAttribute('aria-label', $('#video-size').title);
    $('#video-seek').disabled = job.running;
    $('#video-play').disabled = job.running;
    $('#video-rewind').disabled = job.running;
    $('#video-step-back').disabled = job.running;
    $('#video-step-forward').disabled = job.running;
    $('#video-forward').disabled = job.running;
    $('#video-size').disabled = job.running;
    $('#video-volume').disabled = job.running;
    $('#save-video-frame-side').disabled = job.running;
    $('#crop-video-frame').disabled = job.running;
    $('#video-realtime').disabled = job.running;
    $('#video-realtime').classList.toggle('active', next.video.realtime_running);
    $('#video-realtime').textContent = next.video.realtime_running ? 'FX✓' : 'FX';
    $('#save-video-button').disabled = (
      job.running
      || next.video.realtime_running
      || !next.models.length
      || !next.settings.enhancement.model
    );
    const realtimeModel = $('#video-realtime-mode');
    const selectedRealtimeModel = realtimeModel.value;
    const realtimeModels = next.video.realtime_models || [];
    realtimeModel.replaceChildren(
      ...realtimeModels.map((name) => new Option(name, name)),
    );
    realtimeModel.value = realtimeModels.includes(selectedRealtimeModel)
      ? selectedRealtimeModel
      : next.video.realtime_model || realtimeModels[0] || '';
    realtimeModel.disabled = job.running || next.video.realtime_running
      || !realtimeModels.length;
    $('#video-fullscreen').disabled = job.running;
  }
  if (job.status === 'Complete' || job.status === 'Cancelled') {
    callApi('dismiss_job');
  }
  if (next.message) setToast(next.message.text, next.message.type);
}

async function fetchAndApplyState() {
  try {
    const previousId = state?.current_id;
    const next = await callApi('get_state', state?.image_revision ?? null, state?.history_revision ?? null);
    if (state && next.revision < state.revision) return;
    if (
      next.job.status === 'Complete'
      && ['upscale', 'denoise'].includes(next.job.kind)
      && previousId !== next.current_id
      && next.preview_loading
    ) {
      resultPreviewId = next.current_id;
    }
    if (resultPreviewId && (resultPreviewId !== next.current_id || !next.preview_loading)) {
      resultPreviewId = null;
    }
    for (const [key, value] of pendingSettings) {
      const actual = SLIDER_SETTING_KEYS.has(key)
        ? next.settings.effects[key]
        : key === 'Inversion'
          ? next.settings.effects.Inversion
          : next.settings.enhancement[key];
      if (Object.is(actual, value)) pendingSettings.delete(key);
    }
    if (pendingScale) {
      if (pendingScale.entryId !== next.current_id) {
        pendingScale = null;
      } else if (Math.abs(next.scale - pendingScale.value) < 0.001) {
        pendingScale = null;
      } else {
        next.scale = pendingScale.value;
      }
    }
    if (previousId && previousId !== next.current_id) panById.set(previousId, pan);
    if (!previousId || previousId !== next.current_id) pan = panById.get(next.current_id) || { x: 0, y: 0 };
    state = next;
    applyPreview(next);
    syncControls(next);
    if (next.history) renderHistory(next);
    updateHistorySelection(next.current_id);
  } catch (error) {
    setToast(error.message, 'error');
  }
}

async function refreshState() {
  if (stateRefreshPromise) {
    stateRefreshQueued = true;
    return stateRefreshPromise;
  }
  stateRefreshPromise = (async () => {
    do {
      stateRefreshQueued = false;
      await fetchAndApplyState();
    } while (stateRefreshQueued);
  })();
  try {
    await stateRefreshPromise;
  } finally {
    stateRefreshPromise = null;
  }
}

async function pollJobState() {
  if (jobPollInFlight) return;
  jobPollInFlight = true;
  try {
    const job = await callApi('get_job_state');
    syncJobOverlay(job);
    if (state) syncDebugPanel({ ...state, job, debug: job.running ? {
      fps: job.processing_fps,
      device: job.processing_device,
      ram_bytes: job.ram_bytes,
      gpu_memory_bytes: job.gpu_memory_bytes,
    } : state.debug });
    if (
      !state
      || !job.running
      || state.video?.realtime_running
      || ['Complete', 'Cancelled', 'Failed'].includes(job.status)
    ) {
      await refreshState();
    }
  } catch (error) {
    setToast(`Could not read processing progress: ${error.message}`, 'error');
  } finally {
    jobPollInFlight = false;
  }
}

function startPolling() {
  if (jobPollTimer) return;
  pollJobState();
  jobPollTimer = setInterval(pollJobState, 150);
}

function setSetting(key, value) {
  pendingSettings.set(key, value);
  if (settingTimer) return;
  settingTimer = setTimeout(flushSettings, 50);
}

async function flushSettings() {
  settingTimer = null;
  if (settingsFlushInProgress) return;
  const updates = [...pendingSettings.entries()];
  if (!updates.length) return;
  settingsFlushInProgress = true;
  try {
    for (const [key, value] of updates) {
      if (!await callApi('set_setting', key, value)) throw new Error(`Could not apply ${key}.`);
    }
    await refreshState();
  } catch (error) {
    setToast(error.message, 'error');
  } finally {
    settingsFlushInProgress = false;
    if (pendingSettings.size && !settingTimer) settingTimer = setTimeout(flushSettings, 50);
  }
}

function setScale(value, anchor = null) {
  if (!state?.has_image) return;
  const scale = Number(value) / 100;
  const stage = $('#stage');
  const media = state.kind === 'video' ? videoPlayer : $('#preview-image');
  const stageRect = stage.getBoundingClientRect();
  const mediaRect = media.getBoundingClientRect();
  const sourceWidth = state.kind === 'video' ? videoPlayer.videoWidth || state.image_size[0] : state.image_size[0];
  const sourceHeight = state.kind === 'video' ? videoPlayer.videoHeight || state.image_size[1] : state.image_size[1];
  const fit = Math.min((stage.clientWidth - 64) / sourceWidth, (stage.clientHeight - 64) / sourceHeight, 1);
  const newWidth = sourceWidth * fit * scale;
  const newHeight = sourceHeight * fit * scale;
  const anchorX = anchor?.x ?? (stageRect.left + stageRect.width / 2);
  const anchorY = anchor?.y ?? (stageRect.top + stageRect.height / 2);
  const relativeX = Math.max(0, Math.min(1, (anchorX - mediaRect.left) / mediaRect.width));
  const relativeY = Math.max(0, Math.min(1, (anchorY - mediaRect.top) / mediaRect.height));
  const maxPanX = Math.max(0, (newWidth - stageRect.width) / 2);
  const maxPanY = Math.max(0, (newHeight - stageRect.height) / 2);
  pan.x = Math.max(-maxPanX, Math.min(maxPanX,
    anchorX - stageRect.left - (relativeX - 0.5) * newWidth - stageRect.width / 2));
  pan.y = Math.max(-maxPanY, Math.min(maxPanY,
    anchorY - stageRect.top - (relativeY - 0.5) * newHeight - stageRect.height / 2));
  state.scale = scale;
  pendingScale = { entryId: state.current_id, value: scale };
  if (state.kind === 'video') {
    videoNativeSize = false;
    $('#video-zoom-label').value = `${Math.round(value)}%`;
    $('#video-size').textContent = '1:1';
    $('#video-size').title = 'View at original pixel size';
  } else {
    $('#scale-label').textContent = `${Math.round(value)}%`;
  }
  applyPreview(state);
  clearTimeout(scaleTimer);
  scaleTimer = setTimeout(() => runAction('set_scale', scale), 50);
}

$('#open-button').addEventListener('click', importImage);
$('#empty-open-button').addEventListener('click', importImage);
$('#debug-toggle').addEventListener('change', () => syncDebugPanel(state || { media_info: null }));
$('#export-button').addEventListener('click', () => {
  if (state?.kind === 'video') {
    return runAction('save_video');
  }
  return runAction('save_image');
});
$('#save-video-button').addEventListener('click', () => {
  showVideoUpscaleStarting();
  return runAction('start_video_upscale');
});
$('#remove-button').addEventListener('click', async () => {
  if (window.confirm('Remove this image and its edits?')) {
    await pauseCurrentVideoForHistoryChange();
    await runAction('remove_image');
  }
});
$('#reset-module').addEventListener('click', () => runAction('reset_module'));
$('#cancel-job').addEventListener('click', async () => {
  $('#cancel-job').disabled = true;
  try {
    await callApi('cancel_operation');
    await refreshState();
  } catch (error) {
    setToast(error.message, 'error');
    $('#cancel-job').disabled = false;
  }
});
async function initialize() {
  const moduleStatus = await loadFeatureModules();
  Object.entries(moduleStatus)
    .filter(([, available]) => !available)
    .forEach(([name]) => disableUnavailableFeature(name));

  bindAdjustControls(setSetting, runAction);
  bindEnhanceControls(setSetting, runAction);
  bindVideoControls({
    $, callApi, runAction, getState: () => state, videoPlayer, syncVideoTimeline,
    applyPreview, setScale, setToast,
    pauseCurrentVideoForHistoryChange,
    setSetting,
    getVideoNativeSize: () => videoNativeSize,
    setVideoNativeSize: (value) => { videoNativeSize = value; },
    getPan: () => pan,
    setPan: (value) => { pan = value; },
  });
  bindCanvasControls({
    $, getState: () => state, getPan: () => pan, setPan: (value) => { pan = value; },
    applyPreview, setScale, runAction, setToast, videoPlayer,
    pauseCurrentVideoForHistoryChange,
    getVideoNativeSize: () => videoNativeSize,
  });

  if (window.pywebview?.api) startPolling();
  else window.addEventListener('pywebviewready', startPolling, { once: true });
  setBusy(false);
}

initialize().catch((error) => {
  console.error('Could not initialize the application UI.', error);
  setToast(error.message, 'error');
});
