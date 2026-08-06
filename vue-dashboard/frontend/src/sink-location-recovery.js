const RECOVERABLE_SINK_CODES = new Set([
  "sink_location_exists",
  "sink_parent_unavailable",
]);

export function isRecoverableSinkProblem(error) {
  return RECOVERABLE_SINK_CODES.has(error?.problem?.code);
}

export function hasOccupiedSink(plan) {
  return Array.isArray(plan?.sinks) && plan.sinks.some((sink) => sink?.occupied === true);
}

export function hasUnreadySink(plan) {
  return Array.isArray(plan?.sinks) && plan.sinks.some((sink) => Boolean(sink?.parent_issue));
}

export async function validateOutputFolders(folders, browse) {
  if (typeof browse !== "function") throw new TypeError("A host folder validator is required.");
  const distinctFolders = [...new Set(
    (folders ?? []).map((folder) => String(folder ?? "").trim()).filter(Boolean),
  )];

  for (const folder of distinctFolders) {
    let listing;
    try {
      listing = await browse(folder);
    } catch {
      throw new Error(`The output folder “${folder}” could not be resolved on the session host. Choose another folder.`);
    }
    if (!listing?.exists) {
      throw new Error(`The output folder “${folder}” does not exist on the session host. Choose an existing folder.`);
    }
    if (!listing?.writable) {
      throw new Error(`The output folder “${folder}” is not writable on the session host. Choose another folder.`);
    }
  }
}

export function suggestedSinkLocation(sink) {
  const current = String(sink?.current_location ?? "").trim();
  const suggested = String(sink?.suggested_location ?? "").trim();
  const sinkType = String(sink?.sink_type ?? "").trim().toLowerCase();
  if (!sink?.occupied || sink?.parent_issue || !current || !suggested || suggested === current) return "";
  if (!sinkType || !suggested.toLowerCase().endsWith(`.${sinkType}`)) return "";
  // A collision suggestion is only a filename change. Crossing directories
  // would bypass the host-parent validation that made the plan trustworthy.
  const comparableFolder = (location) => {
    const folder = outputFolder(location).replace(/\\/g, "/").replace(/\/+$/, "");
    return /^[A-Za-z]:/.test(folder) ? folder.toLowerCase() : folder;
  };
  if (comparableFolder(suggested) !== comparableFolder(current)) return "";
  return suggested;
}

export function buildSinkLocationUpdates(sinks) {
  if (!Array.isArray(sinks) || sinks.length === 0) {
    throw new TypeError("At least one output path is required.");
  }
  return sinks.map((sink) => {
    const sinkLocation = String(sink?.edited_location ?? "").trim();
    if (!sinkLocation) throw new TypeError("An output path is required for every file sink.");
    return {
      flow_index: sink.flow_index,
      sink_index: sink.sink_index,
      sink_location: sinkLocation,
    };
  });
}

export function moveOutputToFolder(location, folder) {
  const rawFolder = String(folder ?? "").trim();
  const filename = String(location ?? "").trim().split(/[\\/]/).pop();
  if (!rawFolder || !filename) return String(location ?? "");
  const separator = rawFolder.includes("\\") ? "\\" : "/";
  let cleanFolder = rawFolder.replace(/[\\/]+$/, "");
  if (!cleanFolder && rawFolder.startsWith("/")) cleanFolder = "/";
  if (/^[A-Za-z]:[\\/]*$/.test(rawFolder)) cleanFolder = `${rawFolder.slice(0, 2)}${separator}`;
  const joiner = cleanFolder.endsWith(separator) ? "" : separator;
  return `${cleanFolder}${joiner}${filename}`;
}

export function outputFolder(location) {
  const value = String(location ?? "").trim();
  const separatorIndex = Math.max(value.lastIndexOf("/"), value.lastIndexOf("\\"));
  if (separatorIndex < 0) return "";
  if (separatorIndex === 0) return value[0];
  if (separatorIndex === 2 && /^[A-Za-z]:[\\/]/.test(value)) return value.slice(0, 3);
  return value.slice(0, separatorIndex);
}
