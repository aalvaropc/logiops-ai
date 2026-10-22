export function createStartup({
  attempt, delays = [2000, 5000, 10000], retryable = () => true,
  wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  onFailure = () => {}, onSuccess = () => {},
} = {}) {
  let turn = 0;
  let failed = false;

  async function start() {
    const mine = ++turn;
    for (let index = 0; ; index += 1) {
      try {
        await attempt();
      } catch (error) {
        if (mine !== turn) return false;
        failed = true;
        const retryIn = retryable(error) ? delays[index] ?? null : null;
        onFailure(error, { retryIn });
        if (retryIn === null) return false;
        await wait(retryIn);
        if (mine !== turn) return false;
        continue;
      }
      if (mine !== turn) return false;
      const recovered = failed;
      failed = false;
      onSuccess(recovered);
      return true;
    }
  }

  return { start };
}
