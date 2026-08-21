<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { AlertTriangle, Check, FileCode2 } from "@lucide/vue";
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
const duplicateAcknowledged = ref(false);

const normalizedName = computed(() => name.value.trim().replace(/\.(toml|json)$/i, "").trim());
const filename = computed(() => `${normalizedName.value || "untitled-device-template"}.toml`);
const nameMatch = computed(() => templates.value.find((template) => {
  const candidate = normalizedName.value;
  return candidate && (template.name === candidate || templateReference(template) === candidate);
}) ?? null);
const draftKey = computed(() => toml.value);
const isValidated = computed(() => validationState.value === "valid" && validatedDraft.value === draftKey.value);
const matches = computed(() => validation.value?.matches ?? []);
const visibleMatches = computed(() => matches.value.slice(0, 3));
const remainingMatchCount = computed(() => Math.max(matches.value.length - visibleMatches.value.length, 0));
const canContinue = computed(() => {
  if (step.value === 0) return Boolean(normalizedName.value && deviceType.value && !nameMatch.value);
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
  duplicateAcknowledged.value = false;
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
  else if (step.value === 1 && isValidated.value) step.value = 2;
  else if (step.value === 1) await validate({ advance: true });
}

function back() {
  if (step.value === 0) emit("cancel");
  else step.value -= 1;
}

async function create() {
  if (!isValidated.value || nameMatch.value || (matches.value.length && !duplicateAcknowledged.value)) return;
  busy.value = true;
  createError.value = "";
  try {
    const created = await createDeviceTemplate({
      name: normalizedName.value,
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
        <li v-for="(label, index) in steps" :key="label" :class="{ active: index === step, complete: index < step }" :aria-label="`Step ${index + 1}: ${label}`" :aria-current="index === step ? 'step' : undefined">
          <span><Check v-if="index < step" :size="13" /><template v-else>{{ index + 1 }}</template></span>{{ label }}
        </li>
      </ol>

      <section class="wizard-content">
        <p v-if="loadError" class="form-notice" role="alert"><AlertTriangle :size="18" /> {{ loadError }}</p>
        <div v-if="step === 0" class="wizard-section">
          <div><h2>Name and type</h2><p>The name becomes a reusable TOML file; the device type controls validation.</p></div>
          <label class="field"><span>Template name</span><input v-model="name" autofocus placeholder="e.g. 8206-high-gain" /><small>File: <code>{{ filename }}</code></small></label>
          <div v-if="nameMatch" class="conflict-notice" role="alert">
            <div><strong>Name conflict</strong><p><code>{{ filename }}</code> is already used by {{ nameMatch.name }}.</p></div>
            <BaseButton variant="secondary" @click="emit('open-existing', templateReference(nameMatch))">Open existing</BaseButton>
          </div>
          <label class="field"><span>Starter device type</span><select v-model="deviceType" :disabled="!types.length"><option v-for="row in types" :key="row.type" :value="row.type">{{ row.type }}</option></select><small>This seeds the editor. The TOML remains the source of truth.</small></label>
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
              <strong>{{ validation?.content?.type ?? deviceType }}</strong>
              <p>Required: <code>{{ types.find((row) => row.type === (validation?.content?.type ?? deviceType))?.required_parameters.join(", ") || "none" }}</code></p>
              <p>Optional: <code>{{ types.find((row) => row.type === (validation?.content?.type ?? deviceType))?.optional_parameters.join(", ") || "none" }}</code></p>
              <p>The template name comes from Step 1; TOML owns the device type and parameters.</p>
              <p v-if="validationState === 'valid'">Hash: <code>{{ validation.content_hash }}</code></p>
              <p v-else-if="validationState === 'validating'" role="status">Validating TOML…</p>
              <p v-else>Changes must be validated before you can create the template.</p>
              <p v-if="validationError" class="validation-copy" role="alert">{{ validationError }}</p>
            </aside>
          </div>
        </div>

        <div v-else class="wizard-section">
          <div><h2>Review and create</h2><p>The canonical configuration is the identity; the name is only its human label.</p></div>
          <div v-if="matches.length" class="match-notice" role="status">
            <strong>Duplicate configuration conflict</strong>
            <p>The canonical content hash <code>{{ validation.content_hash }}</code> already belongs to {{ matches.length === 1 ? "an existing template" : "existing templates" }}. Choose how you want to continue.</p>
            <div class="duplicate-choices">
              <section>
                <span>Option 1</span>
                <strong>Use an existing template</strong>
                <p>Reuse the same validated device settings without adding another copy.</p>
                <div class="match-actions"><BaseButton v-for="template in visibleMatches" :key="template.file_path" variant="secondary" @click="emit('open-existing', templateReference(template))">Open {{ template.name }}</BaseButton></div>
                <small v-if="remainingMatchCount">Also matches {{ remainingMatchCount }} other existing template{{ remainingMatchCount === 1 ? "" : "s" }}.</small>
              </section>
              <section>
                <span>Option 2</span>
                <strong>Create a separate template</strong>
                <p>Keep the new name even though its canonical device settings are identical.</p>
                <label class="duplicate-acknowledgement"><input v-model="duplicateAcknowledged" type="checkbox" /><span>I understand this creates a duplicate configuration.</span></label>
              </section>
            </div>
          </div>
          <dl class="review-list"><div><dt>Name</dt><dd>{{ normalizedName }}</dd></div><div><dt>File</dt><dd><code>{{ filename }}</code></dd></div><div><dt>Type</dt><dd><code>{{ validation?.content?.type }}</code></dd></div><div><dt>Hash</dt><dd><code>{{ validation?.content_hash }}</code></dd></div><div><dt>TOML source</dt><dd><pre>{{ toml }}</pre></dd></div></dl>
          <p v-if="createError" class="validation-copy" role="alert">{{ createError }}</p>
        </div>
      </section>

      <footer><BaseButton variant="quiet" @click="back">{{ step === 0 ? "Choose another type" : "Back" }}</BaseButton><BaseButton v-if="step < 2" :disabled="step === 0 ? !canContinue : validationState === 'validating'" @click="next">{{ step === 1 && !isValidated ? "Validate & Continue" : "Continue" }}</BaseButton><div v-else class="create-action"><small v-if="matches.length && !duplicateAcknowledged">Choose an existing template or acknowledge the duplicate above.</small><BaseButton :disabled="busy || (Boolean(matches.length) && !duplicateAcknowledged)" @click="create">{{ busy ? "Creating…" : matches.length ? "Create New Template Anyway" : "Create Device Template" }}</BaseButton></div></footer>
    </BaseCard>
  </div>
</template>

<style scoped>
.create-device-template-page { overflow-y: auto; scrollbar-gutter: stable; }
.create-device-template-page :deep(.page-header) { position: sticky; z-index: 2; top: 0; padding-block: var(--space-2); background: var(--surface-page); }
.device-template-wizard { display: flex; min-height: 0; flex-direction: column; overflow: hidden; }
.wizard-steps { display: grid; grid-template-columns: repeat(3, 1fr); flex: 0 0 auto; margin: 0; padding: 0; list-style: none; border-bottom: 1px solid var(--border-card); background: var(--surface-muted); }
.wizard-steps li { display: flex; align-items: center; justify-content: center; gap: var(--space-2); padding: var(--space-3); color: var(--text-muted); font: var(--fw-bold) var(--fs-xs) var(--font-display); }
.wizard-steps li > span { width: 24px; height: 24px; display: grid; place-items: center; border: 1px solid var(--sage-300); border-radius: var(--radius-pill); }
.wizard-steps .active, .wizard-steps .complete { color: var(--text-accent); }
.wizard-steps .active > span, .wizard-steps .complete > span { color: white; border-color: var(--accent); background: var(--accent); }
.wizard-content { min-height: 0; flex: 1 1 auto; overflow-y: auto; padding: var(--space-5); scrollbar-gutter: stable; }
.wizard-section { display: grid; gap: var(--space-5); }
.wizard-section h2 { font-size: var(--fs-h3); }
.wizard-section > div > p { margin-top: var(--space-2); color: var(--text-muted); }
.wizard-heading-split { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); }
.template-mode-badge { display: inline-flex; align-items: center; gap: var(--space-2); padding: 0.4rem 0.65rem; border: 1px solid var(--sage-300); border-radius: var(--radius-pill); color: var(--text-accent); background: var(--sage-50); font-size: var(--fs-xs); font-weight: var(--fw-bold); white-space: nowrap; }
.field { display: grid; gap: var(--space-2); }
.field > span { color: var(--text-accent); font: var(--fw-bold) var(--fs-xs) var(--font-display); text-transform: uppercase; letter-spacing: var(--ls-wide); }
.field input, .field select { width: 100%; padding: var(--space-3); border: 1px solid var(--sage-300); border-radius: var(--radius-sm); background: var(--surface-card); }
.field small, .parameter-layout aside { color: var(--text-muted); }
.parameter-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 0.35fr); gap: var(--space-4); align-items: start; }
.parameter-layout aside { display: grid; gap: var(--space-3); padding: var(--space-4); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-muted); font-size: var(--fs-xs); }
.parameter-layout code, .review-list code { overflow-wrap: anywhere; }
.toml-editor-shell { min-width: 0; overflow: hidden; border: 1px solid var(--green-950); border-radius: var(--radius-md); background: #10271a; box-shadow: var(--shadow-card); }
.toml-editor-toolbar { min-height: 46px; display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: 0 var(--space-4); color: var(--sage-100); background: #17452d; }
.toml-editor-toolbar > div { display: flex; align-items: center; gap: var(--space-2); }
.toml-editor-toolbar strong { font-family: var(--font-display); font-size: var(--fs-xs); }
.toml-editor-toolbar span { padding: 0.2rem 0.45rem; border: 1px solid rgba(255, 255, 255, 0.22); border-radius: var(--radius-sm); color: var(--sage-200); font-size: 0.62rem; font-weight: var(--fw-bold); }
.toml-editor-toolbar code { overflow: hidden; color: var(--sage-200); text-overflow: ellipsis; white-space: nowrap; }
.toml-editor-shell textarea { width: 100%; min-height: 440px; display: block; padding: var(--space-5); resize: vertical; border: 0; outline: 0; color: #edf6f0; background: #10271a; font: 0.8rem/1.7 var(--font-mono); tab-size: 2; }
.toml-editor-shell textarea:focus-visible { box-shadow: inset var(--shadow-focus); }
.conflict-notice { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-4); border: 1px solid #dfaaa6; border-left: var(--border-accent) solid var(--error); border-radius: var(--radius-md); background: #faf0ef; }
.conflict-notice strong { color: var(--error); }
.conflict-notice p { margin-top: var(--space-1); color: var(--text-muted); font-size: var(--fs-xs); }
.match-notice { display: grid; gap: var(--space-3); padding: var(--space-4); border-left: var(--border-accent) solid var(--accent); background: var(--sage-50); }
.match-notice code { overflow-wrap: anywhere; }
.match-notice small { color: var(--text-muted); }
.match-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.duplicate-choices { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.duplicate-choices section { display: grid; align-content: start; gap: var(--space-2); padding: var(--space-4); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-card); }
.duplicate-choices section > span { color: var(--text-accent); font: var(--fw-bold) 0.68rem var(--font-display); letter-spacing: var(--ls-wide); text-transform: uppercase; }
.duplicate-choices section > strong { color: var(--text-heading); font-size: var(--fs-sm); }
.duplicate-choices section > p { color: var(--text-muted); font-size: var(--fs-xs); line-height: var(--lh-body); }
.duplicate-acknowledgement { display: flex; align-items: flex-start; gap: var(--space-2); margin-top: var(--space-2); color: var(--text-body); font-size: var(--fs-xs); line-height: var(--lh-snug); cursor: pointer; }
.duplicate-acknowledgement input { width: 18px; height: 18px; flex: 0 0 auto; accent-color: var(--accent); }
.review-list { display: grid; gap: var(--space-3); margin: 0; }
.review-list > div { display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: var(--space-3); padding-bottom: var(--space-3); border-bottom: 1px solid var(--border-card); }
.review-list dt { color: var(--text-muted); font-size: var(--fs-xs); }
.review-list dd { margin: 0; }
.review-list pre { max-height: 240px; overflow: auto; margin: 0; white-space: pre-wrap; }
.device-template-wizard footer { display: flex; flex: 0 0 auto; justify-content: space-between; gap: var(--space-3); padding: var(--space-4); border-top: 1px solid var(--border-card); background: var(--surface-card); }
.create-action { display: flex; align-items: center; justify-content: flex-end; gap: var(--space-3); }
.create-action small { max-width: 320px; color: var(--error); font-size: var(--fs-xs); text-align: right; }
@media (max-width: 760px) { .parameter-layout, .duplicate-choices { grid-template-columns: 1fr; } .wizard-steps li { flex-direction: column; } .wizard-heading-split, .conflict-notice, .device-template-wizard footer, .create-action { align-items: stretch; flex-direction: column; } .create-action small { max-width: none; text-align: left; } }
</style>
