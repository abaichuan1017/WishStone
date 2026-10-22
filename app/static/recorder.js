// A single press/release controller shared by pointer and keyboard input.
export class HoldRecorder {
  constructor({onState, onAudio, onError, getMedia = () => navigator.mediaDevices.getUserMedia({audio: true}), Recorder = globalThis.MediaRecorder, now = () => performance.now(), maxMs = 60000}) {
    Object.assign(this, {onState, onAudio, onError, getMedia, Recorder, now, maxMs});
    this.phase = "idle"; this.epoch = 0; this.holding = false;
  }
  state(phase) { this.phase = phase; this.onState(phase); }
  async start() {
    if (this.phase !== "idle") return;
    const epoch = ++this.epoch;
    this.holding = true; this.discard = false;
    this.state("requesting");
    let stream;
    try {
      if (!this.Recorder) throw new Error("当前浏览器不支持录音，请写下心愿。");
      stream = await this.getMedia();
      if (epoch !== this.epoch || !this.holding) { stream.getTracks().forEach(t => t.stop()); return; }
      const mimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"].find(type => this.Recorder.isTypeSupported(type));
      const recorder = new this.Recorder(stream, mimeType ? {mimeType} : undefined);
      this.recorder = recorder; this.chunks = []; this.startedAt = this.now();
      recorder.ondataavailable = e => { if (e.data.size) this.chunks.push(e.data); };
      recorder.onstop = () => {
        clearTimeout(this.limit); stream.getTracks().forEach(t => t.stop());
        const elapsed = this.now() - this.startedAt;
        const blob = new Blob(this.chunks, {type: recorder.mimeType || "audio/webm"});
        this.recorder = null; this.state("idle");
        if (this.discard) return;
        if (elapsed < 300 || !blob.size) { this.onError(new Error("录音太短，请按住按钮再说一次。")); return; }
        this.onAudio(blob);
      };
      recorder.onerror = () => { this.cancel(); this.onError(new Error("录音中断，请重新尝试。")); };
      recorder.start(); this.state("recording");
      this.limit = setTimeout(() => this.stop(), this.maxMs);
    } catch (error) {
      stream?.getTracks().forEach(t => t.stop());
      if (epoch !== this.epoch) return;
      this.holding = false; this.state("idle");
      this.onError(new Error(error.name === "NotAllowedError" ? "麦克风未获授权。允许访问后可以重试，也可以写下心愿。" : error.message || "无法访问麦克风。"));
    }
  }
  stop(discard = false) {
    this.holding = false;
    if (this.phase === "requesting") { ++this.epoch; this.state("idle"); return; }
    if (this.phase === "stopping" && discard) this.discard = true;
    if (this.phase !== "recording") return;
    this.discard = discard; clearTimeout(this.limit); this.state("stopping");
    this.recorder.stop(); this.recorder.stream.getTracks().forEach(t => t.stop());
  }
  cancel() { this.stop(true); }
}
