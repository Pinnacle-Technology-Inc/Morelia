import { loadDeviceScan, startDeviceScan } from "./devices-api";

function pause(milliseconds, signal) {
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const timer = setTimeout(finish, milliseconds);
    signal.addEventListener("abort", finish, { once: true });
    if (signal.aborted) finish();
  });
}

// Stopping a viewer never cancels the server's hardware cleanup.
export function createDeviceScanController({
  onUpdate, onError, start = startDeviceScan, poll = loadDeviceScan, intervalMs = 250,
}) {
  let generation = 0;
  let request = null;
  let disposed = false;

  function stop() {
    generation += 1;
    request?.abort();
    request = null;
  }

  async function refresh() {
    if (disposed) return;
    stop();
    const current = generation;
    const controller = new AbortController();
    request = controller;
    const { signal } = controller;
    try {
      let snapshot = await start({ signal });
      const scanId = snapshot.scanId;
      if (!scanId) throw new Error("The device scan returned no scan ID.");
      let revision = -1;
      while (current === generation && !signal.aborted) {
        if (snapshot.scanId !== scanId) throw new Error("The device scan returned a different scan ID.");
        if (snapshot.revision > revision) {
          revision = snapshot.revision;
          onUpdate(snapshot);
          if (snapshot.scanState === "complete" || snapshot.scanState === "failed") return snapshot;
        }
        await pause(intervalMs, signal);
        if (current !== generation || signal.aborted) return;
        snapshot = await poll(scanId, { signal });
      }
    } catch (error) {
      if (current === generation && !signal.aborted) onError(error);
    } finally {
      if (current === generation) request = null;
    }
  }

  function dispose() {
    disposed = true;
    stop();
  }

  return { refresh, stop, dispose };
}
