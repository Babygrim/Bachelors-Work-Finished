export function bindCanvasControls({
  $, getState, getPan, setPan, applyPreview, setScale, runAction, setToast,
  videoPlayer, pauseCurrentVideoForHistoryChange, getVideoNativeSize,
}) {
  let cropMode = false;
  let cropStart = null;
  let dragStart = null;

  function stopCropMode(message = '') {
    cropMode = false;
    $('#crop-box').hidden = true;
    $('#stage').classList.remove('cropping');
    $('#crop-button').classList.remove('active');
    if (message) setToast(message);
  }

  $('#scale-slider').addEventListener('input', (event) => setScale(event.target.value));
  $('#fit-button').addEventListener('click', () => setScale(100));
  $('#reset-scale-button').addEventListener('click', () => setScale(100));
  $('#crop-button').addEventListener('click', () => {
    cropMode = !cropMode;
    $('#stage').classList.toggle('cropping', cropMode);
    $('#crop-button').classList.toggle('active', cropMode);
    setToast(cropMode ? 'Drag over the image to crop. Press Escape to cancel.' : 'Crop selection cancelled.');
  });

  $('#stage').addEventListener('pointerdown', (event) => {
    const state = getState();
    if (!state?.has_image) return;
    if (cropMode || event.ctrlKey) {
      cropStart = { x: event.clientX, y: event.clientY };
      $('#crop-box').hidden = false;
      const stageRect = $('#stage').getBoundingClientRect();
      Object.assign($('#crop-box').style, {
        left: `${cropStart.x - stageRect.left}px`,
        top: `${cropStart.y - stageRect.top}px`,
        width: '0px',
        height: '0px',
      });
      event.preventDefault();
    } else if (event.shiftKey) {
      const pan = getPan();
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
      Object.assign($('#crop-box').style, {
        left: `${left}px`, top: `${top}px`,
        width: `${Math.max(0, right - left)}px`, height: `${Math.max(0, bottom - top)}px`,
      });
    } else if (dragStart) {
      const stage = $('#stage');
      const state = getState();
      const image = state?.kind === 'video' ? videoPlayer : $('#preview-image');
      const maxX = Math.max(0, (image.clientWidth - stage.clientWidth) / 2);
      const maxY = Math.max(0, (image.clientHeight - stage.clientHeight) / 2);
      setPan({
        x: Math.max(-maxX, Math.min(maxX, dragStart.panX + event.clientX - dragStart.x)),
        y: Math.max(-maxY, Math.min(maxY, dragStart.panY + event.clientY - dragStart.y)),
      });
      applyPreview(state);
    }
  });

  window.addEventListener('pointerup', async (event) => {
    if (cropStart) {
      const start = cropStart;
      cropStart = null;
      const state = getState();
      const displayedImage = state?.kind === 'video' ? videoPlayer : $('#preview-image');
      const imageRect = displayedImage.getBoundingClientRect();
      const left = Math.max(0, Math.min(start.x, event.clientX) - imageRect.left) / imageRect.width;
      const top = Math.max(0, Math.min(start.y, event.clientY) - imageRect.top) / imageRect.height;
      const right = Math.min(imageRect.width, Math.max(start.x, event.clientX) - imageRect.left) / imageRect.width;
      const bottom = Math.min(imageRect.height, Math.max(start.y, event.clientY) - imageRect.top) / imageRect.height;
      stopCropMode();
      if (right > left && bottom > top) {
        await pauseCurrentVideoForHistoryChange();
        const position = state?.kind === 'video'
          ? state.video?.realtime_running
            ? state.video.realtime_position
            : videoPlayer.currentTime
          : undefined;
        await runAction('crop_image', [left, top, right, bottom], position);
      }
    }
    dragStart = null;
  });

  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      cropStart = null;
      stopCropMode();
    }
  });

  $('#stage').addEventListener('wheel', (event) => {
    const state = getState();
    if (!event.shiftKey || !state?.has_image) return;
    event.preventDefault();
    const current = state.kind === 'video' && getVideoNativeSize()
      ? 100
      : Number(state.scale || 1) * 100;
    const next = Math.max(10, Math.min(500, current + (event.deltaY < 0 ? 15 : -15)));
    if (state.kind === 'video') $('#video-zoom').value = next;
    else $('#scale-slider').value = next;
    setScale(next, { x: event.clientX, y: event.clientY });
  }, { passive: false });

  window.addEventListener('resize', () => {
    const state = getState();
    if (state) applyPreview(state);
  });
}
