const SVG_ATTRS = 'viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
  + 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
const SPEAKER = '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" fill="currentColor"/>';
const ICON_VOLUME = `<svg ${SVG_ATTRS}>${SPEAKER}<path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/></svg>`;
const ICON_MUTED = `<svg ${SVG_ATTRS}>${SPEAKER}<line x1="16" y1="9" x2="22" y2="15"/><line x1="22" y1="9" x2="16" y2="15"/></svg>`;

export function setMuteButton(button, muted) {
  const icon = muted ? ICON_MUTED : ICON_VOLUME;
  if (button.dataset.icon !== icon) {
    button.innerHTML = icon;
    button.dataset.icon = icon;
  }
  button.title = muted ? 'Unmute' : 'Mute';
  button.setAttribute('aria-label', button.title);
}

// The processed preview has no audio track, so the sound comes from the source video element
// (hidden while real-time upscaling runs) and is kept in step with the preview position.
const DRIFT_LIMIT_SECONDS = 0.35;
const MIN_AUDIBLE_SPEED = 0.6;
const SPEED_WINDOW_MS = 1500;

export function createRealtimeAudio({ videoPlayer, realtimePlayer, getState }) {
  let samples = [];

  function previewPosition(video) {
    return video.realtime_transport === 'mse'
      && realtimePlayer.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA
      ? realtimePlayer.currentTime
      : Number(video.realtime_position) || 0;
  }

  // Preview speed relative to the video's own timeline (1 = real time).
  function previewSpeed(position) {
    const now = performance.now();
    const last = samples[samples.length - 1];
    if (last && Math.abs(position - last[1]) > 2) samples = [];  // seek: not a speed change
    samples.push([now, position]);
    samples = samples.filter(([time]) => now - time <= SPEED_WINDOW_MS);
    const [firstTime, firstPosition] = samples[0];
    const elapsed = now - firstTime;
    if (elapsed < 400) return 1;
    return Math.max(0, (position - firstPosition) / (elapsed / 1000));
  }

  function silence() {
    samples = [];
    if (!videoPlayer.paused) videoPlayer.pause();
  }

  function update() {
    const state = getState();
    const video = state?.video;
    if (!video?.realtime_running) {
      samples = [];
      if (videoPlayer.playbackRate !== 1) videoPlayer.playbackRate = 1;
      return;
    }
    if (video.realtime_paused || video.realtime_loading || state.job.running) {
      silence();
      return;
    }
    const position = previewPosition(video);
    const speed = previewSpeed(position);
    if (speed < MIN_AUDIBLE_SPEED) {
      // Audio stretched this far would be unintelligible; stay silent until the preview keeps up.
      if (!videoPlayer.paused) videoPlayer.pause();
      return;
    }
    const rate = Math.min(1, speed);
    if (Math.abs(videoPlayer.playbackRate - rate) > 0.02) videoPlayer.playbackRate = rate;
    if (
      videoPlayer.paused
      || !Number.isFinite(videoPlayer.currentTime)
      || Math.abs(videoPlayer.currentTime - position) > DRIFT_LIMIT_SECONDS
    ) {
      videoPlayer.currentTime = position;
    }
    if (videoPlayer.paused) videoPlayer.play().catch(() => {});
  }

  return { update };
}
