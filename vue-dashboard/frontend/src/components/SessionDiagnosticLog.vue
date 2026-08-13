<script setup>
import { computed, onMounted, ref } from "vue";
import { Download, RefreshCw } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import {
  loadSessionDiagnostics,
  sessionDiagnosticsExportUrl,
} from "../session-diagnostics-api";

const props = defineProps({
  sessionId: { type: [String, Number], required: true },
});

const records = ref([]);
const state = ref("loading");
const error = ref("");
const layer = ref("all");
const query = ref("");

const layers = computed(() => [...new Set(records.value.map((row) => row.layer).filter(Boolean))].sort());
const visible = computed(() => {
  const needle = query.value.trim().toLowerCase();
  return records.value.filter((record) => {
    if (layer.value !== "all" && record.layer !== layer.value) return false;
    return !needle || JSON.stringify(record).toLowerCase().includes(needle);
  });
});
const exportUrl = computed(() => sessionDiagnosticsExportUrl(props.sessionId));

async function refresh() {
  state.value = "loading";
  error.value = "";
  try {
    const page = await loadSessionDiagnostics(props.sessionId);
    records.value = page.items ?? [];
    state.value = "live";
  } catch (failure) {
    state.value = "unavailable";
    error.value = failure instanceof Error ? failure.message : "Diagnostic logs are unavailable.";
  }
}

function formatRecord(record) {
  return JSON.stringify(record, null, 2);
}

function formatTimestamp(value) {
  if (!value) return "Time unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

onMounted(refresh);
</script>

<template>
  <section class="diagnostics" aria-labelledby="diagnostic-log-title">
    <header class="diagnostics__header">
      <div>
        <h2 id="diagnostic-log-title">Diagnostic logs</h2>
        <p>Redacted, session-scoped confirmations from the control plane, runtime host, and watchdog driver.</p>
      </div>
      <div class="diagnostics__actions">
        <BaseButton variant="secondary" size="small" :disabled="state === 'loading'" @click="refresh">
          <RefreshCw :size="15" /> Refresh
        </BaseButton>
        <a class="diagnostics__download" :href="exportUrl" download>
          <Download :size="15" /> Download TXT
        </a>
      </div>
    </header>

    <div class="diagnostics__filters">
      <label>
        <span>Layer</span>
        <select v-model="layer">
          <option value="all">All layers</option>
          <option v-for="value in layers" :key="value" :value="value">{{ value }}</option>
        </select>
      </label>
      <label class="diagnostics__search">
        <span>Find in loaded logs</span>
        <input v-model="query" type="search" placeholder="operation id, error, event…" />
      </label>
    </div>

    <p v-if="state === 'loading'" class="diagnostics__notice">Loading diagnostic logs…</p>
    <p v-else-if="state === 'unavailable'" class="diagnostics__notice is-error" role="alert">{{ error }}</p>
    <p v-else-if="!visible.length" class="diagnostics__notice">
      {{ records.length ? "No loaded records match these filters." : "No diagnostic records have been written for this session yet." }}
    </p>
    <ol v-else class="diagnostics__list">
      <li v-for="(record, index) in visible" :key="`${record.layer}:${record.timestamp}:${index}`">
        <div class="diagnostics__line">
          <span class="diagnostics__layer">{{ record.layer ?? "unknown" }}</span>
          <time>{{ formatTimestamp(record.timestamp) }}</time>
          <strong>{{ record.event ?? "diagnostic_record" }}</strong>
          <span :class="`is-${record.level ?? 'info'}`">{{ record.level ?? "info" }}</span>
        </div>
        <pre>{{ formatRecord(record) }}</pre>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.diagnostics { display: grid; gap: var(--space-4); padding: var(--space-4); background: var(--surface-sage); }
.diagnostics__header, .diagnostics__actions, .diagnostics__filters, .diagnostics__line { display: flex; align-items: center; gap: var(--space-3); }
.diagnostics__header { justify-content: space-between; align-items: flex-start; }
.diagnostics__header h2, .diagnostics__header p { margin: 0; }
.diagnostics__header p { margin-top: var(--space-1); color: var(--text-muted); }
.diagnostics__download { display: inline-flex; align-items: center; gap: var(--space-2); min-height: 2rem; padding: 0 var(--space-3); color: var(--text-heading); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-card); font-size: var(--fs-sm); font-weight: var(--fw-bold); text-decoration: none; }
.diagnostics__filters label { display: grid; gap: var(--space-1); color: var(--text-muted); font-size: var(--fs-xs); }
.diagnostics__filters select, .diagnostics__filters input { min-height: 2.25rem; padding: 0 var(--space-3); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-card); }
.diagnostics__search { flex: 1; }
.diagnostics__search input { width: min(36rem, 100%); }
.diagnostics__notice { margin: 0; padding: var(--space-3); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-card); color: var(--text-muted); }
.diagnostics__notice.is-error { color: var(--error); }
.diagnostics__list { display: grid; gap: var(--space-3); margin: 0; padding: 0; list-style: none; }
.diagnostics__list li { min-width: 0; padding: var(--space-3); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-card); }
.diagnostics__line { flex-wrap: wrap; font: var(--fw-regular) var(--fs-xs)/1.4 var(--font-mono); }
.diagnostics__line time { color: var(--text-muted); }
.diagnostics__layer { padding: 0.15rem var(--space-2); border-radius: var(--radius-pill); background: var(--surface-sage); font-weight: var(--fw-bold); }
.diagnostics__line strong { color: var(--text-heading); }
.diagnostics__line .is-error, .diagnostics__line .is-critical { color: var(--error); }
.diagnostics__line .is-warning { color: var(--warning); }
.diagnostics__list pre { max-height: 22rem; overflow: auto; margin: var(--space-3) 0 0; padding: var(--space-3); color: var(--text-body); border-radius: var(--radius-sm); background: var(--surface-sage); font: var(--fw-regular) var(--fs-xs)/1.5 var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 760px) { .diagnostics__header, .diagnostics__filters { display: grid; } .diagnostics__actions { flex-wrap: wrap; } }
</style>
