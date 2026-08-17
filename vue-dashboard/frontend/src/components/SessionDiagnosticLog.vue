<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { Download, RefreshCw } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import {
  loadSessionDiagnosticsText,
  sessionDiagnosticsExportUrl,
} from "../session-diagnostics-api";

const props = defineProps({
  sessionId: { type: [String, Number], required: true },
});

const content = ref("");
const state = ref("loading");
const error = ref("");
const view = ref("human");
let requestSequence = 0;

const exportUrl = computed(() => sessionDiagnosticsExportUrl(props.sessionId, view.value));

async function refresh() {
  const sequence = ++requestSequence;
  state.value = "loading";
  error.value = "";
  try {
    const text = await loadSessionDiagnosticsText(props.sessionId, view.value);
    if (sequence !== requestSequence) return;
    content.value = text;
    state.value = "live";
  } catch (failure) {
    if (sequence !== requestSequence) return;
    state.value = "unavailable";
    error.value = failure instanceof Error ? failure.message : "Diagnostic logs are unavailable.";
  }
}

onMounted(refresh);
watch(view, refresh);
</script>

<template>
  <section class="diagnostics" aria-labelledby="diagnostic-log-title">
    <header class="diagnostics__header">
      <div>
        <h2 id="diagnostic-log-title">Diagnostic logs</h2>
        <p>Session-scoped telemetry rendered for reading or complete raw inspection.</p>
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

    <fieldset class="diagnostics__view-selector">
      <legend>View</legend>
      <div class="diagnostics__view-options">
        <label :class="{ 'is-selected': view === 'human' }">
          <input v-model="view" type="radio" name="diagnostics-view" value="human" />
          <span>
            <strong>Human</strong>
            Readable diagnostics with repetitive telemetry and identifier noise removed.
          </span>
        </label>
        <label :class="{ 'is-selected': view === 'verbose' }">
          <input v-model="view" type="radio" name="diagnostics-view" value="verbose" />
          <span>
            <strong>Verbose</strong>
            Complete raw telemetry including IDs, polling, heartbeats, database records, and full tracebacks.
          </span>
        </label>
      </div>
    </fieldset>

    <p v-if="state === 'loading'" class="diagnostics__notice" aria-live="polite">
      Loading {{ view }} diagnostics…
    </p>
    <p v-else-if="state === 'unavailable'" class="diagnostics__notice is-error" role="alert">
      {{ error }}
    </p>
    <p v-else-if="!content" class="diagnostics__notice">
      No diagnostic records have been written for this session yet.
    </p>
    <pre v-else class="diagnostics__output" tabindex="0">{{ content }}</pre>
  </section>
</template>

<style scoped>
.diagnostics { display: grid; gap: var(--space-4); padding: var(--space-4); background: var(--surface-sage); }
.diagnostics__header, .diagnostics__actions { display: flex; align-items: center; gap: var(--space-3); }
.diagnostics__header { justify-content: space-between; align-items: flex-start; }
.diagnostics__header h2, .diagnostics__header p { margin: 0; }
.diagnostics__header p { margin-top: var(--space-1); color: var(--text-muted); }
.diagnostics__download { display: inline-flex; align-items: center; gap: var(--space-2); min-height: 2rem; padding: 0 var(--space-3); color: var(--text-heading); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-card); font-size: var(--fs-sm); font-weight: var(--fw-bold); text-decoration: none; }
.diagnostics__view-selector { min-width: 0; margin: 0; padding: 0; border: 0; }
.diagnostics__view-selector legend { margin-bottom: var(--space-2); color: var(--text-muted); font-size: var(--fs-xs); font-weight: var(--fw-bold); }
.diagnostics__view-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); }
.diagnostics__view-options label { display: flex; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-card); color: var(--text-muted); cursor: pointer; }
.diagnostics__view-options label.is-selected { border-color: var(--text-heading); color: var(--text-body); }
.diagnostics__view-options input { margin-top: 0.2rem; accent-color: var(--text-heading); }
.diagnostics__view-options span { display: grid; gap: var(--space-1); font-size: var(--fs-xs); line-height: 1.4; }
.diagnostics__view-options strong { color: var(--text-heading); font-size: var(--fs-sm); }
.diagnostics__notice { margin: 0; padding: var(--space-3); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-card); color: var(--text-muted); }
.diagnostics__notice.is-error { color: var(--error); }
.diagnostics__output { max-height: 42rem; overflow: auto; margin: 0; padding: var(--space-4); color: var(--text-body); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-card); font: var(--fw-regular) var(--fs-xs)/1.55 var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 760px) { .diagnostics__header, .diagnostics__view-options { display: grid; grid-template-columns: 1fr; } .diagnostics__actions { flex-wrap: wrap; } }
</style>
