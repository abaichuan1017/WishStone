import test from 'node:test';
import assert from 'node:assert/strict';
import {HoldRecorder} from '../app/static/recorder.js';

function setup(getMedia) {
  let stopped = 0, time = 0;
  const stream = {getTracks: () => [{stop: () => stopped++}]};
  class Recorder {
    static isTypeSupported() { return true; }
    constructor(s) { this.stream = s; this.mimeType = 'audio/webm'; }
    start() { this.ondataavailable({data: new Blob(['audio'])}); }
    stop() { queueMicrotask(() => this.onstop()); }
  }
  const states = [], audio = [], errors = [];
  const recorder = new HoldRecorder({Recorder, getMedia: getMedia || (() => Promise.resolve(stream)), now: () => time, onState: s => states.push(s), onAudio: a => audio.push(a), onError: e => errors.push(e)});
  return {recorder, stream, states, audio, errors, setTime: v => {time = v}, stopped: () => stopped};
}

test('release while microphone permission is pending never starts capture', async () => {
  let grant;
  const s = setup(() => new Promise(resolve => {grant = resolve}));
  const start = s.recorder.start(); s.recorder.stop(); grant(s.stream); await start;
  assert.equal(s.recorder.phase, 'idle'); assert.equal(s.stopped(), 1); assert.equal(s.audio.length, 0);
});
test('hold and release submits exactly one recording', async () => {
  const s = setup(); await s.recorder.start(); s.setTime(900); s.recorder.stop(); s.recorder.stop();
  await Promise.resolve(); assert.equal(s.audio.length, 1); assert.equal(s.audio[0].type, 'audio/webm'); assert.equal(s.recorder.phase, 'idle');
});
test('pointer cancel or window blur discards the current recording', async () => {
  const s = setup(); await s.recorder.start(); s.setTime(900); s.recorder.cancel(); await Promise.resolve();
  assert.equal(s.audio.length, 0); assert.equal(s.errors.length, 0); assert.equal(s.recorder.phase, 'idle');
});
test('too-short press gives an actionable error', async () => {
  const s = setup(); await s.recorder.start(); s.setTime(100); s.recorder.stop(); await Promise.resolve();
  assert.equal(s.audio.length, 0); assert.equal(s.errors.length, 1);
});
test('permission denial returns to idle without capture', async () => {
  const s = setup(() => Promise.reject(Object.assign(new Error('denied'), {name:'NotAllowedError'})));
  await s.recorder.start(); assert.equal(s.recorder.phase, 'idle'); assert.match(s.errors[0].message, /麦克风未获授权/);
});
