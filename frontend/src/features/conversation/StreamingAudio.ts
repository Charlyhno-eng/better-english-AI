import { replyAudioBlob, type VoiceTurn } from './api.ts';

/** Schedule decoded WAV fragments on one clock, without gaps at chunk boundaries. */
export class StreamingAudio {
  private context: AudioContext;
  private next = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private pending = Promise.resolve();
  private stopped = false;
  private onPlaybackChange: (playing: boolean) => void;

  constructor(onPlaybackChange: (playing: boolean) => void = () => {}) {
    // Created during the recording button gesture so autoplay can be unlocked.
    this.context = new AudioContext();
    this.onPlaybackChange = onPlaybackChange;
    void this.context.resume().catch(() => {});
  }

  append(audio: NonNullable<VoiceTurn['audio']>) {
    this.pending = this.pending.then(async () => {
      if (this.stopped) return;
      const buffer = await this.context.decodeAudioData(await replyAudioBlob(audio).arrayBuffer());
      if (this.stopped) return;
      if (this.context.state !== 'running') await this.context.resume();
      if (this.stopped || this.context.state !== 'running') return;
      const source = this.context.createBufferSource();
      source.buffer = buffer;
      source.connect(this.context.destination);
      source.onended = () => {
        this.sources.delete(source); source.disconnect();
        if (!this.sources.size) this.onPlaybackChange(false);
      };
      this.sources.add(source);
      const when = Math.max(this.next, this.context.currentTime + .08);
      source.start(when);
      this.next = when + buffer.duration;
      this.onPlaybackChange(true);
    }).catch(() => { /* The complete reply still has a normal replay control. */ });
  }

  stop() {
    if (this.stopped) return;
    this.stopped = true;
    for (const source of this.sources) { source.stop(); source.disconnect(); }
    this.sources.clear();
    this.onPlaybackChange(false);
    void this.context.close().catch(() => {});
  }
}
