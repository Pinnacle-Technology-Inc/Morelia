<script setup>
import { computed, onMounted, ref } from "vue";
import { X } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import { loadDeviceConfig } from "../devices-api";
import { createDeviceTemplate, loadDeviceTemplates } from "../templates-api";

const props = defineProps({
  device: { type: Object, required: true },
});
const emit = defineEmits(["close", "exported"]);

const loadState = ref("loading"); // loading | ready | error
const loadError = ref("");
const step = ref("name"); // confirm-dup | name
const busy = ref(false);
const errorMsg = ref("");

const config = ref(null);
const templates = ref([]);
const duplicates = ref([]);
const templateName = ref("");

// Recursively key-sorted stringify so two canonical parameter maps compare equal
// regardless of key order. Both the config's stored parameters and a template's
// content are already registry-canonical, so this is an exact content match —
// the client-side stand-in for the server content hash (see gap register D-03).
function stableStringify(value) {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}

// Warn (non-blocking) when the chosen name would overwrite a differently-named
// existing template file — create() replaces a same-named file in place.
const nameCollision = computed(() =>
  templates.value.some((template) => template.name === templateName.value.trim()),
);

onMounted(async () => {
  try {
    const [loadedConfig, templateList] = await Promise.all([
      loadDeviceConfig(props.device.configId),
      loadDeviceTemplates().catch(() => []),
    ]);
    config.value = loadedConfig;
    templates.value = Array.isArray(templateList) ? templateList : [];
    templateName.value = props.device.nickname ?? props.device.name ?? props.device.hardwareId ?? "";

    const signature = stableStringify(loadedConfig?.parameters ?? {});
    duplicates.value = templates.value.filter(
      (template) =>
        template.type === loadedConfig?.type &&
        stableStringify(template.content?.parameters ?? {}) === signature,
    );
    step.value = duplicates.value.length ? "confirm-dup" : "name";
    loadState.value = "ready";
  } catch (reason) {
    loadState.value = "error";
    loadError.value = reason instanceof Error ? reason.message : "Could not load the device config.";
  }
});

async function onExport() {
  const name = templateName.value.trim();
  if (!name) {
    errorMsg.value = "Enter a name for the template.";
    return;
  }
  errorMsg.value = "";
  busy.value = true;
  try {
    await createDeviceTemplate({
      name,
      type: config.value.type,
      parameters: config.value.parameters ?? {},
    });
    emit("exported", name);
  } catch (reason) {
    errorMsg.value = reason instanceof Error ? reason.message : "Export failed.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="$emit('close')">
    <section class="dialog device-export-dialog" role="dialog" aria-modal="true" aria-label="Export device template">
      <header>
        <div>
          <h2>Export template</h2>
          <p>{{ device.name }} · <code>{{ device.type }}</code></p>
        </div>
        <button class="icon-button" type="button" aria-label="Close dialog" @click="$emit('close')"><X :size="19" /></button>
      </header>

      <div class="dialog__content">
        <p v-if="loadState === 'loading'" class="empty-state" aria-busy="true">Checking existing templates…</p>
        <p v-else-if="loadState === 'error'" class="empty-state" role="alert">{{ loadError }}</p>

        <div v-else-if="step === 'confirm-dup'" class="dialog-form">
          <div class="dialog-notice">
            <strong>A device template with identical settings already exists.</strong>
            <ul>
              <li v-for="template in duplicates" :key="template.file_path"><code>{{ template.name }}</code> — {{ template.file_path }}</li>
            </ul>
            <p>Save these settings as a duplicate template anyway?</p>
          </div>
        </div>

        <div v-else class="dialog-form">
          <label class="field field--wide">
            <span>Template name</span>
            <input v-model="templateName" type="text" placeholder="e.g. pod-high" @keydown.enter="onExport" />
            <small v-if="nameCollision" class="validation-copy">A template named “{{ templateName.trim() }}” already exists and will be overwritten.</small>
          </label>
          <p class="device-export-dialog__hint">Saved to the device-template library as a <code>.toml</code> file.</p>
        </div>

        <p v-if="errorMsg" class="validation-copy" role="alert">{{ errorMsg }}</p>
      </div>

      <footer>
        <BaseButton variant="secondary" :disabled="busy" @click="$emit('close')">Cancel</BaseButton>
        <BaseButton v-if="loadState === 'ready' && step === 'confirm-dup'" :disabled="busy" @click="step = 'name'">Make a duplicate</BaseButton>
        <BaseButton v-else-if="loadState === 'ready'" :disabled="busy" @click="onExport">Export template</BaseButton>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.device-export-dialog { width: min(560px, 100%); }
.device-export-dialog__hint { color: var(--muted); font-size: 0.75rem; }
.dialog-notice ul { margin: 0; padding-left: 1.1rem; font-size: 0.78rem; }
.dialog-notice code { overflow-wrap: anywhere; }
</style>
