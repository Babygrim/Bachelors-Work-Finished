const H264_MP4_TYPE = 'video/mp4; codecs="avc1.4D0032"';
const FIRST_FRAME_TIMEOUT_MS = 15000;
const INITIAL_BUFFER_SECONDS = 0.3;

export class RealtimeMsePreview {
  constructor(video, onError, onFirstFrame = () => {}) {
    this.video = video;
    this.onError = onError;
    this.onFirstFrame = onFirstFrame;
    this.identity = '';
    this.generation = 0;
    this.hasFirstFrame = false;
    this.ready = false;
    this.failed = false;
    this.loadedDataHandler = null;
    this.videoErrorHandler = null;
    this.bufferedHandler = null;
    this.firstFrameTimer = null;
    this.mediaSource = null;
    this.objectUrl = null;
    this.abortController = null;
    this.reader = null;
    this.paused = false;
    this.lastRemoved = 0;
    this.receivedBytes = 0;
    this.receivedChunks = 0;
    this.appendedBytes = 0;
    this.appendedChunks = 0;
    video.muted = true;
    video.playsInline = true;
  }

  setSource(url, revision, offset) {
    const identity = url ? `${url}|${revision}|${offset}` : '';
    if (identity === this.identity) return;
    this.stop();
    if (!url) return;
    this.identity = identity;
    if (!window.MediaSource || !MediaSource.isTypeSupported(H264_MP4_TYPE)) {
      this.failed = true;
      this.onError(new Error('This browser does not support AMD H.264 real-time preview.'));
      return;
    }

    this.lastRemoved = 0;
    this.hasFirstFrame = false;
    this.ready = false;
    this.failed = false;
    this.receivedBytes = 0;
    this.receivedChunks = 0;
    this.appendedBytes = 0;
    this.appendedChunks = 0;
    this.abortController = new AbortController();
    const generation = this.generation;
    this.loadedDataHandler = () => {
      if (
        generation !== this.generation
        || !this.identity
        || this.video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA
      ) return;
      this.hasFirstFrame = true;
      this._checkInitialBuffer(generation);
    };
    this.videoErrorHandler = () => {
      if (generation !== this.generation || !this.identity || this.ready) return;
      const mediaError = this.video.error;
      const detail = mediaError
        ? `Browser media error ${mediaError.code}${mediaError.message ? `: ${mediaError.message}` : ''}.`
        : 'Browser media element failed before the initial preview buffer was ready.';
      this._reportFirstFrameFailure(new Error(detail), generation);
    };
    this.bufferedHandler = () => this._checkInitialBuffer(generation);
    this.video.addEventListener('loadeddata', this.loadedDataHandler);
    this.video.addEventListener('error', this.videoErrorHandler);
    this.video.addEventListener('progress', this.bufferedHandler);
    this.video.addEventListener('canplay', this.bufferedHandler);
    this.video.addEventListener('canplaythrough', this.bufferedHandler);
    this.firstFrameTimer = window.setTimeout(() => {
      this._reportFirstFrameFailure(
        new Error('Timed out waiting for the initial H.264 preview buffer.'),
        generation,
      );
    }, FIRST_FRAME_TIMEOUT_MS);
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
    } else if (
      this.ready
      && this.video.paused
      && this.video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA
    ) {
      this.video.play().catch((error) => this.onError(error));
    }
  }

  stop() {
    window.clearTimeout(this.firstFrameTimer);
    this.firstFrameTimer = null;
    if (this.loadedDataHandler) {
      this.video.removeEventListener('loadeddata', this.loadedDataHandler);
      this.loadedDataHandler = null;
    }
    if (this.videoErrorHandler) {
      this.video.removeEventListener('error', this.videoErrorHandler);
      this.videoErrorHandler = null;
    }
    if (this.bufferedHandler) {
      this.video.removeEventListener('progress', this.bufferedHandler);
      this.video.removeEventListener('canplay', this.bufferedHandler);
      this.video.removeEventListener('canplaythrough', this.bufferedHandler);
      this.bufferedHandler = null;
    }
    this.hasFirstFrame = false;
    this.ready = false;
    this.failed = false;
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
        if (done) {
          if (!this.hasFirstFrame && this.receivedBytes === 0) {
            throw new Error('The H.264 preview stream ended before its first decoded frame.');
          }
          break;
        }
        this.receivedBytes += value.byteLength;
        this.receivedChunks += 1;
        await this._append(sourceBuffer, value, signal);
        this.appendedBytes += value.byteLength;
        this.appendedChunks += 1;
        if (!positioned && offset > 0 && sourceBuffer.buffered.length) {
          this.video.currentTime = offset;
          positioned = true;
        }
        this._checkInitialBuffer(generation);
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
        if (
          this.ready
          && !this.paused
          && this.video.paused
          && this.video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA
        ) {
          this.video.play().catch((error) => this.onError(error));
        }
      }
      if (generation === this.generation && mediaSource.readyState === 'open') {
        mediaSource.endOfStream();
        this._checkInitialBuffer(generation);
      }
    } catch (error) {
      if (error.name !== 'AbortError' && generation === this.generation) {
        if (this.ready) {
          this.onError(error);
        } else {
          this._reportFirstFrameFailure(error, generation);
        }
      }
    }
  }

  _checkInitialBuffer(generation) {
    if (
      generation !== this.generation
      || this.ready
      || !this.hasFirstFrame
    ) return;
    let bufferedLead = 0;
    for (let index = 0; index < this.video.buffered.length; index += 1) {
      const start = this.video.buffered.start(index);
      const end = this.video.buffered.end(index);
      const currentTime = this.video.currentTime;
      if (currentTime >= start - 0.05 && currentTime <= end + 0.05) {
        bufferedLead = Math.max(0, end - Math.max(start, currentTime));
        break;
      }
    }
    if (
      bufferedLead < INITIAL_BUFFER_SECONDS
      && this.video.readyState < HTMLMediaElement.HAVE_ENOUGH_DATA
      && this.mediaSource?.readyState !== 'ended'
    ) return;
    this.ready = true;
    this.failed = false;
    window.clearTimeout(this.firstFrameTimer);
    this.firstFrameTimer = null;
    if (this.loadedDataHandler) {
      this.video.removeEventListener('loadeddata', this.loadedDataHandler);
      this.loadedDataHandler = null;
    }
    this.onFirstFrame();
  }

  _reportFirstFrameFailure(error, generation) {
    if (generation !== this.generation || this.failed || this.ready) return;
    this.failed = true;
    window.clearTimeout(this.firstFrameTimer);
    this.firstFrameTimer = null;
    this.onError(new Error(
      `${error.message} `
      + `Received ${this.receivedBytes} bytes in ${this.receivedChunks} chunks; `
      + `appended ${this.appendedBytes} bytes in ${this.appendedChunks} chunks. `
      + `Media readyState=${this.video.readyState}, networkState=${this.video.networkState}.`,
    ));
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
