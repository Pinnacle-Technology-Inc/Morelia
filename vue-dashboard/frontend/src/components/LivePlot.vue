<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { RefreshCw, Wifi, WifiOff } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import StatusBadge from "./StatusBadge.vue";
import {
  PlotConnectionState,
  createPlotSubscription,
} from "../plot-stream";

const props = defineProps({
  sessionId: { type: [String, Number], required: true },
  sinkId: { type: String, required: true },
  sinkName: { type: String, default: "" },
  sinkHealth: { type: String, default: "Unknown" },
  token: { type: [String, Function], default: null },
  apiBase: { type: String, default: () => import.meta.env.VITE_API_BASE_URL ?? "" },
  autoStart: { type: Boolean, default: true },
  height: { type: Number, default: 180 },
});

const connectionState = ref(PlotConnectionState.IDLE);
const samples = ref([]);
const channels = ref([]);
const dropped = ref(0);
const lastSeq = ref(-1);
const errorMessage = ref(null);
const sampleRate = ref(null);

let subscription = null;

const stateLabel = computed(() => {
  switch (connectionState.value) {
    case PlotConnectionState.CONNECTING:
      return "Connecting";
    case PlotConnectionState.LIVE:
      return "Live";
    case PlotConnectionState.RECONNECTING:
      return "Reconnecting";
    case PlotConnectionState.STALE:
      return "Stale";
    case PlotConnectionState.DEGRADED:
      return "Degraded";
    case PlotConnectionState.DROPPED:
      return "Dropped samples";
    case PlotConnectionState.UNAUTHORIZED:
      return "Unauthorized";
    case PlotConnectionState.STOPPED:
      return "Stopped";
    case PlotConnectionState.ERROR:
      return "Error";
    default:
      return "Idle";
  }
});

const stateTone = computed(() => {
  switch (connectionState.value) {
    case PlotConnectionState.LIVE:
      return "ok";
    case PlotConnectionState.CONNECTING:
    case PlotConnectionState.RECONNECTING:
      return "pending";
    case PlotConnectionState.DROPPED:
    case PlotConnectionState.DEGRADED:
    case PlotConnectionState.STALE:
      return "warn";
    case PlotConnectionState.UNAUTHORIZED:
    case PlotConnectionState.ERROR:
      return "bad";
    default:
      return "muted";
  }
});

const channelSeries = computed(() => {
  const names = channels.value.length
    ? channels.value
    : samples.value[0]?.map((_, index) => `ch${index}`) ?? [];
  return names.map((name, channelIndex) => ({
    name,
    values: samples.value.map((row) => Number(row[channelIndex] ?? 0)),
  }));
});

const chartModel = computed(() => {
  const series = channelSeries.value;
  const width = 640;
  const height = props.height;
  const padX = 8;
  const padY = 12;
  const allValues = series.flatMap((entry) => entry.values);
  const min = allValues.length ? Math.min(...allValues) : 0;
  const max = allValues.length ? Math.max(...allValues) : 1;
  const span = max - min || 1;
  const count = series[0]?.values.length ?? 0;

  const paths = series.map((entry, seriesIndex) => {
    if (!entry.values.length) return { name: entry.name, d: "", tone: seriesIndex };
    const d = entry.values
      .map((value, index) => {
        const x = padX + (count <= 1 ? 0 : (index / (count - 1)) * (width - padX * 2));
        const y = height - padY - ((value - min) / span) * (height - padY * 2);
        return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(" ");
    return { name: entry.name, d, tone: seriesIndex % 4 };
  });

  return {
    width,
    height,
    min,
    max,
    paths,
    empty: count === 0,
  };
});

function applySnapshot(snap) {
  connectionState.value = snap.state;
  samples.value = snap.samples;
  channels.value = snap.channels ?? [];
  dropped.value = snap.dropped ?? 0;
  lastSeq.value = snap.lastSeq ?? -1;
  errorMessage.value = snap.error;
  sampleRate.value = snap.lastBatch?.sample_rate ?? sampleRate.value;
}

function resolveToken() {
  if (typeof props.token === "function") return props.token;
  if (props.token) return props.token;
  // Backend mint endpoint is not yet exposed over HTTP; surface unauthorized
  // until a token is provided by the host (status/session API or env).
  const envToken = import.meta.env.VITE_PLOT_STREAM_TOKEN;
  if (envToken) return envToken;
  return async () => {
    throw new Error("No plot subscription token available");
  };
}

function startSubscription() {
  stopSubscription();
  subscription = createPlotSubscription({
    sessionId: props.sessionId,
    sinkId: props.sinkId,
    token: resolveToken(),
    apiBase: props.apiBase,
    onChange: applySnapshot,
  });
  if (props.autoStart) subscription.start();
}

function stopSubscription() {
  if (subscription) {
    subscription.disconnect();
    subscription = null;
  }
}

function reconnect() {
  if (!subscription) {
    startSubscription();
    return;
  }
  subscription.reconnect();
}

watch(
  () => [props.sessionId, props.sinkId, props.token],
  () => {
    if (!subscription) {
      startSubscription();
      return;
    }
    subscription.retarget({
      sessionId: props.sessionId,
      sinkId: props.sinkId,
      token: resolveToken(),
    });
  },
);

startSubscription();

onBeforeUnmount(() => {
  stopSubscription();
});
</script>

<template>
  <section
    class="live-plot"
    :data-state="connectionState"
    :aria-label="`Live plot for ${sinkName || sinkId}`"
  >
    <header class="live-plot__header">
      <div class="live-plot__identity">
        <h4>{{ sinkName || sinkId }}</h4>
        <code>{{ sinkId }}</code>
      </div>
      <div class="live-plot__badges">
        <StatusBadge compact :value="sinkHealth" />
        <span
          class="live-plot__state"
          :class="`live-plot__state--${stateTone}`"
          role="status"
          :aria-live="connectionState === 'live' ? 'off' : 'polite'"
        >
          <Wifi
            v-if="connectionState === 'live' || connectionState === 'dropped'"
            :size="14"
            aria-hidden="true"
          />
          <WifiOff
            v-else-if="connectionState === 'unauthorized' || connectionState === 'error' || connectionState === 'stopped'"
            :size="14"
            aria-hidden="true"
          />
          <RefreshCw v-else :size="14" aria-hidden="true" />
          {{ stateLabel }}
        </span>
      </div>
    </header>

    <div class="live-plot__meta">
      <span>Cursor <code>{{ lastSeq < 0 ? "—" : lastSeq }}</code></span>
      <span>Points <code>{{ samples.length }}</code></span>
      <span>Dropped <code>{{ dropped }}</code></span>
      <span v-if="sampleRate">Rate <code>{{ sampleRate }}/s</code></span>
    </div>

    <div class="live-plot__canvas" role="img" :aria-label="chartModel.empty ? 'Waiting for plot samples' : `Plot of ${channels.join(', ') || 'channels'}`">
      <svg
        v-if="!chartModel.empty"
        :viewBox="`0 0 ${chartModel.width} ${chartModel.height}`"
        preserveAspectRatio="none"
      >
        <path
          v-for="path in chartModel.paths"
          :key="path.name"
          class="live-plot__trace"
          :class="`live-plot__trace--${path.tone}`"
          :d="path.d"
          fill="none"
        />
      </svg>
      <p v-else class="live-plot__empty">
        {{
          connectionState === "connecting" || connectionState === "reconnecting"
            ? "Connecting to live plot…"
            : connectionState === "unauthorized"
              ? "Unauthorized for this session/sink."
              : connectionState === "stopped"
                ? "Plot stream stopped."
                : "No plot samples yet."
        }}
      </p>
    </div>

    <div class="live-plot__channels" v-if="channelSeries.length">
      <span v-for="channel in channelSeries" :key="channel.name">{{ channel.name }}</span>
    </div>

    <p v-if="errorMessage" class="live-plot__error">{{ errorMessage }}</p>

    <div class="live-plot__actions">
      <BaseButton
        v-if="['stale', 'error', 'unauthorized', 'stopped', 'degraded'].includes(connectionState)"
        variant="secondary"
        size="small"
        @click="reconnect"
      >
        <RefreshCw :size="14" /> Reconnect
      </BaseButton>
      <p class="live-plot__hint">
        Source health stays separate — this panel only reflects plot presentation state.
      </p>
    </div>
  </section>
</template>

<style scoped>
.live-plot {
  display: grid;
  gap: 0.65rem;
  padding: 0.85rem;
  border: 1px solid var(--border-card, #dde7e0);
  border-radius: var(--radius-md, 10px);
  background: var(--surface-card, #fff);
}

.live-plot__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}

.live-plot__identity {
  display: grid;
  gap: 0.15rem;
  min-width: 0;
}

.live-plot__identity h4 {
  margin: 0;
  font-size: 0.85rem;
}

.live-plot__identity code,
.live-plot__meta code {
  color: var(--text-muted, #6f6f6f);
}

.live-plot__badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.4rem;
}

.live-plot__state {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 700;
}

.live-plot__state--ok {
  color: var(--success, #0a7249);
  background: rgba(10, 114, 73, 0.1);
}

.live-plot__state--pending {
  color: var(--info, #2f6f8f);
  background: rgba(47, 111, 143, 0.12);
}

.live-plot__state--warn {
  color: #735d32;
  background: #faf5e9;
}

.live-plot__state--bad {
  color: var(--error, #b23a32);
  background: rgba(178, 58, 50, 0.1);
}

.live-plot__state--muted {
  color: var(--text-muted, #6f6f6f);
  background: var(--surface-sage, #ebf2ef);
}

.live-plot__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.85rem;
  color: var(--text-muted, #6f6f6f);
  font-size: 0.7rem;
}

.live-plot__canvas {
  min-height: v-bind(height + "px");
  border: 1px solid var(--border-card, #dde7e0);
  border-radius: 8px;
  background:
    linear-gradient(to right, rgba(7, 64, 38, 0.04) 1px, transparent 1px) 0 0 / 32px 32px,
    linear-gradient(to bottom, rgba(7, 64, 38, 0.04) 1px, transparent 1px) 0 0 / 32px 32px,
    var(--sage-50, #f3f7f4);
  overflow: hidden;
}

.live-plot__canvas svg {
  display: block;
  width: 100%;
  height: v-bind(height + "px");
}

.live-plot__trace {
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}

.live-plot__trace--0 { stroke: var(--green-700, #0a7249); }
.live-plot__trace--1 { stroke: var(--info, #2f6f8f); }
.live-plot__trace--2 { stroke: var(--warning, #b9852b); }
.live-plot__trace--3 { stroke: #6b4f8a; }

.live-plot__empty {
  display: grid;
  place-items: center;
  min-height: v-bind(height + "px");
  margin: 0;
  padding: 1rem;
  color: var(--text-muted, #6f6f6f);
  font-size: 0.78rem;
  text-align: center;
}

.live-plot__channels {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}

.live-plot__channels span {
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
  background: var(--surface-sage, #ebf2ef);
  color: var(--text-heading, #141414);
  font-size: 0.68rem;
  font-weight: 700;
}

.live-plot__error {
  margin: 0;
  color: var(--error, #b23a32);
  font-size: 0.75rem;
}

.live-plot__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
}

.live-plot__hint {
  margin: 0;
  color: var(--text-muted, #6f6f6f);
  font-size: 0.68rem;
}
</style>
