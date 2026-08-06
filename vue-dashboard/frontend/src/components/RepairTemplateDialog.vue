<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { AlertTriangle, X } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import TemplateTomlEditor from "./TemplateTomlEditor.vue";
import {
  loadDeviceTemplates,
  loadSessionTemplateSource,
  repairSessionTemplateSource,
  validateSessionTemplateToml,
} from "../templates-api";

const props = defineProps({
  template: { type: Object, required: true },
  issues: { type: Array, default: () => [] },
});
const emit = defineEmits(["close", "repaired"]);

const dialog = ref(null);
const toml = ref("");
const deviceTemplates = ref([]);
const loadState = ref("loading");
const loadError = ref("");
const validationState = ref("idle");
const validationError = ref("");
const validationResult = ref(null);
const validatedToml = ref("");
const saving = ref(false);
const saveError = ref("");

const filename = computed(() => props.template.reference.split("/").pop() || `${props.template.name}.toml`);
const summary = computed(() => validationResult.value?.summary ?? null);
const currentTomlIsValid = computed(
  () => validationState.value === "valid" && validatedToml.value === toml.value,
);

function describeError(error, fallback) {
  return error?.problem?.detail ?? error?.problem?.message ?? error?.message ?? fallback;
}

watch(toml, () => {
  if (validatedToml.value === toml.value && validationResult.value) {
    validationState.value = "valid";
    return;
  }
  validationState.value = toml.value.trim() ? "dirty" : "idle";
  validationError.value = "";
  saveError.value = "";
});

onMounted(async () => {
  try {
    const [source, templates] = await Promise.all([
      loadSessionTemplateSource(props.template.reference),
      loadDeviceTemplates().catch(() => []),
    ]);
    toml.value = source.toml;
    deviceTemplates.value = templates;
    validationState.value = "error";
    validationError.value = props.issues.join(" ") || "This template is not valid TOML.";
    loadState.value = "ready";
    await nextTick();
    dialog.value?.focus();
  } catch (error) {
    loadError.value = describeError(error, "The template source could not be loaded.");
    loadState.value = "error";
  }
});

async function validateToml() {
  if (!toml.value.trim() || validationState.value === "validating") return false;
  const source = toml.value;
  validationState.value = "validating";
  validationError.value = "";
  saveError.value = "";
  try {
    const result = await validateSessionTemplateToml(source);
    if (toml.value !== source) return false;
    validationResult.value = result;
    validatedToml.value = source;
    validationState.value = "valid";
    return true;
  } catch (error) {
    if (toml.value !== source) return false;
    validationResult.value = null;
    validatedToml.value = "";
    validationState.value = "error";
    validationError.value = describeError(error, "This TOML template is not valid.");
    return false;
  }
}

async function save() {
  if (!currentTomlIsValid.value && !(await validateToml())) return;
  saving.value = true;
  saveError.value = "";
  try {
    const repaired = await repairSessionTemplateSource(props.template.reference, toml.value);
    emit("repaired", repaired);
  } catch (error) {
    saveError.value = describeError(error, "The repaired template could not be saved.");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="emit('close')">
    <section
      ref="dialog"
      class="dialog repair-template-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="repair-template-title"
      tabindex="-1"
      @keydown.esc="emit('close')"
    >
      <header>
        <div>
          <h2 id="repair-template-title">Repair {{ template.name }}</h2>
          <p>Edit the source below. Morelia validates it before replacing the invalid file.</p>
        </div>
        <button class="icon-button" type="button" aria-label="Close repair dialog" @click="emit('close')">
          <X :size="19" />
        </button>
      </header>

      <div class="dialog__content">
        <div v-if="issues.length" class="repair-issues" role="status">
          <AlertTriangle :size="18" aria-hidden="true" />
          <div>
            <strong>What is wrong</strong>
            <ul><li v-for="issue in issues" :key="issue">{{ issue }}</li></ul>
          </div>
        </div>
        <p v-if="loadState === 'loading'" class="empty-state" aria-busy="true">Loading template source…</p>
        <p v-else-if="loadState === 'error'" class="empty-state" role="alert">{{ loadError }}</p>
        <TemplateTomlEditor
          v-else
          v-model="toml"
          :filename="filename"
          :state="validationState"
          :error="validationError"
          :summary="summary"
          :device-templates="deviceTemplates"
          @validate="validateToml"
        />
        <p v-if="saveError" class="form-notice" role="alert">
          <AlertTriangle :size="18" aria-hidden="true" /> {{ saveError }}
        </p>
      </div>

      <footer>
        <BaseButton variant="secondary" :disabled="saving" @click="emit('close')">Cancel</BaseButton>
        <BaseButton
          v-if="loadState === 'ready'"
          :disabled="saving || !toml.trim()"
          @click="save"
        >
          {{ saving ? "Saving…" : currentTomlIsValid ? "Save repair" : "Validate & save" }}
        </BaseButton>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.repair-template-dialog {
  width: min(1080px, 100%);
  max-height: calc(100vh - 2rem);
  display: flex;
  flex-direction: column;
}

.repair-template-dialog:focus {
  outline: none;
}

.repair-template-dialog .dialog__content {
  max-height: none;
  flex: 1 1 auto;
  overflow: auto;
}

.repair-issues {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding: var(--space-4);
  color: var(--error);
  border: 1px solid #dfaaa6;
  border-radius: var(--radius-md);
  background: #faf0ef;
}

.repair-issues strong {
  font-family: var(--font-display);
  font-size: var(--fs-sm);
}

.repair-issues ul {
  margin: var(--space-2) 0 0;
  padding-left: 1.1rem;
  color: var(--text-body);
  font-size: var(--fs-xs);
}

.repair-issues li + li {
  margin-top: var(--space-1);
}

.repair-template-dialog :deep(.toml-editor-shell textarea) {
  min-height: 360px;
}

@media (max-width: 540px) {
  .repair-template-dialog {
    max-height: 100vh;
    border-radius: 0;
  }
}
</style>
