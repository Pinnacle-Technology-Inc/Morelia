<script setup>
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "@lucide/vue";
import { onBeforeUnmount, onMounted, ref } from "vue";
import {
  resolveSidebarDragAction,
  resolveSidebarKeyAction,
} from "../sidebar-splitter-utils";

const props = defineProps({ collapsed: Boolean });
const emit = defineEmits(["update:collapsed"]);

const dragging = ref(false);
const stacked = ref(false);
let pointerId = null;
let pointerStartX = 0;
let stackedMediaQuery = null;

function toggle() {
  emit("update:collapsed", !props.collapsed);
}

function handleKeydown(event) {
  const action = resolveSidebarKeyAction(event.key, stacked.value);
  if (action === "none") return;

  event.preventDefault();
  if (action === "toggle") toggle();
  if (action === "collapse") emit("update:collapsed", true);
  if (action === "expand") emit("update:collapsed", false);
}

function startPointerDrag(event) {
  if (event.pointerType === "mouse" && event.button !== 0) return;
  pointerId = event.pointerId;
  pointerStartX = event.clientX;
  dragging.value = true;
  try {
    event.currentTarget.setPointerCapture(pointerId);
  } catch {
    // Synthetic pointer events may not create an active pointer to capture.
  }
}

function applyPointerAction(event) {
  const action = stacked.value
    ? "toggle"
    : resolveSidebarDragAction(props.collapsed, pointerStartX, event.clientX);

  if (action === "toggle") toggle();
  if (action === "collapse") emit("update:collapsed", true);
  if (action === "expand") emit("update:collapsed", false);
}

function finishPointerDrag(event) {
  if (!dragging.value || event.pointerId !== pointerId) return;

  applyPointerAction(event);

  dragging.value = false;
  pointerId = null;
}

function cancelPointerDrag(event) {
  if (event.pointerId !== pointerId) return;
  dragging.value = false;
  pointerId = null;
}

function updateStackedState(event) {
  stacked.value = event.matches;
}

onMounted(() => {
  stackedMediaQuery = window.matchMedia("(max-width: 1180px)");
  stacked.value = stackedMediaQuery.matches;
  stackedMediaQuery.addEventListener("change", updateStackedState);
});

onBeforeUnmount(() => {
  stackedMediaQuery?.removeEventListener("change", updateStackedState);
});
</script>

<template>
  <div
    class="overview-splitter"
    :class="{ 'overview-splitter--dragging': dragging }"
    role="separator"
    :aria-orientation="stacked ? 'horizontal' : 'vertical'"
    :aria-valuenow="collapsed ? 0 : 1"
    aria-valuemin="0"
    aria-valuemax="1"
    :aria-valuetext="collapsed ? 'Supporting panels collapsed' : 'Supporting panels expanded'"
    :aria-label="collapsed ? 'Expand supporting panels' : 'Collapse supporting panels'"
    aria-controls="overview-supporting-panels"
    tabindex="0"
    @keydown="handleKeydown"
    @pointerdown.prevent="startPointerDrag"
    @pointerup.prevent="finishPointerDrag"
    @pointercancel="cancelPointerDrag"
  >
    <span class="overview-splitter__line" aria-hidden="true" />
    <span class="overview-splitter__handle" aria-hidden="true">
      <ChevronRight v-if="!collapsed" class="overview-splitter__desktop-icon" :size="15" />
      <ChevronLeft v-else class="overview-splitter__desktop-icon" :size="15" />
      <ChevronUp v-if="!collapsed" class="overview-splitter__stacked-icon" :size="15" />
      <ChevronDown v-else class="overview-splitter__stacked-icon" :size="15" />
    </span>
  </div>
</template>
