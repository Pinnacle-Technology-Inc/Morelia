<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { AlertTriangle, CheckCircle2, X } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import {
  loadDeviceTemplateSource,
  repairDeviceTemplateSource,
  validateDeviceTemplateToml,
} from "../templates-api";

const props = defineProps({ template: { type: Object, required: true } });
const emit = defineEmits(["back", "close", "repaired"]);

const dialog = ref(null);
const toml = ref("");
const loadState = ref("loading");
const loadError = ref("");
const validationState = ref("invalid");
const validationError = ref(props.template.validation_error ?? "This template did not pass validation.");
const validatedToml = ref("");
const saving = ref(false);
const saveError = ref("");

const reference = computed(() => props.template.file_path ?? props.template.name);
const filename = computed(() => reference.value.split("/").pop() || `${props.template.name}.toml`);
const canSave = computed(() => validationState.value === "valid" && validatedToml.value === toml.value);

const errorLine = computed(() => {
  const match = validationError.value.match(/(?:at\s+)?line\s+(\d+)/i);
  return match ? Number(match[1]) : null;
});

const lineContext = computed(() => {
  if (!errorLine.value) return "";
  const line = toml.value.split(/\r?\n/)[errorLine.value - 1];
  return line === undefined ? `Line ${errorLine.value}` : `Line ${errorLine.value} · ${line.trim() || "(blank line)"}`;
});

const guidance = computed(() => {
  const message = validationError.value.toLowerCase();
  if (errorLine.value || message.includes("toml")) {
    return "Check the highlighted line's TOML syntax. Assignments use key = value, strings need quotes, and section names use [brackets].";
  }
  if (message.includes("type") || message.includes("device")) {
    return "Confirm that type names a supported Morelia device, then validate again.";
  }
  if (message.includes("parameter") || message.includes("unknown") || message.includes("unsupported")) {
    return "Compare [parameters] with the settings supported by this device type. Remove unknown keys or use an allowed value.";
  }
  return "Review the template name, device type, and [parameters] values, then validate the source again.";
});

function describeError(error, fallback) {
  return error?.problem?.detail ?? error?.problem?.message ?? error?.message ?? fallback;
}

watch(toml, () => {
  if (validatedToml.value === toml.value && validatedToml.value) {
    validationState.value = "valid";
  } else if (loadState.value === "ready") {
    validationState.value = "dirty";
  }
  saveError.value = "";
});

onMounted(async () => {
  try {
    const source = await loadDeviceTemplateSource(reference.value);
    toml.value = source.toml;
    loadState.value = "ready";
    validationState.value = "invalid";
    await nextTick();
    dialog.value?.focus();
  } catch (error) {
    loadState.value = "error";
    loadError.value = describeError(error, "The device template source could not be loaded.");
  }
});

async function validate() {
  if (!toml.value.trim() || validationState.value === "validating") return false;
  const source = toml.value;
  validationState.value = "validating";
  validationError.value = "";
  saveError.value = "";
  try {
    await validateDeviceTemplateToml(source);
    if (toml.value !== source) return false;
    validatedToml.value = source;
    validationState.value = "valid";
    return true;
  } catch (error) {
    if (toml.value !== source) return false;
    validatedToml.value = "";
    validationState.value = "invalid";
    validationError.value = describeError(error, "This device template is invalid.");
    return false;
  }
}

async function save() {
  if (!canSave.value) return;
  saving.value = true;
  saveError.value = "";
  try {
    const repaired = await repairDeviceTemplateSource(reference.value, toml.value);
    emit("repaired", repaired);
  } catch (error) {
    saveError.value = describeError(error, "The repaired device template could not be saved.");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="emit('close')">
    <section
      ref="dialog"
      class="dialog repair-device-template"
      role="dialog"
      aria-modal="true"
      aria-labelledby="repair-device-template-title"
      tabindex="-1"
      @keydown.esc="emit('close')"
    >
      <header>
        <div>
          <h2 id="repair-device-template-title">Repair device template</h2>
          <p><strong>{{ template.name }}</strong> · <code>{{ filename }}</code></p>
        </div>
        <button type="button" class="icon-button" aria-label="Close repair window" @click="emit('close')">
          <X :size="19" />
        </button>
      </header>

      <div class="dialog__content">
        <p v-if="loadState === 'loading'" class="repair-device-template__empty" aria-busy="true">Loading template source…</p>
        <p v-else-if="loadState === 'error'" class="repair-device-template__empty" role="alert">{{ loadError }}</p>
        <div v-else class="repair-device-template__layout">
          <label class="repair-source">
            <span><strong>{{ filename }}</strong><small>Editable repair source</small></span>
            <textarea v-model="toml" spellcheck="false" aria-label="Device template TOML source" />
          </label>

          <aside class="repair-guidance" aria-live="polite">
            <div v-if="validationState === 'valid'" class="repair-guidance__valid">
              <CheckCircle2 :size="18" aria-hidden="true" />
              <div><strong>Validation passed</strong><p>This source is ready to save.</p></div>
            </div>
            <template v-else>
              <div class="repair-guidance__error">
                <AlertTriangle :size="18" aria-hidden="true" />
                <div>
                  <strong>{{ validationState === "validating" ? "Validating…" : "Validation error" }}</strong>
                  <p v-if="validationError">{{ validationError }}</p>
                  <code v-if="lineContext">{{ lineContext }}</code>
                </div>
              </div>
              <div class="repair-guidance__help">
                <strong>Debug guidance</strong>
                <p>{{ guidance }}</p>
              </div>
            </template>
            <p v-if="saveError" class="repair-guidance__save-error" role="alert">{{ saveError }}</p>
          </aside>
        </div>
      </div>

      <footer>
        <BaseButton variant="secondary" :disabled="saving" @click="emit('back')">Back</BaseButton>
        <BaseButton
          variant="secondary"
          :disabled="saving || loadState !== 'ready' || validationState === 'validating' || !toml.trim()"
          @click="validate"
        >
          {{ validationState === "validating" ? "Validating…" : "Validate TOML" }}
        </BaseButton>
        <BaseButton :disabled="saving || !canSave" @click="save">
          {{ saving ? "Saving…" : "Save repair" }}
        </BaseButton>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.repair-device-template {
  width: min(980px, 100%);
  max-height: calc(100vh - 2rem);
  display: flex;
  flex-direction: column;
}

.repair-device-template:focus { outline: none; }
.repair-device-template .dialog__content { min-height: 0; overflow: auto; padding: var(--space-5); }
.repair-device-template__empty { min-height: 360px; display: grid; place-items: center; color: var(--text-muted); }
.repair-device-template__layout { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(250px, 0.75fr); gap: var(--space-4); min-height: 430px; }

.repair-source { display: flex; min-width: 0; flex-direction: column; overflow: hidden; border: 1px solid var(--green-900); border-radius: var(--radius-md); background: var(--green-950); }
.repair-source > span { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) var(--space-4); color: var(--text-on-dark); border-bottom: 1px solid rgb(255 255 255 / 12%); font-size: var(--fs-xs); }
.repair-source small { color: var(--sage-300); }
.repair-source textarea { width: 100%; min-height: 380px; flex: 1; resize: vertical; padding: var(--space-4); color: #eef7f1; border: 0; outline: 0; background: transparent; font: 0.78rem/1.65 var(--font-mono); tab-size: 2; }
.repair-source:focus-within { box-shadow: var(--shadow-focus); }

.repair-guidance { display: grid; align-content: start; gap: var(--space-3); }
.repair-guidance__error,
.repair-guidance__valid,
.repair-guidance__help { display: flex; align-items: flex-start; gap: var(--space-3); padding: var(--space-4); border: 1px solid var(--border-card); border-radius: var(--radius-md); }
.repair-guidance__error { color: var(--error); border-color: #dfaaa6; background: #faf0ef; }
.repair-guidance__valid { color: var(--success); border-color: var(--sage-300); background: var(--sage-50); }
.repair-guidance__help { display: block; background: var(--surface-sage); }
.repair-guidance strong { font-family: var(--font-display); font-size: var(--fs-xs); }
.repair-guidance p { margin-top: var(--space-2); color: var(--text-body); font-size: var(--fs-xs); line-height: 1.55; overflow-wrap: anywhere; }
.repair-guidance code { display: block; margin-top: var(--space-3); padding: var(--space-2); color: var(--text-body); border-radius: var(--radius-sm); background: rgb(255 255 255 / 60%); white-space: pre-wrap; overflow-wrap: anywhere; }
.repair-guidance__save-error { color: var(--error); }

@media (max-width: 760px) {
  .repair-device-template__layout { grid-template-columns: 1fr; }
  .repair-device-template .dialog__content { padding: var(--space-3); }
  .repair-source textarea { min-height: 300px; }
  .repair-device-template footer { flex-wrap: wrap; }
}
</style>
