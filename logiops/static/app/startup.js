export function createStartup({
  attempt, delays = [2000, 5000, 10000], retryable = () => true,
  wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  onFailure = () => {}, onSuccess = () => {},
} = {}) {
  let turn = 0;
  let failed = false;
  let attempting = false;

  async function start() {
    if (attempting) return false;
    const mine = ++turn;
    for (let index = 0; ; index += 1) {
      let error = null;
      attempting = true;
      try {
        await attempt();
      } catch (caught) {
        error = caught ?? new Error("The attempt failed");
      } finally {
        attempting = false;
      }
      if (mine !== turn) return false;
      if (error) {
        failed = true;
        const retryIn = retryable(error) ? delays[index] ?? null : null;
        onFailure(error, { retryIn });
        if (retryIn === null) return false;
        await wait(retryIn);
        if (mine !== turn) return false;
        continue;
      }
      const recovered = failed;
      failed = false;
      onSuccess(recovered);
      return true;
    }
  }

  return { start };
}
