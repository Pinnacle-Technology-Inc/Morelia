import { requestJson } from "./api-client";

export async function loadSystemHealth() {
  const results = await Promise.allSettled([
    requestJson("/health"),
    requestJson("/ready"),
    requestJson("/api/v1/runtimes/"),
    requestJson("/api/v1/runtimes/restart-report"),
  ]);
  const [health, ready, runtimes, restartReport] = results;
  return {
    health: health.status === "fulfilled" ? health.value : null,
    ready: ready.status === "fulfilled" ? ready.value : null,
    runtimes: runtimes.status === "fulfilled" && Array.isArray(runtimes.value) ? runtimes.value : [],
    restartReport: restartReport.status === "fulfilled" ? restartReport.value : null,
    errors: results.filter((result) => result.status === "rejected").map((result) => result.reason instanceof Error ? result.reason.message : "Endpoint unavailable"),
  };
}

function postLifecycle(path, payload = {}) {
  return requestJson(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export const reconcileRuntimes = () => postLifecycle("/api/v1/runtimes/reconcile");
export const restartControlPlane = () => postLifecycle("/api/v1/runtimes/control-plane-restart", { force: false });
export const shutdownRuntimes = (force = false) => postLifecycle("/api/v1/runtimes/shutdown", { force: Boolean(force) });
export const shutdownControlPlane = (force = false) => postLifecycle("/api/v1/runtimes/control-plane-shutdown", { force: Boolean(force) });
