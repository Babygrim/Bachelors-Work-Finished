const H264_MP4_TYPE = 'video/mp4; codecs="avc1.4D0032"';

export class RealtimeMsePreview {
  constructor(video, onError, onFirstFrame = () => {}) {
    this.video = video;
    this.onError = onError;
    this.onFirstFrame = onFirstFrame;
    this.identity = '';
    this.generation = 0;
    this.hasFirstFrame = false;
    this.loadedDataHandler = null;
    this.mediaSource = null;
    this.objectUrl = null;
    this.abortController = null;
    this.reader = null;
    this.paused = false;
    this.lastRemoved = 0;
    video.muted = true;
    video.playsInline = true;
  }

  setSource(url, revision, offset) {
    const identity = url ? `${url}|${revision}|${offset}` : '';
    if (identity === this.identity) return;
    this.stop();
    if (!url) return;
    if (!window.MediaSource || !MediaSource.isTypeSupported(H264_MP4_TYPE)) {
      this.onError(new Error('This browser does not support AMD H.264 real-time preview.'));
      return;
    }

    this.identity = identity;
    this.lastRemoved = 0;
    this.abortController = new AbortController();
    const generation = this.generation;
    this.hasFirstFrame = false;
    this.loadedDataHandler = () => {
      if (
        generation !== this.generation
        || !this.identity
        || this.video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA
      ) return;
      this.hasFirstFrame = true;
      this.loadedDataHandler = null;
      this.onFirstFrame();
    };
    this.video.addEventListener('loadeddata', this.loadedDataHandler, { once: true });
    const mediaSource = new MediaSource();
    this.mediaSource = mediaSource;
    this.objectUrl = URL.createObjectURL(mediaSource);
    this.video.src = this.objectUrl;
    this.video.load();
    mediaSource.addEventListener('sourceopen', () => {
      if (generation === this.generation) {
        this._consume(url, revision, offset, generation, mediaSource);
      }
    }, { once: true });
  }

  setPaused(paused) {
    this.paused = paused;
    if (paused) {
      this.video.pause();
    } else if (this.video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      this.video.play().catch((error) => this.onError(error));
    }
  }

  stop() {
    if (this.loadedDataHandler) {
      this.video.removeEventListener('loadeddata', this.loadedDataHandler);
      this.loadedDataHandler = null;
    }
    this.hasFirstFrame = false;
    if (
      !this.identity
      && !this.abortController
      && !this.objectUrl
      && !this.video.hasAttribute('src')
    ) return;
    this.generation += 1;
    this.identity = '';
    this.abortController?.abort();
    this.reader?.cancel().catch(() => {});
    this.abortController = null;
    this.reader = null;
    this.video.pause();
    this.video.removeAttribute('src');
    this.video.load();
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.objectUrl = null;
    this.mediaSource = null;
  }

  async _consume(url, revision, offset, generation, mediaSource) {
    const signal = this.abortController.signal;
    try {
      const endpoint = new URL(`${url.replace(/\/$/, '')}/mp4`, window.location.href);
      endpoint.searchParams.set('revision', revision);
      const response = await fetch(endpoint, { signal });
      if (!response.ok || !response.body) {
        throw new Error(`Could not open AMD H.264 preview (${response.status}).`);
      }
      const sourceBuffer = mediaSource.addSourceBuffer(H264_MP4_TYPE);
      sourceBuffer.timestampOffset = offset;
      const reader = response.body.getReader();
      this.reader = reader;
      let positioned = false;
      while (generation === this.generation) {
        const { value, done } = await reader.read();
        if (done) break;
        await this._append(sourceBuffer, value, signal);
        if (!positioned && offset > 0 && sourceBuffer.buffered.length) {
          this.video.currentTime = offset;
          positioned = true;
        }
        const currentTime = this.video.currentTime;
        if (
          sourceBuffer.buffered.length
          && currentTime - this.lastRemoved > 40
        ) {
          const removeEnd = currentTime - 30;
          const removeStart = sourceBuffer.buffered.start(0);
          if (removeEnd > removeStart) {
            await this._remove(sourceBuffer, removeStart, removeEnd, signal);
            this.lastRemoved = removeEnd;
          }
        }
        if (!this.paused && this.video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
          this.video.play().catch((error) => this.onError(error));
        }
      }
      if (generation === this.generation && mediaSource.readyState === 'open') {
        mediaSource.endOfStream();
      }
    } catch (error) {
      if (error.name !== 'AbortError' && generation === this.generation) {
        this.onError(error);
      }
    }
  }

  _append(sourceBuffer, data, signal) {
    return this._update(sourceBuffer, signal, () => sourceBuffer.appendBuffer(data));
  }

  _remove(sourceBuffer, start, end, signal) {
    return this._update(sourceBuffer, signal, () => sourceBuffer.remove(start, end));
  }

  _update(sourceBuffer, signal, update) {
    return new Promise((resolve, reject) => {
      const cleanup = () => {
        sourceBuffer.removeEventListener('updateend', onEnd);
        sourceBuffer.removeEventListener('error', onError);
        signal.removeEventListener('abort', onAbort);
      };
      const onEnd = () => {
        cleanup();
        resolve();
      };
      const onError = () => {
        cleanup();
        reject(new Error('Could not append AMD H.264 preview data.'));
      };
      const onAbort = () => {
        cleanup();
        reject(new DOMException('The preview stream was stopped.', 'AbortError'));
      };
      sourceBuffer.addEventListener('updateend', onEnd, { once: true });
      sourceBuffer.addEventListener('error', onError, { once: true });
      signal.addEventListener('abort', onAbort, { once: true });
      try {
        update();
      } catch (error) {
        cleanup();
        reject(error);
      }
    });
  }
}
