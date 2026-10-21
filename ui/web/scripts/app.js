import { bindAdjustControls, syncAdjustControls } from './modules/adjust.js';
import { bindEnhanceControls, syncEnhanceControls } from './modules/enhance.js';

const $ = (selector) => document.querySelector(selector);
const SLIDER_SETTING_KEYS = new Set(['Brightness', 'Color', 'Contrast', 'Sharpness', 'Blur']);
let state = null;
let pan = { x: 0, y: 0 };
const panById = new Map();
const videoPlayer = document.querySelector('#video-player');
let lastVideoPositionSync = 0;
let dragStart = null;
let cropStart = null;
let toastTimer = null;
let settingTimer = null;
let scaleTimer = null;
const pendingSettings = new Map();
let settingsFlushInProgress = false;
let stateRefreshQueued = false;
let stateRefreshPromise = null;
let cropMode = false;
let imageLoading = false;
let imageLoadToken = 0;
let resultPreviewId = null;

function callApi(method, ...args) {
  const api = window.pywebview?.api;
  if (!api) return Promise.reject(new Error('The Python bridge is not ready yet.'));
  return api[method](...args);
}

async function runAction(method, ...args) {
  try {
    const result = await callApi(method, ...args);
    await refreshState();
    return result;
  } catch (error) {
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

function setBusy(busy) {
  const imageUnavailable = !state?.has_image;
  const blocked = busy || imageLoading || resultPreviewId || state?.image_loading;
  document.querySelectorAll('.controls input, .controls select, .controls button, .mode-tab, .history-item, #remove-button, #open-button, #empty-open-button, #export-button')
    .forEach((control) => {
      const importAction = control.id === 'open-button' || control.id === 'empty-open-button';
      control.disabled = blocked || (imageUnavailable && !importAction);
    });
  if (state?.has_image) {
    $('#open-button').disabled = blocked;
    $('#empty-open-button').disabled = blocked;
    $('#export-button').disabled = blocked;
  }
}

function syncVideoTimeline() {
  const duration = Number.isFinite(videoPlayer.duration)
    ? videoPlayer.duration
    : state?.video?.duration || 0;
  const current = Number.isFinite(videoPlayer.currentTime) ? videoPlayer.currentTime : 0;
  const formatTime = (seconds) => {
    const value = Math.max(0, Math.floor(seconds));
    return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
  };
  $('#video-time').textContent = `${formatTime(current)} / ${formatTime(duration)}`;
  if (document.activeElement !== $('#video-seek')) {
    $('#video-seek').value = duration ? Math.round((current / duration) * 1000) : 0;
  }
  $('#video-play').textContent = videoPlayer.paused ? '▶' : 'Ⅱ';
  $('#video-play').setAttribute('aria-label', videoPlayer.paused ? 'Play video' : 'Pause video');
  const volume = $('#video-volume');
  if (document.activeElement !== volume) {
    volume.value = videoPlayer.muted ? 0 : videoPlayer.volume;
  }
}

function applyPreview(next) {
  const stage = $('#stage');
  const image = $('#preview-image');
  const video = $('#video-player');
  if (!next?.has_image) {
    video.pause();
    video.hidden = true;
    image.hidden = true;
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
    image.hidden = true;
    video.hidden = false;
    if (video.dataset.source !== next.video.url) {
      video.pause();
      video.crossOrigin = 'anonymous';
      video.dataset.source = next.video.url;
      video.src = next.video.url;
      video.load();
    }
    video.style.width = `${Math.max(1, width * fit)}px`;
    video.style.height = `${Math.max(1, height * fit)}px`;
  } else {
    video.pause();
    video.hidden = true;
    image.hidden = false;
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
  const enhanced = next.module === 'Resolution_Enhancement';
  $('#effects-controls').hidden = isVideo || enhanced;
  $('#enhance-controls').hidden = isVideo || !enhanced;
  $('#video-controls').hidden = !isVideo;
  $('#image-toolbar').hidden = isVideo;
  $('#video-toolbar').hidden = !isVideo;
  $('#inspector-title').textContent = isVideo ? 'Video' : enhanced ? 'Enhance' : 'Adjust';
  $('#inspector-kicker').textContent = isVideo ? 'VIDEO ENHANCEMENT' : enhanced ? 'RESOLUTION ENHANCEMENT' : 'IMAGE EFFECTS';
  document.querySelectorAll('.mode-tab').forEach((tab) => tab.classList.toggle('selected', tab.dataset.module === next.module));
  $('#image-name').textContent = next.image_name || 'No image loaded';
  $('#export-button').disabled = !next.has_image || next.image_loading || next.job.running;
  $('#remove-button').disabled = !next.has_image || next.image_loading || next.job.running;
  $('#reset-module').disabled = !next.has_image || next.image_loading || next.job.running;
  $('#scale-slider').disabled = !next.has_image || next.image_loading || next.job.running;
  $('#scale-slider').value = Math.round((next.scale || 1) * 100);
  $('#scale-label').textContent = `${Math.round((next.scale || 1) * 100)}%`;
  $('#dimensions').textContent = next.image_size ? `${next.image_size[0]} × ${next.image_size[1]}` : '-- × --';

  const job = next.job;
  const exporting = job.kind === 'export';
  $('#job-overlay').hidden = !job.running;
  $('#job-status').textContent = exporting ? 'Exporting image' : job.status || 'Processing image';
  $('#job-percent').textContent = exporting ? 'Saving' : `${job.progress || 0}%`;
  $('#progress-fill').style.width = `${job.progress || 0}%`;
  $('.progress-track').classList.toggle('indeterminate', exporting);
  $('#cancel-job').hidden = exporting;
  $('#job-detail').textContent = exporting
    ? 'Applying effects and writing the image'
    : job.total
      ? `${job.stage.replaceAll('-', ' ')} · ${job.current}/${job.total} ${job.unit}${job.total === 1 ? '' : 's'}`
      : 'Preparing image';
  const previewHandoff = Boolean(resultPreviewId);
  $('#image-loading').hidden = !(imageLoading || previewHandoff);
  setBusy(job.running);
  $('#adjust-tab').disabled = !next.has_image || isVideo || next.image_loading || job.running;
  $('#enhance-tab').disabled = !next.has_image || isVideo || next.image_loading || job.running;
  $('#video-tab').disabled = !isVideo || next.image_loading || job.running;
  $('#crop-button').disabled = !next.has_image || next.image_loading || job.running;
  $('#video-play').textContent = videoPlayer.paused ? '▶' : 'Ⅱ';
  $('#video-play').setAttribute('aria-label', videoPlayer.paused ? 'Play video' : 'Pause video');
  if (next.video) {
    syncVideoTimeline();
    $('#video-seek').disabled = job.running;
    $('#video-play').disabled = job.running;
    $('#video-rewind').disabled = job.running;
    $('#video-step-back').disabled = job.running;
    $('#video-step-forward').disabled = job.running;
    $('#video-forward').disabled = job.running;
    $('#video-volume').disabled = job.running;
    $('#save-video-frame').disabled = job.running;
    $('#save-video-frame-side').disabled = job.running;
    $('#crop-video-frame').disabled = job.running;
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

async function pollState() {
  await refreshState();
  setTimeout(pollState, 150);
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

function setScale(value) {
  if (!state?.has_image) return;
  const scale = Number(value) / 100;
  state.scale = scale;
  $('#scale-label').textContent = `${Math.round(value)}%`;
  applyPreview(state);
  clearTimeout(scaleTimer);
  scaleTimer = setTimeout(() => runAction('set_scale', scale), 50);
}

$('#open-button').addEventListener('click', importImage);
$('#empty-open-button').addEventListener('click', importImage);
$('#export-button').addEventListener('click', () => runAction('save_image'));
$('#remove-button').addEventListener('click', async () => {
  if (window.confirm('Remove this image and its edits?')) await runAction('remove_image');
});
$('#reset-module').addEventListener('click', () => runAction('reset_module'));
$('#cancel-job').addEventListener('click', () => callApi('cancel_operation'));
document.querySelectorAll('.mode-tab').forEach((tab) => tab.addEventListener('click', () => runAction('set_module', tab.dataset.module)));
bindAdjustControls(setSetting, runAction);
bindEnhanceControls(setSetting, runAction);

function syncVideoPosition(force = false) {
  if (!state?.video || !Number.isFinite(videoPlayer.currentTime)) return;
  syncVideoTimeline();
  const now = performance.now();
  if (force || now - lastVideoPositionSync >= 250) {
    lastVideoPositionSync = now;
    callApi('set_video_position', videoPlayer.currentTime).catch(() => {});
  }
}

function seekVideo(seconds) {
  if (!state?.video || !Number.isFinite(videoPlayer.duration)) return;
  videoPlayer.currentTime = Math.max(0, Math.min(videoPlayer.duration, seconds));
  syncVideoPosition(true);
}

videoPlayer.addEventListener('loadedmetadata', () => {
  if (state?.video && Number.isFinite(state.video.position)) {
    videoPlayer.currentTime = Math.min(state.video.position, videoPlayer.duration || state.video.position);
  }
  syncVideoTimeline();
});
videoPlayer.addEventListener('timeupdate', () => syncVideoPosition());
videoPlayer.addEventListener('pause', () => syncVideoPosition(true));
videoPlayer.addEventListener('ended', () => syncVideoPosition(true));
videoPlayer.addEventListener('volumechange', syncVideoTimeline);
$('#video-play').addEventListener('click', async () => {
  if (!state?.video) return;
  if (videoPlayer.paused) {
    try {
      await videoPlayer.play();
    } catch (error) {
      setToast(`Could not play video: ${error.message}`, 'error');
    }
  } else {
    videoPlayer.pause();
  }
  syncVideoTimeline();
});
$('#video-rewind').addEventListener('click', () => seekVideo(videoPlayer.currentTime - 10));
$('#video-forward').addEventListener('click', () => seekVideo(videoPlayer.currentTime + 10));
$('#video-step-back').addEventListener('click', () => {
  videoPlayer.pause();
  seekVideo(videoPlayer.currentTime - 1 / (state?.video?.fps || 30));
});
$('#video-step-forward').addEventListener('click', () => {
  videoPlayer.pause();
  seekVideo(videoPlayer.currentTime + 1 / (state?.video?.fps || 30));
});
$('#video-volume').addEventListener('input', (event) => {
  const volume = Number(event.target.value);
  videoPlayer.volume = volume;
  videoPlayer.muted = volume === 0;
  syncVideoTimeline();
});
$('#video-seek').addEventListener('input', (event) => {
  if (Number.isFinite(videoPlayer.duration)) {
    seekVideo((Number(event.target.value) / 1000) * videoPlayer.duration);
  }
});
$('#save-video-frame').addEventListener('click', () => runAction('save_video_frame', videoPlayer.currentTime));
$('#save-video-frame-side').addEventListener('click', () => runAction('save_video_frame', videoPlayer.currentTime));
$('#crop-video-frame').addEventListener('click', () => {
  cropMode = true;
  $('#stage').classList.add('cropping');
  $('#crop-button').classList.add('active');
  setToast('Drag over the current frame to create a cropped image.');
});

function updateScale(value) {
  setScale(value);
}
$('#scale-slider').addEventListener('input', (event) => updateScale(event.target.value));
$('#fit-button').addEventListener('click', () => updateScale(100));
$('#reset-scale-button').addEventListener('click', () => updateScale(100));

$('#crop-button').addEventListener('click', () => {
  cropMode = !cropMode;
  $('#stage').classList.toggle('cropping', cropMode);
  $('#crop-button').classList.toggle('active', cropMode);
  setToast(cropMode ? 'Drag over the image to crop. Press Escape to cancel.' : 'Crop selection cancelled.');
});
$('#stage').addEventListener('pointerdown', (event) => {
  if (!state?.has_image) return;
  if (cropMode || event.ctrlKey) {
    cropStart = { x: event.clientX, y: event.clientY };
    $('#crop-box').hidden = false;
    $('#crop-box').style.left = `${cropStart.x - $('#stage').getBoundingClientRect().left}px`;
    $('#crop-box').style.top = `${cropStart.y - $('#stage').getBoundingClientRect().top}px`;
    $('#crop-box').style.width = '0px';
    $('#crop-box').style.height = '0px';
    event.preventDefault();
  } else if (event.shiftKey) {
    dragStart = { x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y };
    $('#stage').setPointerCapture(event.pointerId);
    event.preventDefault();
  }
});
window.addEventListener('pointermove', (event) => {
  if (cropStart) {
    const stageRect = $('#stage').getBoundingClientRect();
    const left = Math.max(0, Math.min(cropStart.x, event.clientX) - stageRect.left);
    const top = Math.max(0, Math.min(cropStart.y, event.clientY) - stageRect.top);
    const right = Math.min(stageRect.width, Math.max(cropStart.x, event.clientX) - stageRect.left);
    const bottom = Math.min(stageRect.height, Math.max(cropStart.y, event.clientY) - stageRect.top);
    Object.assign($('#crop-box').style, { left: `${left}px`, top: `${top}px`, width: `${Math.max(0, right - left)}px`, height: `${Math.max(0, bottom - top)}px` });
  } else if (dragStart) {
    const stage = $('#stage');
    const image = $('#preview-image');
    const maxX = Math.max(0, (image.clientWidth - stage.clientWidth) / 2);
    const maxY = Math.max(0, (image.clientHeight - stage.clientHeight) / 2);
    pan.x = Math.max(-maxX, Math.min(maxX, dragStart.panX + event.clientX - dragStart.x));
    pan.y = Math.max(-maxY, Math.min(maxY, dragStart.panY + event.clientY - dragStart.y));
    applyPreview(state);
  }
});
window.addEventListener('pointerup', async (event) => {
  if (cropStart) {
    const start = cropStart;
    cropStart = null;
    $('#crop-box').hidden = true;
    if (cropMode) {
      cropMode = false;
      $('#stage').classList.remove('cropping');
      $('#crop-button').classList.remove('active');
    }
    const displayedImage = state?.kind === 'video' ? videoPlayer : $('#preview-image');
    const imageRect = displayedImage.getBoundingClientRect();
    const left = Math.max(0, Math.min(start.x, event.clientX) - imageRect.left) / imageRect.width;
    const top = Math.max(0, Math.min(start.y, event.clientY) - imageRect.top) / imageRect.height;
    const right = Math.min(imageRect.width, Math.max(start.x, event.clientX) - imageRect.left) / imageRect.width;
    const bottom = Math.min(imageRect.height, Math.max(start.y, event.clientY) - imageRect.top) / imageRect.height;
    if (right > left && bottom > top) {
      const position = state?.kind === 'video' ? videoPlayer.currentTime : undefined;
      await runAction('crop_image', [left, top, right, bottom], position);
    }
  }
  dragStart = null;
});
window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    cropStart = null;
    cropMode = false;
    $('#crop-box').hidden = true;
    $('#stage').classList.remove('cropping');
    $('#crop-button').classList.remove('active');
  }
});
$('#stage').addEventListener('wheel', (event) => {
  if (!event.shiftKey || !state?.has_image) return;
  event.preventDefault();
  const current = Number($('#scale-slider').value);
  const next = Math.max(10, Math.min(500, current + (event.deltaY < 0 ? 15 : -15)));
  const stageRect = $('#stage').getBoundingClientRect();
  const imageRect = $('#preview-image').getBoundingClientRect();
  const relativeX = (event.clientX - (imageRect.left + imageRect.width / 2)) / imageRect.width;
  const relativeY = (event.clientY - (imageRect.top + imageRect.height / 2)) / imageRect.height;
  const zoomRatio = next / current;
  const newWidth = imageRect.width * zoomRatio;
  const newHeight = imageRect.height * zoomRatio;
  pan.x = event.clientX - stageRect.left - relativeX * newWidth - stageRect.width / 2;
  pan.y = event.clientY - stageRect.top - relativeY * newHeight - stageRect.height / 2;
  $('#scale-slider').value = next;
  updateScale(next);
}, { passive: false });
window.addEventListener('resize', () => { if (state) applyPreview(state); });

if (window.pywebview?.api) pollState();
else window.addEventListener('pywebviewready', pollState, { once: true });