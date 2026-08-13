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
  [TimelineCategory.OPERATIONS]: "Operations",
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
  return "No meaningful timeline events have been recorded yet.";
});

function formatTimestamp(value) {
  if (!value) return "Time unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
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
        <h2 v-else id="session-timeline-title">Timeline</h2>
        <p>{{ preview ? "Latest meaningful changes in this run." : "Dataflow, recovery, supervision, and command history in one place." }}</p>
      </div>
      <BaseButton v-if="preview" variant="quiet" size="small" @click="$emit('view-all')">
        View full timeline
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
          <div class="timeline__meta">
            <time v-if="entry.at" :datetime="entry.at">{{ formatTimestamp(entry.at) }}</time>
            <span v-else>Time unavailable</span>
            <span class="timeline__category">{{ categoryLabels[entry.category] ?? "Activity" }}</span>
          </div>
          <strong>{{ entry.title }}</strong>
          <p>{{ entry.summary }}</p>
          <details v-if="!preview && entry.details" class="timeline__details">
            <summary>Technical details</summary>
            <pre>{{ technicalDetails(entry.details) }}</pre>
          </details>
        </div>
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
.timeline__header h3,
.timeline__header p {
  margin: 0;
}

.timeline__header p {
  margin-top: var(--space-1);
  color: var(--text-muted);
  font-size: var(--fs-sm);
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
  grid-template-columns: var(--space-3) minmax(0, 1fr);
  gap: var(--space-3);
  min-width: 0;
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
  border-bottom: 1px solid var(--border-card);
}

.timeline__entry:last-child .timeline__content {
  border-bottom: 0;
}

.timeline__content > strong {
  display: block;
  margin-top: var(--space-1);
  color: var(--text-heading);
}

.timeline__content > p {
  margin: var(--space-1) 0 0;
  color: var(--text-body);
  overflow-wrap: anywhere;
}

.timeline__meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  color: var(--text-muted);
  font-size: var(--fs-xs);
}

.timeline__category {
  padding: 0 var(--space-2);
  border-radius: var(--radius-pill);
  background: var(--surface-card);
  font-weight: var(--fw-bold);
}

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
}
</style>
