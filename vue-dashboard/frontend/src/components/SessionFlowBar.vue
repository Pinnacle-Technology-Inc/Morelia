<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { deriveFlowStatus, formatReportAge } from "../session-flow-status";

const props = defineProps({
  lifecycle: { type: String, default: "Unknown" },
  health: { type: String, default: "Unknown" },
  phase: { type: String, default: null },
  activityState: { type: String, default: "idle" },
  detailAvailable: { type: Boolean, default: true },
  // One row per reported device, from deriveStreamRows(). Empty until the
  // runtime has reported at least once.
  streams: { type: Array, default: () => [] },
  // Frozen session configuration used when the runtime has no current rows
  // (completed, scheduled, or not yet reported). This keeps one visible rail
  // per configured source-to-sink path instead of collapsing to one generic bar.
  configuredFlows: { type: Array, default: () => [] },
  lastReportAt: { type: String, default: null },
  outboxHealth: { type: String, default: null },
});

const status = computed(() =>
  deriveFlowStatus({
    lifecycle: props.lifecycle,
    health: props.health,
    phase: props.phase,
    activityState: props.activityState,
    detailAvailable: props.detailAvailable,
    streams: props.streams,
    outboxHealth: props.outboxHealth,
  }),
);

// The rat is no longer rendered here. It is the SESSION-level verdict, so it
// belongs with Session Summary; this component owns the per-stream rail. The
// shared mapping moved to `deriveRatState` in session-flow-status.js so both
// places read the same verdict.

// The report age has to tick on its own. Detail refreshes are throttled, so
// without a local clock the label would freeze at whatever it read on the last
// fetch — and a frozen "2s ago" is precisely the lie this bar is here to stop.
const now = ref(Date.now());
let clock = null;
onMounted(() => {
  clock = setInterval(() => (now.value = Date.now()), 1000);
});
onUnmounted(() => clock && clearInterval(clock));

const reportAge = computed(() => formatReportAge(props.lastReportAt, now.value));

function configuredSourceLabel(flow, index) {
  const nickname = String(flow?.nickname ?? "").trim();
  if (nickname) return nickname;
  return flow?.device_type ?? flow?.deviceType ?? flow?.type ?? `Source ${index + 1}`;
}

function configuredSinkLabel(sink, index) {
  return sink?.sink_name ?? sink?.name ?? sink?.sink_type ?? sink?.type ?? `Sink ${index + 1}`;
}

const fallbackRows = computed(() => {
  const flows = props.configuredFlows.length ? props.configuredFlows : [null];
  return flows.flatMap((flow, sourceIndex) => {
    const sinks = Array.isArray(flow?.sinks) && flow.sinks.length ? flow.sinks : [null];
    return sinks.map((sink, sinkIndex) => ({
      id: `configured-${sourceIndex}-${sinkIndex}`,
      sourceIndex,
      label: flow ? configuredSourceLabel(flow, sourceIndex) : "Data flow",
      hardwareId: flow && !String(flow?.nickname ?? "").trim()
        ? flow?.hardware_id ?? flow?.hardwareId ?? null
        : null,
      tone: status.value.tone,
      flowing: status.value.flowing,
      status: flow
        ? sink
          ? `→ ${configuredSinkLabel(sink, sinkIndex)}`
          : "No sink configured"
        : "Source-to-sink map unavailable",
      reason: null,
      sinkCount: 0,
      fallback: true,
    }));
  });
});

// Configured paths determine the rail count in every lifecycle, while a running
// session layers the source's current runtime status onto each of its sink paths.
// This keeps the footprint stable and preserves useful live health information.
const displayedRows = computed(() => {
  if (props.lifecycle !== "Active" || !props.streams.length) return fallbackRows.value;
  if (!props.configuredFlows.length) return props.streams;

  return fallbackRows.value.map((path) => {
    const stream = props.streams[path.sourceIndex];
    if (!stream) return path;
    return {
      ...path,
      tone: stream.tone,
      flowing: stream.flowing,
      status: `${stream.status} · ${path.status}`,
      reason: stream.reason,
      attempt: stream.attempt,
      fallback: false,
    };
  });
});
const displayedReason = computed(() => {
  let reason = String(status.value.reason ?? "").trim();
  const phaseSentence = props.phase ? `Phase: ${props.phase}.` : "";
  if (phaseSentence && reason.toLowerCase().startsWith(phaseSentence.toLowerCase())) {
    reason = reason.slice(phaseSentence.length).trim();
  }
  const headline = String(status.value.headline ?? "").trim();
  if (!reason || !headline) return reason;
  const prefix = `${headline}.`;
  return reason.toLowerCase().startsWith(prefix.toLowerCase())
    ? reason.slice(prefix.length).trim()
    : reason;
});
</script>

<template>
  <!-- aria-live=polite, not assertive: status changes here are ambient context
       for a spectating operator, not something to interrupt them mid-task. -->
  <section
    class="flow-bar"
    :class="[`flow-bar--${status.tone}`, { 'is-flowing': status.flowing }]"
    role="status"
    aria-live="polite"
  >
    <!-- No lifecycle/health badges here. The page header already renders both,
         about 200px above this line and from the same two variables — two
         "Active" chips and two "Healthy" chips on one screen read as four
         independent facts that happen to agree, which is what made this bar
         look like it was contradicting itself. This bar owns exactly one
         question: is data moving right now. -->
    <header class="flow-bar__head">
      <span class="flow-bar__dot" aria-hidden="true" />
      <strong class="flow-bar__headline">{{ status.headline }}</strong>
      <code v-if="phase" class="flow-bar__phase">{{ phase }}</code>
      <code v-if="reportAge" class="flow-bar__age" :class="{ 'is-unproven': status.unproven }">
        report {{ reportAge }}
      </code>
    </header>

    <!-- The rail gets the full width now that the rat has moved out to Session
         Summary. -->
    <div class="flow-bar__body">
      <ul class="flow-rail">
        <li
          v-for="row in displayedRows"
          :key="row.id"
          class="flow-rail__row"
          :class="[`is-${row.tone}`, { 'flow-rail__row--fallback': row.fallback }]"
        >
          <!-- The hardware id used to be a `title` tooltip only. It is shown
               inline now because this rail replaced the Overview "Stream Health"
               tiles, which printed it — folding those tiles in here must not
               silently drop the one field they carried that the rail did not. -->
          <div class="flow-rail__path">
            <span class="flow-rail__name">
              <span class="flow-rail__label" :title="row.label">{{ row.label }}</span>
              <code v-if="row.hardwareId" class="flow-rail__hardware">{{ row.hardwareId }}</code>
            </span>
            <span
              class="flow-rail__track"
              :class="{ 'is-flowing': row.flowing }"
              role="img"
              :aria-label="`${row.label}: ${row.status}${row.flowing ? ', data transferring' : ', not transferring'}.${row.reason ? ` ${row.reason}.` : ''}`"
            >
              <span class="flow-rail__fill" />
            </span>
          </div>
          <span class="flow-rail__note">
            <span class="flow-rail__status">{{ row.status }}</span>
            <span v-if="row.reason" class="flow-rail__reason">
              {{ row.reason }}<template v-if="row.attempt"> · attempt {{ row.attempt }}</template>
            </span>
            <span v-if="row.sinkCount" class="flow-rail__sink" :class="`is-${row.sinkTone}`">
              {{ row.sinkNote }}
            </span>
          </span>
        </li>
      </ul>
    </div>

    <p v-if="displayedReason" class="flow-bar__reason" :title="status.reason">{{ displayedReason }}</p>

  </section>
</template>

<style scoped>
/* One tone variable drives the dot, the track fill and the left rule, so adding
   a tone means adding one rule rather than touching four selectors. */
/* Renders INSIDE the Overview "Stream Health" panel, which already draws the
   card — so this supplies no border, radius or background of its own; a bordered
   card nested directly in another reads as a rendering mistake. The left tone
   rule stays, because that rule is the status signal, not decoration. */
.flow-bar {
  --tone: var(--text-muted);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  width: 100%;
  padding-left: var(--space-4);
  border-left: 3px solid var(--tone);
  /* The rail relayouts off THIS element's width, not the viewport's: the bar
     sits in a half-width Overview panel on a wide screen, so a media query would
     read the page as roomy and leave the rail squeezed. */
  container: flow-bar / inline-size;
}
.flow-bar--good {
  --tone: var(--success);
}
.flow-bar--warn {
  --tone: var(--warning);
}
.flow-bar--bad {
  --tone: var(--error);
}

.flow-bar__head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  flex-wrap: wrap;
}
.flow-bar__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--tone);
  flex: none;
}
/* Pulse the dot only while something is actually moving. A resting or stalled
   session showing a heartbeat is a lie. */
.flow-bar.is-flowing .flow-bar__dot {
  animation: flow-pulse 1.8s ease-in-out infinite;
}
.flow-bar__headline {
  color: var(--text-heading);
  font-size: var(--fs-md, 1rem);
}
.flow-bar__phase {
  color: var(--text-muted);
  font-size: var(--fs-xs);
}
.flow-bar__age {
  margin-left: auto;
  color: var(--text-muted);
  font-size: var(--fs-xs);
}
.flow-bar__age.is-unproven {
  color: var(--warning);
}

.flow-bar__body {
  display: flex;
  align-items: stretch;
  width: 100%;
  min-height: 1.5rem;
}
.flow-bar__body > .flow-rail {
  flex: 1 1 auto;
  min-width: 0;
}

/* --- the rail ---------------------------------------------------------- */

.flow-rail {
  display: flex;
  flex-direction: column;
  width: 100%;
  margin: 0;
  padding: 0;
  list-style: none;
}
.flow-rail__row {
  --row-tone: var(--text-muted);
  display: grid;
  grid-template-columns: minmax(0, 4fr) minmax(8rem, 1.5fr);
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  min-height: calc(var(--space-5) * 2);
  padding: var(--space-2) 0;
}
.flow-rail__row + .flow-rail__row {
  border-top: 1px solid var(--border-card);
}
.flow-rail__row.is-good {
  --row-tone: var(--success);
}
.flow-rail__row.is-warn {
  --row-tone: var(--warning);
}
.flow-rail__row.is-bad {
  --row-tone: var(--error);
}
.flow-rail__row--fallback {
  --row-tone: var(--tone);
}
.flow-rail__path {
  display: grid;
  grid-template-columns: minmax(7rem, 1fr) minmax(10rem, 3fr);
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.flow-rail__name {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  font-family: var(--font-mono, monospace);
  font-size: var(--fs-xs);
  color: var(--text-body);
}
.flow-rail__label,
.flow-rail__hardware {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.flow-rail__hardware {
  color: var(--text-muted);
  font-size: 0.66rem;
}
.flow-rail__track {
  position: relative;
  height: 8px;
  border-radius: 999px;
  background: var(--surface-sage);
  overflow: hidden;
}
.flow-rail__fill {
  position: absolute;
  inset: 0;
  background: var(--row-tone);
  /* Held tracks stay visible but obviously inert — the colour still reads at a
     glance, the movement does not. */
  opacity: 0.35;
}
.flow-rail__track.is-flowing .flow-rail__fill {
  opacity: 0.85;
  background-image: repeating-linear-gradient(
    115deg,
    transparent 0 10px,
    rgba(255, 255, 255, 0.5) 10px 20px
  );
  background-size: 28px 100%;
  animation: flow-march 900ms linear infinite;
}
.flow-rail__note {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex-wrap: wrap;
  font-size: var(--fs-xs);
  min-width: 0;
}
.flow-rail__reason {
  color: var(--row-tone);
}
.flow-rail__status {
  color: var(--text-muted);
}
.flow-rail__sink {
  color: var(--text-muted);
}
.flow-rail__sink.is-warn {
  color: var(--warning);
}
.flow-rail__sink.is-bad {
  color: var(--error);
}

/* Narrow rail (half-width Overview panel): the reason column drops to its own
   full-width line instead of being crushed. Squeezed into ~140px, copy like
   "Port not connected — waiting for it to return · attempt 2" wraps to five
   lines and the row grows taller than the two-line version costs. */
@container flow-bar (max-width: 26rem) {
  .flow-rail__row {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "path"
      "note";
    row-gap: var(--space-2);
  }
  .flow-rail__path {
    grid-area: path;
    grid-template-columns: minmax(0, 1fr) minmax(3.5rem, 7rem);
  }
  .flow-rail__note {
    grid-area: note;
  }
}

@keyframes flow-march {
  to {
    background-position: 28px 0;
  }
}
@keyframes flow-pulse {
  50% {
    opacity: 0.35;
  }
}
/* Motion here is ambient and runs for the entire length of a session, which is
   exactly the case vestibular-sensitivity settings exist for. Colour and text
   still carry the full signal without it. */
@media (prefers-reduced-motion: reduce) {
  .flow-rail__track.is-flowing .flow-rail__fill,
  .flow-bar__dot {
    animation: none;
  }
}

.flow-bar__reason {
  display: -webkit-box;
  width: 100%;
  height: calc(var(--space-5) * 2);
  overflow: hidden;
  margin: 0;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

</style>
