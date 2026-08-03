import { afterEach, expect, it, vi } from "vitest";
import { browseDirectories, browseRoots, createDirectory } from "./filesystem-api";

afterEach(() => vi.restoreAllMocks());

const listing = { path: "cortical", parent: "", directories: [], writable: true, exists: true };

function stubOk(body) {
  const fetchMock = vi.fn(() => Promise.resolve({ ok: true, json: async () => body }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

it("omits the query string entirely so the host picks its default start folder", async () => {
  const fetchMock = stubOk(listing);

  await browseDirectories("");

  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/filesystem/directories");
});

it("encodes a Windows absolute path so the backslashes and colon survive", async () => {
  const fetchMock = stubOk(listing);

  await browseDirectories("C:\\data\\cortical array");

  expect(fetchMock.mock.calls[0][0]).toBe(
    "/api/v1/filesystem/directories?path=C%3A%5Cdata%5Ccortical%20array",
  );
});

it("requests the host's filesystem roots", async () => {
  const fetchMock = stubOk({ roots: [{ name: "C:", path: "C:\\" }] });

  await expect(browseRoots()).resolves.toEqual({ roots: [{ name: "C:", path: "C:\\" }] });
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/filesystem/roots");
});

it("posts the parent path and new folder name as JSON", async () => {
  const fetchMock = stubOk(listing);

  await createDirectory("cortical", "run-08");

  const [url, options] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/v1/filesystem/directories");
  expect(options.method).toBe("POST");
  expect(JSON.parse(options.body)).toEqual({ path: "cortical", name: "run-08" });
});

it("sends an empty parent path rather than null when creating at the root", async () => {
  const fetchMock = stubOk(listing);

  await createDirectory(null, "cortical");

  expect(JSON.parse(fetchMock.mock.calls[0][1].body).path).toBe("");
});

it("surfaces the API problem detail when a folder cannot be read", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 403,
        json: async () => ({ detail: "That folder cannot be read." }),
      }),
    ),
  );

  await expect(browseDirectories("C:\\System Volume Information")).rejects.toThrow(
    "cannot be read",
  );
});
