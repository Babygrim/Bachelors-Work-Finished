export function bindVideoControls({
  $, callApi, runAction, getState, videoPlayer, syncVideoTimeline,
  applyPreview, setScale, setToast, getVideoNativeSize, setVideoNativeSize,
  getPan, setPan, setSetting,
}) {
  let lastPositionSync = 0;

  function syncVideoPosition(force = false) {
    const state = getState();
    if (!state?.video || !Number.isFinite(videoPlayer.currentTime)) return;
    syncVideoTimeline();
    const now = performance.now();
    if (force || now - lastPositionSync >= 250) {
      lastPositionSync = now;
      callApi('set_video_position', videoPlayer.currentTime).catch(() => {});
    }
  }

  function seekVideo(seconds) {
    if (!getState()?.video || !Number.isFinite(videoPlayer.duration)) return;
    videoPlayer.currentTime = Math.max(0, Math.min(videoPlayer.duration, seconds));
    syncVideoPosition(true);
  }

  videoPlayer.addEventListener('loadedmetadata', () => {
    const state = getState();
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
    if (!getState()?.video) return;
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
  $('#video-realtime').addEventListener('click', async () => {
    const state = getState();
    if (!state?.video) return;
    const method = state.video.realtime_running
      ? 'stop_video_realtime'
      : 'start_video_realtime';
    const started = method === 'start_video_realtime'
      ? await runAction(method, videoPlayer.currentTime, $('#video-realtime-mode').value)
      : await runAction(method);
    if (started && method === 'start_video_realtime') {
      try {
        await videoPlayer.play();
      } catch (error) {
        setToast(`Could not play audio: ${error.message}`, 'error');
      }
    }
  });
  $('#video-output-resolution').addEventListener('change', (event) => {
    setSetting('factor', Number(event.target.value));
  });
  $('#video-model-select').addEventListener('change', (event) => {
    setSetting('model', event.target.value);
  });
  $('#video-keep-size').addEventListener('change', (event) => {
    setSetting('keep_size', event.target.checked);
  });
  $('#video-size').addEventListener('click', () => {
    setVideoNativeSize(!getVideoNativeSize());
    setPan({ x: 0, y: 0 });
    const state = getState();
    if (state) applyPreview(state);
    $('#video-size').textContent = getVideoNativeSize() ? 'Fit' : '1:1';
    $('#video-size').title = getVideoNativeSize() ? 'Fit video to canvas' : 'View at original pixel size';
  });
  $('#video-zoom').addEventListener('input', (event) => setScale(event.target.value));
  $('#video-rewind').addEventListener('click', () => seekVideo(videoPlayer.currentTime - 10));
  $('#video-forward').addEventListener('click', () => seekVideo(videoPlayer.currentTime + 10));
  $('#video-step-back').addEventListener('click', () => {
    videoPlayer.pause();
    seekVideo(videoPlayer.currentTime - 1 / (getState()?.video?.fps || 30));
  });
  $('#video-step-forward').addEventListener('click', () => {
    videoPlayer.pause();
    seekVideo(videoPlayer.currentTime + 1 / (getState()?.video?.fps || 30));
  });
  $('#video-mute').addEventListener('click', () => {
    videoPlayer.muted = !videoPlayer.muted;
    $('#video-mute').textContent = videoPlayer.muted ? '🔇' : '🔊';
    $('#video-mute').title = videoPlayer.muted ? 'Unmute' : 'Mute';
    $('#video-mute').setAttribute('aria-label', $('#video-mute').title);
    syncVideoTimeline();
  });
  $('#video-volume').addEventListener('input', (event) => {
    const volume = Number(event.target.value);
    videoPlayer.volume = volume;
    videoPlayer.muted = volume === 0;
    syncVideoTimeline();
  });
  $('#video-fullscreen').addEventListener('click', async () => {
    const stage = $('#stage');
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await stage.requestFullscreen();
      }
    } catch (error) {
      setToast(`Could not enter full screen: ${error.message}`, 'error');
    }
  });
  document.addEventListener('fullscreenchange', () => {
    const state = getState();
    if (state) applyPreview(state);
  });
  $('#video-seek').addEventListener('input', (event) => {
    if (Number.isFinite(videoPlayer.duration)) {
      seekVideo((Number(event.target.value) / 1000) * videoPlayer.duration);
    }
  });
  $('#save-video-frame').addEventListener('click', () => runAction('save_video_frame', videoPlayer.currentTime));
  $('#save-video-frame-side').addEventListener('click', () => runAction('save_video_frame', videoPlayer.currentTime));
  $('#crop-video-frame').addEventListener('click', () => {
    $('#stage').classList.add('cropping');
    $('#crop-button').classList.add('active');
    setToast('Drag over the current frame to create a cropped image.');
  });
}
