const DRAG_THRESHOLD = 8;

export function resolveSidebarDragAction(collapsed, startX, endX) {
  const distance = endX - startX;
  if (Math.abs(distance) < DRAG_THRESHOLD) return "toggle";
  if (!collapsed && distance > 0) return "collapse";
  if (collapsed && distance < 0) return "expand";
  return "none";
}

export function resolveSidebarKeyAction(key, stacked) {
  if (["Enter", " "].includes(key)) return "toggle";
  if (!stacked && key === "ArrowRight") return "collapse";
  if (!stacked && key === "ArrowLeft") return "expand";
  if (stacked && key === "ArrowDown") return "collapse";
  if (stacked && key === "ArrowUp") return "expand";
  return "none";
}
