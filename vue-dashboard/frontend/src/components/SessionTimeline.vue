<script setup>
import { computed, ref } from "vue";
import BaseButton from "./BaseButton.vue";
import { recentTimelineEntries, TimelineCategory } from "../session-timeline";

const props = defineProps({
  entries: { type: Array, default: () => [] },
  variant: { type: String, default: "full" },
  state: { type: String, default: "idle" },
  error: { type: [String, Object], default: null },
});

defineEmits(["view-all"]);

const filter = ref("all");
const categoryLabels = Object.freeze({
  [TimelineCategory.DATAFLOW]: "Dataflow",
  [TimelineCategory.RECOVERY]: "Recovery",
  [TimelineCategory.SUPERVISION]: "Supervision",
  [TimelineCategory.OPERATIONS]: "Session",
});
const categories = Object.entries(categoryLabels).map(([value, label]) => ({ value, label }));

const preview = computed(() => props.variant === "preview");
const displayedEntries = computed(() => {
  if (preview.value) return recentTimelineEntries(props.entries);
  if (filter.value === "all") return props.entries;
  return props.entries.filter((entry) => entry.category === filter.value);
});
const streamWarning = computed(() => ["stale", "unavailable"].includes(props.state));
const emptyMessage = computed(() => {
  if (props.state === "connecting" || props.state === "reconnecting") {
    return "Waiting for the activity stream. Durable session history will appear here when available.";
  }
  if (filter.value !== "all") return `No ${categoryLabels[filter.value]?.toLowerCase()} events recorded.`;
  return "No activity has been recorded yet.";
});

function parsedTimestamp(value) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatDate(value) {
  const parsed = parsedTimestamp(value);
  return parsed
    ? parsed.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
    : String(value || "Time unavailable");
}

function formatTime(value) {
  const parsed = parsedTimestamp(value);
  return parsed
    ? parsed.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" })
    : "";
}

function technicalDetails(details) {
  try {
    return JSON.stringify(details ?? {}, null, 2);
  } catch {
    return "Technical details are unavailable.";
  }
}
</script>

<template>
  <section class="timeline" :class="{ 'timeline--preview': preview }" aria-labelledby="session-timeline-title">
    <header class="timeline__header">
      <div>
        <h3 v-if="preview" id="session-timeline-title">Recent activity</h3>
        <h2 v-else id="session-timeline-title">Activity</h2>
      </div>
      <BaseButton v-if="preview" variant="quiet" size="small" @click="$emit('view-all')">
        View all activity
      </BaseButton>
      <label v-else class="timeline__filter">
        <span>Show</span>
        <select v-model="filter">
          <option value="all">All activity</option>
          <option v-for="category in categories" :key="category.value" :value="category.value">
            {{ category.label }}
          </option>
        </select>
      </label>
    </header>

    <p v-if="streamWarning" class="timeline__warning" role="status">
      Live activity is {{ state }}. Durable records and the last proven runtime events are still shown.
      <span v-if="error">{{ error?.message ?? error }}</span>
    </p>

    <ol v-if="displayedEntries.length" class="timeline__list">
      <li v-for="entry in displayedEntries" :key="entry.key" class="timeline__entry" :class="`is-${entry.tone}`">
        <span class="timeline__marker" aria-hidden="true" />
        <div class="timeline__content">
          <div class="timeline__headline">
            <span class="timeline__category" :class="`is-${entry.category}`">
              {{ categoryLabels[entry.category] ?? "Activity" }}
            </span>
            <strong>{{ entry.title }}</strong>
            <span class="timeline__summary">{{ entry.summary }}</span>
          </div>
          <details v-if="!preview && entry.details" class="timeline__details">
            <summary>Technical details</summary>
            <pre>{{ technicalDetails(entry.details) }}</pre>
          </details>
        </div>
        <template v-if="entry.at">
          <time class="timeline__time" :datetime="entry.at">{{ formatTime(entry.at) }}</time>
          <time class="timeline__date" :datetime="entry.at">{{ formatDate(entry.at) }}</time>
        </template>
        <template v-else>
          <span class="timeline__time" aria-hidden="true" />
          <span class="timeline__date">Time unavailable</span>
        </template>
      </li>
    </ol>
    <p v-else class="timeline__empty" role="status">{{ emptyMessage }}</p>
  </section>
</template>

<style scoped>
.timeline {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--surface-sage);
}

.timeline--preview {
  padding: 0;
  background: transparent;
}

.timeline__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.timeline__header h2,
.timeline__header h3 {
  margin: 0;
  color: var(--text-heading);
  font: var(--fw-bold) var(--fs-lg)/var(--lh-heading) var(--font-display);
  letter-spacing: var(--ls-tight);
}

.timeline__filter {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.timeline__filter select {
  min-height: 2rem;
  padding-inline: var(--space-3);
  color: var(--text-body);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--surface-card);
}

.timeline__warning,
.timeline__empty {
  margin: 0;
  padding: var(--space-3);
  color: var(--text-muted);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--surface-card);
}

.timeline__warning {
  color: var(--warning);
}

.timeline__list {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.timeline__entry {
  --timeline-tone: var(--text-muted);
  display: grid;
  grid-template-columns: var(--space-3) minmax(0, 1fr) max-content max-content;
  gap: var(--space-3);
  min-width: 0;
  border-bottom: 1px solid var(--border-card);
}

.timeline__entry.is-good { --timeline-tone: var(--success); }
.timeline__entry.is-warn { --timeline-tone: var(--warning); }
.timeline__entry.is-bad { --timeline-tone: var(--error); }

.timeline__marker {
  width: var(--space-3);
  height: var(--space-3);
  margin-top: var(--space-4);
  border: 2px solid var(--surface-card);
  border-radius: var(--radius-pill);
  background: var(--timeline-tone);
  box-shadow: 0 0 0 1px var(--timeline-tone);
}

.timeline__content {
  min-width: 0;
  padding: var(--space-3) 0 var(--space-4);
}

.timeline__entry:last-child {
  border-bottom: 0;
}

.timeline__time,
.timeline__date {
  align-self: start;
  padding-top: var(--space-3);
  color: var(--text-muted);
  font: var(--fw-regular) var(--fs-xs)/var(--space-4) var(--font-mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.timeline__time {
  color: var(--text-body);
  font-weight: var(--fw-medium);
  text-align: right;
}

.timeline__headline {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: nowrap;
  min-height: var(--space-4);
  line-height: var(--lh-snug);
}

.timeline__headline strong {
  color: var(--text-heading);
  font-family: var(--font-display);
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  letter-spacing: var(--ls-tight);
  white-space: nowrap;
}

.timeline__summary {
  min-width: 0;
  overflow: hidden;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.timeline__summary::before {
  content: "— ";
  color: var(--border-card);
}

.timeline__category {
  flex: 0 0 auto;
  padding: var(--space-1) var(--space-2);
  color: var(--text-accent);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-pill);
  background: var(--surface-card);
  font: var(--fw-bold) var(--fs-xs)/1 var(--font-display);
  letter-spacing: var(--ls-wide);
  text-transform: uppercase;
}

.timeline__category.is-recovery { color: var(--yellow-800); }
.timeline__category.is-supervision { color: var(--info); }
.timeline__category.is-operations { color: var(--text-body); }

.timeline__details {
  margin-top: var(--space-2);
  color: var(--text-muted);
  font-size: var(--fs-xs);
}

.timeline__details summary {
  cursor: pointer;
  font-weight: var(--fw-bold);
}

.timeline__details pre {
  max-height: 18rem;
  overflow: auto;
  margin-bottom: 0;
  padding: var(--space-3);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-sm);
  background: var(--surface-card);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@media (max-width: 760px) {
  .timeline__header {
    display: grid;
  }

  .timeline__filter {
    align-items: stretch;
    flex-direction: column;
  }

  .timeline__entry {
    grid-template-columns: var(--space-3) minmax(0, 1fr) max-content;
  }

  .timeline__marker {
    grid-row: 1 / span 2;
  }

  .timeline__content {
    grid-column: 2 / -1;
    padding-bottom: var(--space-2);
  }

  .timeline__time,
  .timeline__date {
    grid-row: 2;
    padding-top: 0;
    padding-bottom: var(--space-3);
  }

  .timeline__time {
    grid-column: 2;
    justify-self: end;
  }

  .timeline__date {
    grid-column: 3;
  }
}
</style>
