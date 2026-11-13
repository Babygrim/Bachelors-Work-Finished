export function bindVideoControls({
  $, callApi, runAction, getState, videoPlayer, syncVideoTimeline,
  applyPreview, setScale, setToast, getVideoNativeSize, setVideoNativeSize,
  getPan, setPan, setSetting, pauseCurrentVideoForHistoryChange,
}) {
  let lastPositionSync = 0;
  let pendingRealtimePosition = null;
  let pendingRealtimeDirection = 0;

  function syncVideoPosition(force = false) {
    const state = getState();
    if (!state?.video || !Number.isFinite(videoPlayer.currentTime)) return;
    if (state.video.realtime_running) {
      syncVideoTimeline();
      return;
    }
    syncVideoTimeline();
    const now = performance.now();
    if (force || now - lastPositionSync >= 250) {
      lastPositionSync = now;
      callApi('set_video_position', videoPlayer.currentTime).catch(() => {});
    }
  }

  function getCurrentVideoPosition() {
    const state = getState();
    if (state?.video?.realtime_running) {
      const realtimePosition = Number(state.video.realtime_position);
      if (pendingRealtimePosition !== null) {
        const reached = pendingRealtimeDirection < 0
          ? realtimePosition <= pendingRealtimePosition
          : realtimePosition >= pendingRealtimePosition;
        if (reached) {
          pendingRealtimePosition = null;
          pendingRealtimeDirection = 0;
        }
      }
      if (pendingRealtimePosition !== null) {
        return pendingRealtimePosition;
      }
      return Number.isFinite(state.video.realtime_position)
        ? state.video.realtime_position
        : 0;
    }
    pendingRealtimePosition = null;
    pendingRealtimeDirection = 0;
    return Number.isFinite(videoPlayer.currentTime) ? videoPlayer.currentTime : 0;
  }

  function seekVideo(seconds) {
    const state = getState();
    if (!state?.video) return;
    const realtime = state.video.realtime_running;
    const duration = realtime
      ? state.video.duration
      : videoPlayer.duration;
    if (!Number.isFinite(duration)) return;
    const position = Math.max(0, Math.min(duration, seconds));
    if (!realtime) {
      videoPlayer.currentTime = position;
      syncVideoPosition(true);
    } else {
      const current = getCurrentVideoPosition();
      pendingRealtimePosition = position;
      pendingRealtimeDirection = Math.sign(position - current) || 1;
      callApi('seek_video_realtime', position).catch((error) => {
        pendingRealtimePosition = null;
        pendingRealtimeDirection = 0;
        setToast(`Could not seek real-time preview: ${error.message}`, 'error');
      });
    }
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
    const state = getState();
    if (!state?.video) return;
    try {
      if (state.video.realtime_running) {
        await runAction(
          'set_video_realtime_paused',
          !state.video.realtime_paused,
        );
      } else if (videoPlayer.paused) {
        await videoPlayer.play();
      } else {
        videoPlayer.pause();
      }
    } catch (error) {
      setToast(`Could not control video: ${error.message}`, 'error');
    }
    syncVideoTimeline();
  });
  $('#video-realtime').addEventListener('click', async () => {
    const state = getState();
    if (!state?.video) return;
    const method = state.video.realtime_running
      ? 'stop_video_realtime'
      : 'start_video_realtime';
    if (method === 'start_video_realtime') {
      const position = getCurrentVideoPosition();
      const wasPaused = videoPlayer.paused;
      videoPlayer.pause();
      const started = await runAction(
        method,
        position,
        $('#video-realtime-mode').value,
      );
      if (!started) {
        videoPlayer.currentTime = position;
        if (!wasPaused) {
          try {
            await videoPlayer.play();
          } catch (error) {
            setToast(`Could not resume video: ${error.message}`, 'error');
          }
        }
      } else if (wasPaused) {
        await runAction('set_video_realtime_paused', true);
      }
    } else {
      const position = state.video.realtime_position || 0;
      const wasPaused = state.video.realtime_paused;
      const stoppedPosition = await runAction(method);
      videoPlayer.currentTime = Number.isFinite(stoppedPosition)
        ? stoppedPosition
        : position;
      if (wasPaused) {
        videoPlayer.pause();
      } else {
        try {
          await videoPlayer.play();
        } catch (error) {
          setToast(`Could not resume video: ${error.message}`, 'error');
        }
      }
    }
  });
  videoPlayer.addEventListener('pause', async () => {
    const state = getState();
    if (state?.video?.realtime_running && !state.video.realtime_paused) {
      await runAction('set_video_realtime_paused', true);
    }
  });
  $('#video-output-resolution').addEventListener('change', (event) => {
    setSetting('factor', Number(event.target.value));
  });
  $('#video-model-select').addEventListener('change', (event) => {
    setSetting('model', event.target.value);
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
  $('#video-rewind').addEventListener('click', () => seekVideo(getCurrentVideoPosition() - 10));
  $('#video-forward').addEventListener('click', () => seekVideo(getCurrentVideoPosition() + 10));
  $('#video-step-back').addEventListener('click', () => {
    videoPlayer.pause();
    seekVideo(getCurrentVideoPosition() - 1 / (getState()?.video?.fps || 30));
  });
  $('#video-step-forward').addEventListener('click', () => {
    videoPlayer.pause();
    seekVideo(getCurrentVideoPosition() + 1 / (getState()?.video?.fps || 30));
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
    const state = getState();
    const duration = state?.video?.realtime_running
      ? state.video.duration
      : videoPlayer.duration;
    if (Number.isFinite(duration)) {
      seekVideo((Number(event.target.value) / 1000) * duration);
    }
  });
  $('#save-video-frame-side').addEventListener('click', async () => {
    await pauseCurrentVideoForHistoryChange();
    await runAction('save_video_frame', getCurrentVideoPosition());
  });
  $('#crop-video-frame').addEventListener('click', () => {
    $('#stage').classList.add('cropping');
    $('#crop-button').classList.add('active');
    setToast('Drag over the current frame to create a cropped image.');
  });
}
