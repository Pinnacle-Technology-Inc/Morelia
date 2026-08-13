const PROBLEM_MESSAGES = {
  experiment_archived: "Archived experiments are read-only.",
  experiment_has_sessions: "This experiment has linked sessions and cannot be permanently deleted.",
  experiment_name_conflict: "An experiment with this name already exists.",
  experiment_not_found: "This experiment no longer exists. Refresh the list and try again.",
};

export function filterExperiments(experiments, search) {
  const query = String(search ?? "").trim().toLocaleLowerCase();
  if (!query) return experiments;
  return experiments.filter((experiment) =>
    [experiment.name, experiment.description]
      .filter(Boolean)
      .some((value) => String(value).toLocaleLowerCase().includes(query)),
  );
}

export function summarizeExperiments(experiments) {
  const archived = experiments.filter((experiment) => Boolean(experiment.archived_at)).length;
  return {
    active: experiments.length - archived,
    archived,
    total: experiments.length,
  };
}

export function experimentErrorMessage(error, fallback = "Experiments are unavailable.") {
  const problemCode = error?.problem?.code;
  if (problemCode && PROBLEM_MESSAGES[problemCode]) return PROBLEM_MESSAGES[problemCode];
  return error instanceof Error && error.message ? error.message : fallback;
}
