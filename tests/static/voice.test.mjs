import { test, mock, afterEach } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { createVoice, FILLER_DELAY_MS, DEFAULT_FILLER } = await import(moduleUrl("app/voice.js"));

function fakeWindow({ synthesis = true } = {}) {
  const spoken = [];
  const audios = [];
  const urls = { created: 0, revoked: 0 };
  class Utterance {
    constructor(text) { this.text = text; this.listeners = {}; }
    addEventListener(name, fn) { this.listeners[name] = fn; }
  }
  class Audio {
    constructor(url) { this.url = url; this.listeners = {}; this.paused = false; this.played = false; audios.push(this); }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    async play() { this.played = true; }
    pause() { this.paused = true; }
  }
  const win = {
    SpeechSynthesisUtterance: Utterance, Audio,
    URL: { createObjectURL: () => `blob:${++urls.created}`, revokeObjectURL: () => { urls.revoked += 1; } },
    spoken, audios, urls,
  };
  if (synthesis) {
    win.speechSynthesis = { speaking: false, pending: false, cancelled: 0, speak(u) { spoken.push(u); this.speaking = true; }, cancel() { this.cancelled += 1; this.speaking = false; } };
  }
  return win;
}

const created = [];
afterEach(() => { for (const voice of created.splice(0)) voice.stop({ quiet: true }); });

function setup({ engine = "browser", fetch, synthesis = true, enabled = true } = {}) {
  const win = fakeWindow({ synthesis });
  const events = [];
  const voice = createVoice({
    window: win, fetch, getToken: () => "tok", getConfig: () => ({ engine, voice: "Ruth", fillers: ["Still working."] }),
    isEnabled: () => enabled, device: (method, phase) => events.push(`${method}:${phase}`),
  });
  created.push(voice);
  return { win, voice, events };
}

test("the browser voice reads the line and reports the end to the device", async () => {
  const { win, voice, events } = setup();
  assert.equal(await voice.speak("Hello there."), "browser");
  assert.equal(win.spoken[0].text, "Hello there.");
  assert.equal(win.spoken[0].lang, "en-US");
  win.spoken[0].listeners.end();
  assert.deepEqual(events, ["voice:speech-end"]);
  const silent = setup({ synthesis: false });
  assert.equal(await silent.voice.speak("x"), "browser");
  assert.deepEqual(silent.events, ["voice:speech-end"], "without speechSynthesis the reply ends at once");
});

test("Polly audio is fetched with the token and played; a 503 falls back to the browser", async () => {
  const calls = [];
  const fetchPolly = async (url, init) => { calls.push({ url, init }); return { ok: true, blob: async () => new Blob(["mp3"]) }; };
  const { win, voice, events } = setup({ engine: "polly", fetch: fetchPolly });
  assert.equal(await voice.speak("Approved."), "polly");
  assert.equal(calls[0].url, "/voice/speech");
  assert.equal(calls[0].init.headers.Authorization, "Bearer tok");
  assert.equal(JSON.parse(calls[0].init.body).text, "Approved.");
  assert.equal(win.audios[0].played, true);
  assert.equal(voice.speaking(), true);
  win.audios[0].listeners.ended();
  assert.deepEqual(events, ["voice:speech-end"]);
  assert.equal(win.urls.revoked, 1);
  const fallback = setup({ engine: "polly", fetch: async () => ({ ok: false, status: 503 }) });
  assert.equal(await fallback.voice.speak("Hi."), "browser");
  assert.equal(fallback.win.spoken.length, 1);
  const broken = setup({ engine: "polly", fetch: async () => { throw new TypeError("offline"); } });
  assert.equal(await broken.voice.speak("Hi."), "browser");
});

test("talking over the voice stops it, and audio that arrives late is dropped", async () => {
  let release;
  let pending = true;
  const fetchPolly = () => (pending ? new Promise((resolve) => { release = resolve; }) : Promise.resolve({ ok: true, blob: async () => new Blob(["mp3"]) }));
  const { win, voice, events } = setup({ engine: "polly", fetch: fetchPolly });
  const speaking = voice.speak("Long answer.");
  const turn = voice.turn();
  voice.stop();
  assert.equal(voice.turn(), turn + 1);
  release({ ok: true, blob: async () => new Blob(["mp3"]) });
  assert.equal(await speaking, "dropped");
  assert.equal(win.audios.length, 0);
  pending = false;
  assert.equal(await voice.speak("Second."), "polly");
  assert.equal(win.audios.length, 1);
  voice.stop();
  assert.equal(win.audios[0].paused, true);
  assert.deepEqual(events, ["voice:speech-end"]);
  const first = setup();
  await first.voice.speak("A.");
  first.voice.stop();
  assert.equal(first.win.speechSynthesis.cancelled, 1);
  assert.deepEqual(first.events, ["voice:speech-end"]);
  first.voice.stop({ quiet: true });
  assert.deepEqual(first.events, ["voice:speech-end"], "a quiet stop with nothing playing says nothing");
});

test("a filler is spoken after 2.5 seconds of thinking unless it is cancelled", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { win, voice } = setup();
    voice.startFiller();
    mock.timers.tick(FILLER_DELAY_MS - 1);
    assert.equal(win.spoken.length, 0);
    mock.timers.tick(1);
    assert.equal(win.spoken[0].text, "Still working.");
    const cancelled = setup();
    cancelled.voice.startFiller();
    cancelled.voice.cancelFiller();
    mock.timers.tick(FILLER_DELAY_MS);
    assert.equal(cancelled.win.spoken.length, 0);
    const off = setup({ enabled: false });
    off.voice.startFiller();
    mock.timers.tick(FILLER_DELAY_MS);
    assert.equal(off.win.spoken.length, 0);
    assert.equal(DEFAULT_FILLER, "One moment, I'm still working on it.");
  } finally {
    mock.timers.reset();
  }
});

test("booking numbers are spelled for the voice only", async () => {
  const { spokenForm } = await import(moduleUrl("app/voice.js"));
  assert.equal(spokenForm("Your confirmation number is LGO-ABC234."), "Your confirmation number is L G O A B C 2 3 4.");
  assert.equal(spokenForm("SHIP-433 costs $390."), "SHIP-433 costs $390.");
  const { win, voice } = setup();
  await voice.speak("Booked LGO-7KQ2MD.");
  assert.equal(win.spoken[0].text, "Booked L G O 7 K Q 2 M D.");
});
