<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { AlertTriangle, Folder, X } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import FolderPickerDialog from "./FolderPickerDialog.vue";
import {
  buildSinkLocationUpdates,
  moveOutputToFolder,
  outputFolder,
  suggestedSinkLocation,
} from "../sink-location-recovery";

const props = defineProps({
  sinks: { type: Array, default: () => [] },
  loading: Boolean,
  busy: Boolean,
  error: { type: String, default: "" },
  reason: { type: String, default: "" },
});
const emit = defineEmits(["close", "retry", "save"]);

const rows = ref([]);
const folderTarget = ref(null);
const firstPathInput = ref(null);

function setFirstPathInput(element) {
  firstPathInput.value = element;
}

watch(
  () => props.sinks,
  async (sinks) => {
    rows.value = sinks.map((sink) => ({
      ...sink,
      edited_location: sink.current_location ?? sink.suggested_location ?? "",
    }));
    await nextTick();
    firstPathInput.value?.focus();
  },
  { immediate: true },
);

const cannotSave = computed(() =>
  props.loading || props.busy || rows.value.length === 0 ||
  rows.value.some((sink) => !String(sink.edited_location ?? "").trim()),
);

function useSuggestion(row) {
  const suggestion = suggestedSinkLocation(row);
  if (suggestion) row.edited_location = suggestion;
}

function selectFolder(folder) {
  const row = rows.value[folderTarget.value];
  if (row) row.edited_location = moveOutputToFolder(row.edited_location, folder);
  folderTarget.value = null;
}

function save() {
  if (cannotSave.value) return;
  emit("save", buildSinkLocationUpdates(rows.value));
}

function close() {
  if (!props.busy) emit("close");
}
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="close" @keydown.esc="close">
    <section class="dialog sink-editor" role="dialog" aria-modal="true" aria-label="Edit output paths">
      <header>
        <div>
          <h2>Edit output paths</h2>
          <p>Changes are saved to this never-started run before it is started.</p>
        </div>
        <button class="icon-button" type="button" aria-label="Close dialog" :disabled="busy" @click="close">
          <X :size="19" />
        </button>
      </header>

      <div class="dialog__content">
        <p v-if="reason" class="form-notice" role="alert"><AlertTriangle :size="18" /> {{ reason }}</p>
        <p v-if="loading" class="sink-editor__empty" role="status">Loading output paths…</p>
        <div v-else-if="rows.length" class="sink-editor__rows">
          <article v-for="(row, index) in rows" :key="`${row.flow_index}:${row.sink_index}`" class="sink-editor__row">
            <header>
              <div>
                <strong>{{ row.nickname || `Flow ${row.flow_index + 1}` }} · {{ row.sink_name }}</strong>
                <span>{{ String(row.sink_type).toUpperCase() }} output</span>
              </div>
              <span v-if="row.occupied" class="sink-editor__conflict">File exists</span>
              <span v-else-if="row.parent_issue" class="sink-editor__conflict">Folder unavailable</span>
            </header>
            <label class="field">
              <span>Absolute output path</span>
              <input
                :ref="index === 0 ? setFirstPathInput : undefined"
                v-model="row.edited_location"
                :disabled="busy"
                required
              />
            </label>
            <div class="sink-editor__actions">
              <BaseButton
                v-if="suggestedSinkLocation(row) && suggestedSinkLocation(row) !== row.edited_location"
                variant="secondary"
                size="small"
                :disabled="busy"
                @click="useSuggestion(row)"
              >
                Use suggested path
              </BaseButton>
              <BaseButton variant="secondary" size="small" :disabled="busy" @click="folderTarget = index">
                <Folder :size="14" /> Choose folder
              </BaseButton>
            </div>
          </article>
        </div>
        <div v-else class="sink-editor__empty">
          <p>{{ error || "No editable file outputs were found for this run." }}</p>
          <BaseButton v-if="error" variant="secondary" @click="emit('retry')">Retry loading paths</BaseButton>
        </div>
        <p v-if="error && rows.length" class="form-notice" role="alert"><AlertTriangle :size="18" /> {{ error }}</p>
      </div>

      <footer>
        <BaseButton variant="secondary" :disabled="busy" @click="close">Cancel</BaseButton>
        <BaseButton :disabled="cannotSave" @click="save">{{ busy ? "Saving…" : "Save output paths" }}</BaseButton>
      </footer>
    </section>
    <FolderPickerDialog
      v-if="folderTarget !== null"
      :model-value="outputFolder(rows[folderTarget]?.edited_location)"
      @close="folderTarget = null"
      @select="selectFolder"
    />
  </div>
</template>

<style scoped>
.sink-editor { width: min(720px, 100%); }
.sink-editor__rows { display: grid; gap: var(--space-4); }
.sink-editor__row { display: grid; gap: var(--space-3); padding: var(--space-4); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-sage); }
.sink-editor__row > header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.sink-editor__row > header div { display: grid; gap: var(--space-1); }
.sink-editor__row > header span { color: var(--muted); font-size: var(--fs-xs); }
.sink-editor__conflict { padding: var(--space-1) var(--space-2); color: #9f5c08 !important; border: 1px solid #e6c27a; border-radius: var(--radius-pill); background: #fff9e8; font-weight: 700; white-space: nowrap; }
.sink-editor__actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.sink-editor__empty { display: grid; justify-items: start; gap: var(--space-3); color: var(--muted); }
@media (max-width: 560px) {
  .sink-editor__row > header { display: grid; }
  .sink-editor__actions { display: grid; }
}
</style>
