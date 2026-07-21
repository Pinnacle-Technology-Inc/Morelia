import { describe, expect, it } from "vitest";
import { resolveSidebarDragAction, resolveSidebarKeyAction } from "./sidebar-splitter-utils";

describe("overview sidebar splitter", () => {
  it("treats small pointer movement as a click", () => {
    expect(resolveSidebarDragAction(false, 100, 104)).toBe("toggle");
  });

  it("collapses an expanded sidebar when dragged right", () => {
    expect(resolveSidebarDragAction(false, 100, 132)).toBe("collapse");
  });

  it("keeps an expanded sidebar open when dragged left", () => {
    expect(resolveSidebarDragAction(false, 100, 70)).toBe("none");
  });

  it("expands a collapsed sidebar when dragged left", () => {
    expect(resolveSidebarDragAction(true, 100, 68)).toBe("expand");
  });

  it("keeps a collapsed sidebar closed when dragged right", () => {
    expect(resolveSidebarDragAction(true, 100, 132)).toBe("none");
  });

  it("uses horizontal arrow keys for the desktop vertical separator", () => {
    expect(resolveSidebarKeyAction("ArrowRight", false)).toBe("collapse");
    expect(resolveSidebarKeyAction("ArrowLeft", false)).toBe("expand");
  });

  it("uses vertical arrow keys when the separator stacks horizontally", () => {
    expect(resolveSidebarKeyAction("ArrowDown", true)).toBe("collapse");
    expect(resolveSidebarKeyAction("ArrowUp", true)).toBe("expand");
  });

  it("toggles from Enter or Space in either orientation", () => {
    expect(resolveSidebarKeyAction("Enter", false)).toBe("toggle");
    expect(resolveSidebarKeyAction(" ", true)).toBe("toggle");
  });
});
