<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { AlertTriangle, Check, FileCode2 } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import TemplateTomlEditor from "../components/TemplateTomlEditor.vue";
import {
  createSessionTemplateFromToml,
  duplicateTemplateFrom,
  loadDeviceTemplates,
  validateSessionTemplateToml,
} from "../templates-api";

const emit = defineEmits(["cancel", "created", "open-existing-template"]);

const SNAPSHOT_KEY = "create-template-toml-draft";
const FALLBACK_DEVICE_TEMPLATE = "device-templates/your-device-template.toml";
const steps = ["Details", "TOML", "Recovery", "Review"];

function exampleToml(deviceTemplatePath = FALLBACK_DEVICE_TEMPLATE) {
  return `policy = "recommend"

[[device_flows]]
device_template_path = "${deviceTemplatePath}"
# hardware_id = "17200" # Optional exact-device preference.

[[device_flows.sinks]]
sink_type = "csv"
sink_name = "primary"
# Omit sink_location to use Morelia's generated, collision-safe output path.

[[device_flows.sinks]]
sink_type = "plot"
sink_name = "live"
`;
}

const step = ref(0);
const templateName = ref("");
const toml = ref(exampleToml());
const deviceTemplates = ref([]);
const validationState = ref("idle");
const validationError = ref("");
const validationResult = ref(null);
const validatedToml = ref("");
const createState = ref("idle");
const createError = ref("");
const duplicateTemplate = ref(null);

const filename = computed(() => `${templateName.value.trim() || "untitled-template"}.toml`);
const detailsComplete = computed(() => Boolean(templateName.value.trim()));
const tomlIsCurrentAndValid = computed(
  () => validationState.value === "valid" && validatedToml.value === toml.value,
);
const summary = computed(() => validationResult.value?.summary ?? null);
const recoveryPolicy = computed(() => summary.value?.policy ?? "recommend");
const canAdvance = computed(() => {
  if (step.value === 0) return detailsComplete.value;
  if (step.value === 1) return tomlIsCurrentAndValid.value;
  return true;
});
const advanceBlockedReason = computed(() => {
  if (canAdvance.value) return "";
  if (step.value === 0) return "Name this template to continue.";
  return validationState.value === "error"
    ? "Fix the TOML validation error to continue."
    : "Validate the current TOML to continue.";
});
const createDisabled = computed(
  () => createState.value === "creating" || !detailsComplete.value || !tomlIsCurrentAndValid.value,
);

function describeError(error, fallback) {
  return error?.problem?.detail ?? error?.problem?.message ?? error?.message ?? fallback;
}

function persistSnapshot() {
  try {
    sessionStorage.setItem(
      SNAPSHOT_KEY,
      JSON.stringify({ step: step.value, templateName: templateName.value, toml: toml.value }),
    );
  } catch {
    // Private browsing or storage pressure degrades safely to no persistence.
  }
}

function restoreSnapshot() {
  let snapshot = null;
  try {
    snapshot = JSON.parse(sessionStorage.getItem(SNAPSHOT_KEY) ?? "null");
  } catch {
    snapshot = null;
  }
  if (!snapshot || typeof snapshot !== "object" || typeof snapshot.toml !== "string") return false;
  templateName.value = snapshot.templateName ?? "";
  toml.value = snapshot.toml;
  // Validation is server-owned and is never trusted across a reload.
  step.value = Math.min(Math.max(snapshot.step ?? 0, 0), 1);
  validationState.value = "dirty";
  return true;
}

function clearSnapshot() {
  try {
    sessionStorage.removeItem(SNAPSHOT_KEY);
  } catch {
    // no-op
  }
}

watch([step, templateName, toml], persistSnapshot);
watch(toml, () => {
  if (validatedToml.value === toml.value && validationResult.value) {
    validationState.value = "valid";
    return;
  }
  validationState.value = toml.value.trim() ? "dirty" : "idle";
  validationError.value = "";
  createError.value = "";
  duplicateTemplate.value = null;
});

onMounted(async () => {
  const restored = restoreSnapshot();
  try {
    deviceTemplates.value = await loadDeviceTemplates();
    if (!restored && deviceTemplates.value[0]?.file_path) {
      toml.value = exampleToml(deviceTemplates.value[0].file_path);
    }
  } catch {
    // The editor remains usable; validation will report an unavailable reference.
  }
});

async function validateToml({ advance = false } = {}) {
  if (!toml.value.trim() || validationState.value === "validating") return false;
  const source = toml.value;
  validationState.value = "validating";
  validationError.value = "";
  try {
    const result = await validateSessionTemplateToml(source);
    if (toml.value !== source) return false;
    validationResult.value = result;
    validatedToml.value = source;
    validationState.value = "valid";
    if (advance && step.value === 1) step.value += 1;
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

async function createTemplate() {
  if (createDisabled.value) return;
  createState.value = "creating";
  createError.value = "";
  duplicateTemplate.value = null;
  try {
    const created = await createSessionTemplateFromToml({
      name: templateName.value.trim(),
      toml: toml.value,
    });
    clearSnapshot();
    emit("created", created.template_id);
  } catch (error) {
    createState.value = "error";
    duplicateTemplate.value = duplicateTemplateFrom(error);
    createError.value = describeError(error, "Unable to create this template.");
  }
}

async function onNext() {
  if (step.value === 0 && detailsComplete.value) {
    step.value += 1;
    return;
  }
  if (step.value === 1) {
    if (tomlIsCurrentAndValid.value) step.value += 1;
    else await validateToml({ advance: true });
    return;
  }
  if (step.value === 2) step.value += 1;
}

function onBack() {
  if (step.value === 0) {
    clearSnapshot();
    emit("cancel");
  } else {
    step.value -= 1;
  }
}
</script>

<template>
  <div class="page page--workspace create-template-page">
    <PageHeader
      eyebrow="TOML authoring"
      title="Create Template"
    />

    <BaseCard
      class="template-wizard"
      :class="{ 'template-wizard--editor': step === 1 }"
    >
      <ol class="template-wizard-steps" aria-label="Template creation progress">
        <li
          v-for="(label, index) in steps"
          :key="label"
          :class="{ active: index === step, complete: index < step }"
          :aria-label="`Step ${index + 1}: ${label}`"
          :aria-current="index === step ? 'step' : undefined"
        >
          <span class="template-wizard-step-number">
            <Check v-if="index < step" :size="13" />
            <template v-else>{{ index + 1 }}</template>
          </span>
          <span class="template-wizard-step-label">{{ label }}</span>
        </li>
      </ol>

      <section class="template-wizard-content">
        <div v-if="step === 0" class="template-step template-step--details">
          <div class="template-step-heading">
            <h2>Name the template</h2>
            <p>The name becomes the flat TOML filename in Morelia’s session-template library.</p>
          </div>
          <label class="field">
            <span>Template name</span>
            <input v-model="templateName" autofocus placeholder="e.g. bench-dual-stream" />
            <small>File preview: <code>{{ filename }}</code></small>
          </label>
        </div>

        <div v-else-if="step === 1" class="template-step">
          <div class="template-step-heading template-step-heading--split">
            <div>
              <h2>Edit as TOML</h2>
              <p>Validation resolves device-template references and checks the complete session structure without writing files.</p>
            </div>
            <span class="template-mode-badge"><FileCode2 :size="15" /> TOML only</span>
          </div>
          <TemplateTomlEditor
            v-model="toml"
            :filename="filename"
            :state="validationState"
            :error="validationError"
            :summary="summary"
            :device-templates="deviceTemplates"
            @validate="validateToml()"
          />
        </div>

        <div v-else-if="step === 2" class="template-step template-step--recovery">
          <div class="template-step-heading">
            <h2>Recovery policy</h2>
            <p>The policy is authored in TOML and shown here for confirmation.</p>
          </div>
          <BaseCard class="recovery-confirmation">
            <div>
              <span>Configured policy</span>
              <strong>{{ recoveryPolicy }}</strong>
            </div>
            <p v-if="recoveryPolicy === 'automate'">Morelia may run software-fixable recovery automatically when its preconditions allow.</p>
            <p v-else>Morelia reports software-fixable faults and waits for operator approval.</p>
            <BaseButton variant="quiet" @click="step = 1">Edit in TOML</BaseButton>
          </BaseCard>
        </div>

        <div v-else class="template-step template-step--review">
          <div class="template-step-heading">
            <h2>Review and create</h2>
            <p>The validated draft will be canonicalized and written as one registered TOML template.</p>
          </div>
          <dl class="template-review-list">
            <div><dt>Template</dt><dd>{{ templateName.trim() }}</dd></div>
            <div><dt>File</dt><dd><code>{{ filename }}</code></dd></div>
            <div><dt>Device requirements</dt><dd>{{ summary?.device_flows ?? 0 }}</dd></div>
            <div><dt>Sinks</dt><dd>{{ summary?.sinks ?? 0 }}</dd></div>
            <div><dt>Hardware preferences</dt><dd>{{ summary?.hardware_preferences ?? 0 }}</dd></div>
            <div><dt>Recovery</dt><dd>{{ recoveryPolicy }}</dd></div>
          </dl>
          <div v-if="createError" class="template-create-error" role="alert">
            <AlertTriangle :size="18" />
            <span>{{ createError }}</span>
            <button
              v-if="duplicateTemplate"
              type="button"
              class="table-action"
              @click="emit('open-existing-template', duplicateTemplate.template_id)"
            >
              Open {{ duplicateTemplate.name }}
            </button>
          </div>
        </div>
      </section>

      <footer class="template-wizard-footer">
        <BaseButton variant="quiet" @click="onBack">{{ step === 0 ? "Cancel" : "Back" }}</BaseButton>
        <div>
          <small v-if="advanceBlockedReason">{{ advanceBlockedReason }}</small>
          <BaseButton v-if="step < steps.length - 1" :disabled="step !== 1 && !canAdvance" @click="onNext">
            {{ step === 1 && !tomlIsCurrentAndValid ? "Validate & Continue" : "Continue" }}
          </BaseButton>
          <BaseButton v-else :disabled="createDisabled" @click="createTemplate">
            {{ createState === "creating" ? "Creating…" : "Create Template" }}
          </BaseButton>
        </div>
      </footer>
    </BaseCard>
  </div>
</template>

<style scoped>
.create-template-page { overflow-y: auto; scrollbar-gutter: stable; }
.create-template-page :deep(.page-header h1) { margin-top: 0; font-size: var(--fs-h2); }
.create-template-page,
.template-wizard--editor .template-wizard-content { scrollbar-color: var(--sage-400) var(--sage-100); scrollbar-width: thin; }
.create-template-page::-webkit-scrollbar,
.template-wizard--editor .template-wizard-content::-webkit-scrollbar { width: 10px; }
.create-template-page::-webkit-scrollbar-track,
.template-wizard--editor .template-wizard-content::-webkit-scrollbar-track { background: var(--sage-100); }
.create-template-page::-webkit-scrollbar-thumb,
.template-wizard--editor .template-wizard-content::-webkit-scrollbar-thumb { border: 2px solid var(--sage-100); border-radius: var(--radius-pill); background: var(--sage-400); }
.create-template-page > .template-wizard { display: grid; min-height: 0; flex: 0 0 auto; grid-template-columns: 116px minmax(0, 1fr); grid-template-rows: minmax(0, 1fr) auto; overflow: hidden; }
.create-template-page > .template-wizard--editor { flex: 1 1 auto; }
.template-wizard-steps { display: flex; min-height: 0; grid-column: 1; grid-row: 1 / -1; flex-direction: column; margin: 0; padding: var(--space-3); list-style: none; border-right: 1px solid var(--border-card); background: #f7f9f7; }
.template-wizard-steps li { position: relative; display: flex; min-width: 0; flex: 1 1 0; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-1); color: var(--text-muted); font-family: var(--font-display); font-size: var(--fs-xs); font-weight: var(--fw-bold); text-align: center; }
.template-wizard-steps li::after { position: absolute; z-index: 0; top: calc(50% + 24px); left: calc(50% - 1px); width: 2px; height: calc(100% - 48px); content: ""; background: var(--sage-200); }
.template-wizard-steps li:last-child::after { display: none; }
.template-wizard-steps li.complete::after { background: var(--accent); }
.template-wizard-steps li.active { color: var(--text-heading); }
.template-wizard-steps li.complete { color: var(--text-accent); }
.template-wizard-step-number { position: relative; z-index: 1; width: 26px; height: 26px; display: grid; place-items: center; flex: 0 0 auto; border: 1px solid var(--sage-300); border-radius: var(--radius-pill); color: var(--text-accent); background: var(--surface-card); font: 0.68rem var(--font-mono); }
.complete .template-wizard-step-number, .active .template-wizard-step-number { color: white; border-color: var(--accent); background: var(--accent); }
.template-wizard-content { min-height: 0; grid-column: 2; grid-row: 1; padding: var(--space-5); }
.template-wizard--editor .template-wizard-content { flex: 1 1 auto; overflow-y: auto; scrollbar-gutter: stable; }
.template-step { display: grid; gap: var(--space-5); }
.template-step-heading { padding-top: var(--space-2); border-top: var(--rule-width) solid var(--accent-rule); }
.template-step-heading--split { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); }
.template-step-heading h2 { color: var(--text-heading); font-size: var(--fs-h3); }
.template-step-heading p { max-width: 760px; margin-top: var(--space-2); color: var(--text-muted); font-size: var(--fs-sm); }
.template-mode-badge { display: inline-flex; align-items: center; gap: var(--space-2); padding: 0.4rem 0.65rem; border: 1px solid var(--sage-300); border-radius: var(--radius-pill); color: var(--text-accent); background: var(--sage-50); font-size: var(--fs-xs); font-weight: var(--fw-bold); white-space: nowrap; }
.template-step--details { width: 100%; }
.template-step--details .field { display: grid; gap: var(--space-2); margin-top: var(--space-5); }
.template-step--details .field > span { color: var(--text-accent); font-family: var(--font-display); font-size: var(--fs-xs); font-weight: var(--fw-bold); letter-spacing: var(--ls-wide); text-transform: uppercase; }
.template-step--details input { min-height: 46px; padding: 0 var(--space-4); border: 1px solid var(--sage-300); border-radius: var(--radius-sm); background: var(--surface-card); }
.template-step--details small { color: var(--text-muted); }
.template-step--recovery, .template-step--review { width: 100%; }
.recovery-confirmation { display: grid; grid-template-columns: minmax(160px, 0.4fr) minmax(0, 1fr) auto; align-items: center; gap: var(--space-5); padding: var(--space-5); border-left: var(--border-accent) solid var(--accent); }
.recovery-confirmation span { display: block; color: var(--text-muted); font-size: var(--fs-xs); }
.recovery-confirmation strong { display: block; margin-top: var(--space-1); color: var(--text-heading); font-size: var(--fs-h4); text-transform: capitalize; }
.recovery-confirmation p { color: var(--text-body); font-size: var(--fs-sm); }
.template-review-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid var(--border-card); border-radius: var(--radius-md); overflow: hidden; }
.template-review-list div { padding: var(--space-4); border-top: 1px solid var(--border-card); }
.template-review-list div:nth-child(-n + 2) { border-top: 0; }
.template-review-list div:nth-child(even) { border-left: 1px solid var(--border-card); }
.template-review-list dt { color: var(--text-muted); font-family: var(--font-display); font-size: 0.68rem; font-weight: var(--fw-bold); letter-spacing: var(--ls-wide); text-transform: uppercase; }
.template-review-list dd { margin-top: var(--space-2); color: var(--text-heading); font-weight: var(--fw-semibold); }
.template-create-error { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-4); border: 1px solid #dfaaa6; border-radius: var(--radius-md); color: var(--error); background: #faf0ef; }
.template-create-error span { flex: 1; }
.template-wizard-footer { display: flex; grid-column: 2; grid-row: 2; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-4) var(--space-5); border-top: 1px solid var(--border-card); background: #fafbfa; }
.template-wizard-footer > div { display: flex; align-items: center; justify-content: flex-end; gap: var(--space-3); }
.template-wizard-footer small { max-width: 320px; color: var(--text-muted); font-size: var(--fs-xs); text-align: right; }
@media (max-width: 760px) { .create-template-page > .template-wizard { grid-template-columns: 68px minmax(0, 1fr); } .template-wizard-steps { padding-inline: var(--space-3); } .template-wizard-steps li::after { top: calc(50% + 16px); height: calc(100% - 32px); } .template-wizard-step-label { display: none; } .template-wizard-content { padding: var(--space-4); } .recovery-confirmation { grid-template-columns: 1fr; } }
@media (max-width: 540px) { .template-step-heading--split, .template-wizard-footer, .template-wizard-footer > div { align-items: stretch; flex-direction: column; } .template-wizard-footer small { max-width: none; text-align: left; } .template-review-list { grid-template-columns: 1fr; } .template-review-list div, .template-review-list div:nth-child(even) { border-top: 1px solid var(--border-card); border-left: 0; } .template-review-list div:first-child { border-top: 0; } }
</style>
