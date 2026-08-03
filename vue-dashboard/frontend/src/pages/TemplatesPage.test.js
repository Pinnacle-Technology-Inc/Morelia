import { describe, expect, it } from "vitest";

describe("template read path", () => {
  it("does not fabricate unsupported schema counts", () => {
    expect({ content_hash: "abc" }.sessionsUsing).toBeUndefined();
  });
});
