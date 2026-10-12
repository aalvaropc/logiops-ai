export const DEFAULT_FILLER = "One moment, I'm still working on it.";
export const FILLER_DELAY_MS = 2500;
export const SPEECH_TIMEOUT_MS = 30000;

export function createVoice({ window: win = globalThis.window, fetch: doFetch, getToken = () => "", getConfig = () => ({ engine: "browser", fillers: [] }), isEnabled = () => false, device = () => {} } = {}) {
  const fetcher = (...args) => (doFetch ?? globalThis.fetch)(...args);
  const current = { turn: 0, audio: null, speechTimer: 0, fillerTimer: 0 };

  function synthesis() {
    return "speechSynthesis" in win ? win.speechSynthesis : null;
  }

  function stop({ quiet = false } = {}) {
    current.turn += 1;
    clearTimeout(current.fillerTimer);
    clearTimeout(current.speechTimer);
    let stopped = false;
    if (current.audio) {
      current.audio.pause();
      current.audio = null;
      stopped = true;
    }
    const voices = synthesis();
    if (voices && (voices.speaking || voices.pending)) {
      voices.cancel();
      stopped = true;
    }
    if (stopped && !quiet) device("voice", "speech-end");
  }

  function browserSpeak(line, done) {
    const voices = synthesis();
    if (!voices) {
      done();
      return;
    }
    const utterance = new win.SpeechSynthesisUtterance(line);
    utterance.lang = "en-US";
    utterance.addEventListener("end", done);
    utterance.addEventListener("error", done);
    voices.speak(utterance);
  }

  async function speak(line, { filler = false } = {}) {
    stop({ quiet: true });
    const turn = current.turn;
    const done = () => {
      if (turn !== current.turn) return;
      clearTimeout(current.speechTimer);
      if (!filler) device("voice", "speech-end");
    };
    current.speechTimer = setTimeout(done, SPEECH_TIMEOUT_MS);
    if (getConfig().engine === "polly") {
      try {
        const headers = { "Content-Type": "application/json" };
        const token = getToken();
        if (token) headers.Authorization = `Bearer ${token}`;
        const response = await fetcher("/voice/speech", { method: "POST", headers, body: JSON.stringify({ text: line }), cache: "no-store" });
        if (turn !== current.turn) return "dropped";
        if (response.ok) {
          const url = win.URL.createObjectURL(await response.blob());
          if (turn !== current.turn) {
            win.URL.revokeObjectURL(url);
            return "dropped";
          }
          const audio = new win.Audio(url);
          current.audio = audio;
          const finish = () => {
            win.URL.revokeObjectURL(url);
            if (current.audio === audio) current.audio = null;
            done();
          };
          audio.addEventListener("ended", finish);
          audio.addEventListener("error", finish);
          await audio.play();
          return "polly";
        }
      } catch (_) {
        if (turn !== current.turn) return "dropped";
      }
    }
    browserSpeak(line, done);
    return "browser";
  }

  function startFiller() {
    clearTimeout(current.fillerTimer);
    if (!isEnabled()) return;
    current.fillerTimer = setTimeout(() => {
      const fillers = getConfig().fillers?.length ? getConfig().fillers : [DEFAULT_FILLER];
      speak(fillers[Math.floor(Math.random() * fillers.length)], { filler: true });
    }, FILLER_DELAY_MS);
  }

  function cancelFiller() {
    clearTimeout(current.fillerTimer);
  }

  return { speak, stop, startFiller, cancelFiller, turn: () => current.turn, speaking: () => Boolean(current.audio) };
}
