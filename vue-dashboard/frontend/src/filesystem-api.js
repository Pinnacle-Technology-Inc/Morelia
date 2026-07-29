import { requestJson } from "./api-client";

// Folder browsing for the sink-location picker. Paths are ABSOLUTE on the host
// running the backend — the same machine that opens the sink file — so what the
// picker returns is exactly what sink_location stores and the runtime writes to.
// An omitted path starts at that host's configured OUTPUT_DIR.

export async function browseDirectories(path = "") {
  const query = path ? `?path=${encodeURIComponent(path)}` : "";
  return requestJson(`/api/v1/filesystem/directories${query}`);
}

// Drive letters on Windows, "/" on POSIX. Used when navigating above a root,
// where there is nothing left to go "up" to.
export async function browseRoots() {
  return requestJson("/api/v1/filesystem/roots");
}

export async function createDirectory(path, name) {
  return requestJson("/api/v1/filesystem/directories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: path ?? "", name }),
  });
}
