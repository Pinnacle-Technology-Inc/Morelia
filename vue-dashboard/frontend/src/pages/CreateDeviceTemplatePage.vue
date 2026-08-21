<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { AlertTriangle, Check, Cpu } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import {
  createDeviceTemplate,
  loadDeviceTemplateTypes,
  loadDeviceTemplates,
  validateDeviceTemplateToml,
} from "../templates-api";

const emit = defineEmits(["cancel", "created", "open-existing"]);
const steps = ["Details", "TOML", "Review"];
const examples = {
  pod8206hr: `type = "pod8206hr"

[parameters]
preamp_gain = 10
sample_rate = 2000
`,
  pod8401hr: `type = "pod8401hr"

[parameters]
preamp = "Preamp8407_SE"
primary_channel_modes = ["BIOSENSOR", "EEG_EMG", "EEG_EMG", "EEG_EMG"]
secondary_channel_modes = ["DIGITAL", "DIGITAL", "DIGITAL", "DIGITAL", "DIGITAL", "DIGITAL"]
ss_gain = [1, 5, 5, 5]
sample_rate = 2000
`,
};

const step = ref(0);
const name = ref("");
const deviceType = ref("");
const toml = ref("");
const types = ref([]);
const templates = ref([]);
const loadError = ref("");
const validationState = ref("idle");
const validationError = ref("");
const validation = ref(null);
const validatedDraft = ref("");
const busy = ref(false);
const createError = ref("");

const filename = computed(() => `${name.value.trim() || "untitled-device-template"}.toml`);
const nameCollision = computed(() => {
  const candidate = name.value.trim();
  return templates.value.some((template) => template.name === candidate || templateReference(template) === candidate);
});
const draftKey = computed(() => `${deviceType.value}\n${parametersText.value}`);
const isValidated = computed(() => validationState.value === "valid" && validatedDraft.value === draftKey.value);
const matches = computed(() => validation.value?.matches ?? []);
const canContinue = computed(() => {
  if (step.value === 0) return Boolean(name.value.trim() && deviceType.value && !nameCollision.value);
  if (step.value === 1) return isValidated.value;
  return false;
});

function describeError(error, fallback) {
  return error?.problem?.detail ?? error?.message ?? fallback;
}

function templateReference(template) {
  return template.file_path?.split(/[\\/]/).pop()?.replace(/\.toml$/i, "") ?? template.name;
}

function seedParameters(type) {
  toml.value = examples[type] ?? `type = "${type}"\n\n[parameters]\n`;
}

watch(deviceType, seedParameters);
watch(toml, () => {
  validationState.value = toml.value.trim() ? "dirty" : "idle";
  validationError.value = "";
  validation.value = null;
  createError.value = "";
});

onMounted(async () => {
  try {
    const [typeRows, templateRows] = await Promise.all([loadDeviceTemplateTypes(), loadDeviceTemplates()]);
    types.value = typeRows;
    templates.value = templateRows;
    deviceType.value = typeRows[0]?.type ?? "";
  } catch (error) {
    loadError.value = describeError(error, "Device-template metadata is unavailable.");
  }
});

async function validate({ advance = false } = {}) {
  if (!toml.value.trim() || validationState.value === "validating") return;
  validationState.value = "validating";
  validationError.value = "";
  const snapshot = draftKey.value;
  try {
    const result = await validateDeviceTemplateToml(toml.value);
    if (snapshot !== draftKey.value) return;
    validation.value = result;
    validatedDraft.value = snapshot;
    validationState.value = "valid";
    if (advance) step.value = 2;
  } catch (error) {
    validationState.value = "error";
    validationError.value = describeError(error, "These parameters are not valid for the selected device type.");
  }
}

async function next() {
  if (step.value === 0 && canContinue.value) step.value = 1;
  else if (step.value === 1) await validate({ advance: true });
}

function back() {
  if (step.value === 0) emit("cancel");
  else step.value -= 1;
}

async function create() {
  if (!isValidated.value || matches.value.length || nameCollision.value) return;
  busy.value = true;
  createError.value = "";
  try {
    const created = await createDeviceTemplate({
      name: name.value.trim(),
      type: validation.value.content.type,
      parameters: validation.value.content.parameters,
    });
    emit("created", created.name);
  } catch (error) {
    createError.value = describeError(error, "The device template could not be created.");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="page page--workspace create-device-template-page">
    <PageHeader eyebrow="Reusable device configuration" title="Create Device Template" />
    <BaseCard class="device-template-wizard">
      <ol class="wizard-steps" aria-label="Device template creation progress">
        <li v-for="(label, index) in steps" :key="label" :class="{ active: index === step, complete: index < step }">
          <span><Check v-if="index < step" :size="13" /><template v-else>{{ index + 1 }}</template></span>{{ label }}
        </li>
      </ol>

      <section class="wizard-content">
        <p v-if="loadError" class="form-notice" role="alert"><AlertTriangle :size="18" /> {{ loadError }}</p>
        <div v-if="step === 0" class="wizard-section">
          <div><h2>Name and type</h2><p>The name becomes a reusable TOML file; the device type controls validation.</p></div>
          <label class="field"><span>Template name</span><input v-model="name" autofocus placeholder="e.g. 8206-high-gain" /><small>File: <code>{{ filename }}</code></small></label>
          <p v-if="nameCollision" class="validation-copy" role="alert">That name is already in use. Open the existing template or choose another name.</p>
          <label class="field"><span>Device type</span><select v-model="deviceType" :disabled="!types.length"><option v-for="row in types" :key="row.type" :value="row.type">{{ row.type }}</option></select></label>
        </div>

        <div v-else-if="step === 1" class="wizard-section">
          <div class="wizard-heading-split">
            <div><h2>Edit as TOML</h2><p>Validation checks the complete device template and canonicalizes its parameters before hashing.</p></div>
            <span class="template-mode-badge"><FileCode2 :size="15" /> TOML only</span>
          </div>
          <div class="parameter-layout">
            <section class="toml-editor-shell" aria-labelledby="device-toml-editor-title">
              <header class="toml-editor-toolbar">
                <div><strong id="device-toml-editor-title">Device template source</strong><span>TOML</span></div>
                <code>{{ filename }}</code>
              </header>
              <label class="visually-hidden" for="device-template-toml">Device template TOML</label>
              <textarea id="device-template-toml" v-model="toml" spellcheck="false" autocomplete="off" autocapitalize="off" />
            </section>
            <aside>
              <strong>{{ deviceType }}</strong>
              <p>Required: <code>{{ types.find((row) => row.type === deviceType)?.required_parameters.join(", ") || "none" }}</code></p>
              <p>Optional: <code>{{ types.find((row) => row.type === deviceType)?.optional_parameters.join(", ") || "none" }}</code></p>
              <p v-if="validationState === 'valid'">Hash: <code>{{ validation.content_hash }}</code></p>
              <p v-if="validationError" class="validation-copy" role="alert">{{ validationError }}</p>
            </aside>
          </div>
        </div>

        <div v-else class="wizard-section">
          <div><h2>Review and create</h2><p>The canonical configuration is the identity; the name is only its human label.</p></div>
          <div v-if="matches.length" class="match-notice" role="status">
            <strong>These settings already exist.</strong>
            <p>Reuse the matching template instead of creating a repeated configuration.</p>
            <BaseButton v-for="template in matches" :key="template.file_path" variant="secondary" @click="emit('open-existing', templateReference(template))">Open {{ template.name }}</BaseButton>
          </div>
          <dl class="review-list"><div><dt>Name</dt><dd>{{ name.trim() }}</dd></div><div><dt>Type</dt><dd><code>{{ validation?.content?.type }}</code></dd></div><div><dt>Hash</dt><dd><code>{{ validation?.content_hash }}</code></dd></div><div><dt>Parameters</dt><dd><pre>{{ JSON.stringify(validation?.content?.parameters ?? {}, null, 2) }}</pre></dd></div></dl>
          <p v-if="createError" class="validation-copy" role="alert">{{ createError }}</p>
        </div>
      </section>

      <footer><BaseButton variant="quiet" @click="back">{{ step === 0 ? "Choose another type" : "Back" }}</BaseButton><BaseButton v-if="step < 2" :disabled="step === 0 ? !canContinue : validationState === 'validating'" @click="next">{{ step === 1 ? "Validate & Continue" : "Continue" }}</BaseButton><BaseButton v-else :disabled="busy || Boolean(matches.length)" @click="create">{{ busy ? "Creating…" : "Create Device Template" }}</BaseButton></footer>
    </BaseCard>
  </div>
</template>

<style scoped>
.create-device-template-page { overflow-y: auto; }
.device-template-wizard { overflow: hidden; }
.wizard-steps { display: grid; grid-template-columns: repeat(3, 1fr); margin: 0; padding: 0; list-style: none; border-bottom: 1px solid var(--border-card); background: var(--surface-muted); }
.wizard-steps li { display: flex; align-items: center; justify-content: center; gap: var(--space-2); padding: var(--space-3); color: var(--text-muted); font: var(--fw-bold) var(--fs-xs) var(--font-display); }
.wizard-steps li > span { width: 24px; height: 24px; display: grid; place-items: center; border: 1px solid var(--sage-300); border-radius: var(--radius-pill); }
.wizard-steps .active, .wizard-steps .complete { color: var(--text-accent); }
.wizard-steps .active > span, .wizard-steps .complete > span { color: white; border-color: var(--accent); background: var(--accent); }
.wizard-content { padding: var(--space-5); }
.wizard-section { display: grid; gap: var(--space-5); }
.wizard-section h2 { font-size: var(--fs-h3); }
.wizard-section > div > p { margin-top: var(--space-2); color: var(--text-muted); }
.field { display: grid; gap: var(--space-2); }
.field > span { color: var(--text-accent); font: var(--fw-bold) var(--fs-xs) var(--font-display); text-transform: uppercase; letter-spacing: var(--ls-wide); }
.field input, .field select, .field textarea { width: 100%; padding: var(--space-3); border: 1px solid var(--sage-300); border-radius: var(--radius-sm); background: var(--surface-card); }
.field textarea { min-height: 360px; resize: vertical; font: var(--fs-sm)/1.6 var(--font-mono); }
.field small, .parameter-layout aside { color: var(--text-muted); }
.parameter-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 0.35fr); gap: var(--space-4); align-items: start; }
.parameter-layout aside { display: grid; gap: var(--space-3); padding: var(--space-4); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-muted); font-size: var(--fs-xs); }
.parameter-layout code, .review-list code { overflow-wrap: anywhere; }
.match-notice { display: grid; gap: var(--space-3); padding: var(--space-4); border-left: var(--border-accent) solid var(--accent); background: var(--sage-50); }
.review-list { display: grid; gap: var(--space-3); margin: 0; }
.review-list > div { display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: var(--space-3); padding-bottom: var(--space-3); border-bottom: 1px solid var(--border-card); }
.review-list dt { color: var(--text-muted); font-size: var(--fs-xs); }
.review-list dd { margin: 0; }
.review-list pre { max-height: 240px; overflow: auto; margin: 0; white-space: pre-wrap; }
.device-template-wizard footer { display: flex; justify-content: space-between; gap: var(--space-3); padding: var(--space-4); border-top: 1px solid var(--border-card); }
@media (max-width: 760px) { .parameter-layout { grid-template-columns: 1fr; } .wizard-steps li { flex-direction: column; } }
</style>
