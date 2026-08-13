import { afterEach, expect, it, vi } from "vitest";
import {
  archiveExperiment,
  createExperiment,
  deleteExperiment,
  loadExperiments,
  updateExperiment,
} from "./experiments-api";

afterEach(() => vi.restoreAllMocks());

it("loads non-archived experiments by default", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => [] }));
  vi.stubGlobal("fetch", fetchMock);
  await loadExperiments();
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/experiments?include_archived=false");
});

it("archives through the explicit archive route", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ archived_at: "now" }) }));
  vi.stubGlobal("fetch", fetchMock);
  await archiveExperiment("exp-1");
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/experiments/exp-1/archive");
});

it("creates and edits experiments through JSON resource routes", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ id: "exp-1" }) }));
  vi.stubGlobal("fetch", fetchMock);

  await createExperiment({ name: "Study", description: null });
  await updateExperiment("exp/1", { name: "Updated", description: "Protocol" });

  expect(fetchMock.mock.calls[0]).toEqual([
    "/api/v1/experiments",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ name: "Study", description: null }) }),
  ]);
  expect(fetchMock.mock.calls[1]).toEqual([
    "/api/v1/experiments/exp%2F1",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ name: "Updated", description: "Protocol" }) }),
  ]);
});

it("deletes experiments through the encoded resource route", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => null }));
  vi.stubGlobal("fetch", fetchMock);

  await deleteExperiment("exp/1");

  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/experiments/exp%2F1");
  expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "DELETE" }));
});
