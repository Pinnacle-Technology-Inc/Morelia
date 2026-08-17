<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ArrowUpRight, ChevronDown, ChevronRight, GripVertical } from "@lucide/vue";
import BaseCard from "./BaseCard.vue";
import SessionFlowBar from "./SessionFlowBar.vue";
import StatusBadge from "./StatusBadge.vue";
import { loadSessionDetail } from "../session-detail-api";
import { normalizeSession } from "../session-api";
import { deriveStreamRows, isOutboxUnproven } from "../session-flow-status";
import { timestampMs } from "../datetime";

const props = defineProps({
  session: { type: Object, required: true },
  devices: { type: Array, default: () => [] },
  expanded: Boolean,
});

const emit = defineEmits(["drag-start", "drag-end", "move", "open", "toggle"]);

const detail = ref(null);
const detailState = ref("loading");
const detailError = ref("");
const now = ref(Date.now());
let detailPollTimer = null;
let durationTimer = null;

const displaySession = computed(() => {
  if (!detail.value?.session) return props.session;
  return normalizeSession(detail.value.session, {
    health: detail.value.health,
    phase: detail.value.phase,
  });
});

const streamRows = computed(() =>
  deriveStreamRows({
    devices: detail.value?.latest_report?.devices ?? [],
    sinks: detail.value?.sinks ?? [],
    configuredFlows: detail.value?.session?.device_flows ?? props.session.deviceFlows ?? [],
    unproven: isOutboxUnproven(detail.value?.outbox_health),
  }),
);

const detailAvailable = computed(() => detailState.value !== "unavailable");
const activityState = computed(() => {
  if (detailState.value === "unavailable") return "unavailable";
  if (detailState.value === "loading") return "connecting";
  return "live";
});

const actualDuration = computed(() => {
  const startTimes = (detail.value?.runtimes ?? [])
    .map((runtime) => timestampMs(runtime.started_at))
    .filter((timestamp) => timestamp !== null);
  if (!startTimes.length) return "—";

  const elapsedSeconds = Math.max(0, Math.floor((now.value - Math.min(...startTimes)) / 1000));
  const hours = Math.floor(elapsedSeconds / 3600);
  const minutes = Math.floor((elapsedSeconds % 3600) / 60);
  const seconds = elapsedSeconds % 60;
  return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(seconds).padStart(2, "0")}s`;
});

async function refreshDetail() {
  try {
    detail.value = await loadSessionDetail(props.session.id);
    detailState.value = "live";
    detailError.value = "";
  } catch (error) {
    detailState.value = "unavailable";
    detailError.value = error instanceof Error ? error.message : "Session detail is unavailable.";
  }
}

function moveWithKeyboard(sessionId, event) {
  if (["ArrowLeft", "ArrowUp"].includes(event.key)) {
    event.preventDefault();
    emit("move", sessionId, -1);
  }
  if (["ArrowRight", "ArrowDown"].includes(event.key)) {
    event.preventDefault();
    emit("move", sessionId, 1);
  }
}

onMounted(() => {
  refreshDetail();
  detailPollTimer = setInterval(refreshDetail, 5000);
  durationTimer = setInterval(() => {
    now.value = Date.now();
  }, 1000);
});

onUnmounted(() => {
  if (detailPollTimer) clearInterval(detailPollTimer);
  if (durationTimer) clearInterval(durationTimer);
});
</script>

<template>
  <BaseCard class="active-session-card">
    <article class="session-card">
      <header class="session-card__head">
        <div>
          <h3>{{ displaySession.name }}</h3>
          <p>{{ displaySession.experiment }}</p>
        </div>
        <div class="session-card__controls">
          <button
            class="session-drag-handle"
            type="button"
            draggable="true"
            :aria-label="`Reorder ${displaySession.name}. Use arrow keys or drag.`"
            @dragstart="$emit('drag-start', displaySession.id, $event)"
            @dragend="$emit('drag-end')"
            @keydown="moveWithKeyboard(displaySession.id, $event)"
          >
            <GripVertical :size="18" />
          </button>
          <button
            class="session-disclosure"
            type="button"
            :aria-expanded="expanded"
            :aria-controls="`session-streams-${displaySession.id}`"
            :aria-label="`${expanded ? 'Collapse' : 'Expand'} streams for ${displaySession.name}`"
            @click="$emit('toggle', displaySession.id)"
          >
            <ChevronDown v-if="expanded" :size="20" />
            <ChevronRight v-else :size="20" />
          </button>
        </div>
      </header>

      <div class="badge-row">
        <StatusBadge :value="displaySession.lifecycle" />
        <StatusBadge :value="displaySession.health" />
      </div>

      <dl class="session-stats">
        <div><dt>Duration</dt><dd>{{ actualDuration }}</dd></div>
        <div><dt>Streams / Sinks</dt><dd>{{ displaySession.streamCount ?? displaySession.deviceCount }} / {{ displaySession.sinkCount }}</dd></div>
     
      </dl>

      <section
        v-show="expanded"
        :id="`session-streams-${displaySession.id}`"
        class="session-devices"
        :aria-label="`Streams in ${displaySession.name}`"
      >
        <div class="session-devices__heading">
          <strong>Stream Health</strong>
          <span>{{ displaySession.streamCount ?? displaySession.deviceCount }} stream{{ (displaySession.streamCount ?? displaySession.deviceCount) === 1 ? "" : "s" }}</span>
        </div>
        <SessionFlowBar
          :lifecycle="displaySession.lifecycle"
          :health="displaySession.health"
          :phase="displaySession.phase"
          :activity-state="activityState"
          :streams="streamRows"
          :detail-available="detailAvailable"
          :detail-error="detailError"
          :outbox-health="detail?.outbox_health ?? null"
          :last-report-at="detail?.latest_report?.received_at ?? null"
        />
      </section>

      <footer class="session-card__footer">
        <button class="session-open-action" type="button" @click="$emit('open', displaySession.id)">
          Open session <ArrowUpRight :size="15" />
        </button>
      </footer>
    </article>
  </BaseCard>
</template>
