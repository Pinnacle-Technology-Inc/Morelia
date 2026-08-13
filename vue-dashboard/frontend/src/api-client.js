const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export function apiUrl(path) {
  return `${API_BASE_URL}${path}`;
}

export class ApiProblem extends Error {
  constructor(problem) {
    super(problem.detail || problem.message || problem.title || "API request failed");
    this.name = "ApiProblem";
    this.problem = problem;
  }
}

export async function requestJson(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.headers ?? {}),
    },
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiProblem(body ?? { status: response.status, detail: response.statusText });
  }
  return body;
}
