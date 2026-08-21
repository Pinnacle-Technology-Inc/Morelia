<script setup>
import { computed, onMounted, ref } from "vue";
import { X } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import StatusBadge from "./StatusBadge.vue";
import {
  createDeviceConfigFromTemplate,
  editDeviceConfig,
  loadDeviceConfig,
  registerDeviceName,
} from "../devices-api";
import {
  createDeviceTemplate,
  loadDeviceTemplateSource,
  loadDeviceTemplates,
  matchDeviceTemplate,
} from "../templates-api";

const props = defineProps({
  // A device-pool row (from loadDevicePool). `configId` is set for configured
  // devices; unconfigured devices open this dialog in create mode.
  device: { type: Object, required: true },
});
const emit = defineEmits(["close", "saved"]);

const mode = props.device.configId != null ? "edit" : "create";

const loadState = ref("loading"); // loading | ready | error
const loadError = ref("");
const busy = ref(false);
const errorMsg = ref("");

// Identity + name.
const name = ref(props.device.nickname ?? "");
const hardwareId = ref(props.device.hardwareId ?? "");
const port = ref(props.device.port ?? "");

// Persisted parameters stay typed internally for save/template matching while
// the operator sees the canonical TOML source as one read-only document.
const config = ref(null);
const paramRows = ref([]);
const templateSource = ref("");
const templateSourceState = ref("idle"); // idle | loading | ready | error
const templateSourceError = ref("");

// Every dashboard-managed config starts from, and finishes linked to, a template.
const templates = ref([]);
const selectedTemplateReference = ref("");

// Decision step (shown after Save on edit / custom-create).
const step = ref("form"); // form | decision
const matchResult = ref(null); // { content_hash, matches: [] }
const matchError = ref("");
const targetConfigId = ref(null); // config the decision will relink
const currentSourceTemplate = ref(null);
const decisionChoice = ref(""); // "" | switch | new | custom
const switchTargetPath = ref("");
const newTemplateName = ref("");

const deviceType = computed(() => props.device.type);

const templatesForType = computed(() =>
  templates.value.filter((template) => template.type === deviceType.value),
);

const selectedTemplate = computed(() =>
  templatesForType.value.find((template) => normalizePath(template.file_path) === normalizePath(selectedTemplateReference.value)) ?? null,
);

function normalizePath(value) {
  if (!value) return "";
  return String(value).replace(/\\/g, "/").replace(/^device-templates\//, "").replace(/\.toml$/i, "");
}

function templateReference(template) {
  return template?.file_path?.split(/[\\/]/).pop()?.replace(/\.toml$/i, "") ?? template?.name ?? "";
}

// Split matches into "the template this config already points at" vs. others.
const matchingTemplates = computed(() => matchResult.value?.matches ?? []);

const decisionKind = computed(() => {
  if (matchError.value) return "error";
  if (matchingTemplates.value.length) return "match";
  return "unique";
});

const canApplyDecision = computed(() => {
  if (busy.value || decisionKind.value === "error") return false;
  if (decisionChoice.value === "switch") return Boolean(switchTargetPath.value);
  if (decisionChoice.value === "new") return Boolean(newTemplateName.value.trim());
  return false;
});

function classifyRow(key, value) {
  if (typeof value === "boolean") return { key, type: "boolean", value: String(value) };
  if (typeof value === "number") return { key, type: "number", value: String(value) };
  if (typeof value === "string") return { key, type: "string", value };
  return { key, type: "json", value: JSON.stringify(value) };
}

// Rebuild a parameters object from the form, throwing a friendly error if a
// JSON-typed field is malformed.
function buildParametersFromRows() {
  const out = {};
  for (const row of paramRows.value) {
    const key = row.key.trim();
    if (!key) continue;
    if (row.type === "number") {
      out[key] = row.value === "" ? null : Number(row.value);
    } else if (row.type === "boolean") {
      out[key] = row.value === "true" || row.value === true;
    } else if (row.type === "json") {
      try {
        out[key] = JSON.parse(row.value);
      } catch {
        throw new Error(`“${key}” is not valid JSON.`);
      }
    } else {
      out[key] = row.value;
    }
  }
  return out;
}

function useTemplateParameters(template) {
  const parameters = template?.content?.parameters ?? {};
  paramRows.value = Object.keys(parameters)
    .sort()
    .map((key) => classifyRow(key, parameters[key]));
}

async function loadSelectedTemplateSource() {
  const reference = selectedTemplateReference.value;
  if (!reference) {
    templateSource.value = "";
    templateSourceState.value = "idle";
    templateSourceError.value = "";
    return;
  }

  templateSourceState.value = "loading";
  templateSourceError.value = "";
  try {
    const loaded = await loadDeviceTemplateSource(reference);
    if (reference !== selectedTemplateReference.value) return;
    templateSource.value = loaded.toml;
    templateSourceState.value = "ready";
  } catch (reason) {
    if (reference !== selectedTemplateReference.value) return;
    templateSource.value = "";
    templateSourceState.value = "error";
    templateSourceError.value = reason instanceof Error ? reason.message : "Could not load the device template source.";
  }
}

async function selectTemplate() {
  useTemplateParameters(selectedTemplate.value);
  errorMsg.value = "";
  await loadSelectedTemplateSource();
}

onMounted(async () => {
  try {
    const [templateList, loadedConfig] = await Promise.all([
      loadDeviceTemplates().catch(() => []),
      mode === "edit" ? loadDeviceConfig(props.device.configId) : Promise.resolve(null),
    ]);
    templates.value = Array.isArray(templateList) ? templateList : [];
    if (mode === "edit") {
      config.value = loadedConfig;
      currentSourceTemplate.value = loadedConfig?.source_template ?? null;
      const parameters = loadedConfig?.parameters ?? {};
      paramRows.value = Object.keys(parameters)
        .sort()
        .map((key) => classifyRow(key, parameters[key]));
      name.value = loadedConfig?.nickname ?? name.value;
      port.value = loadedConfig?.port ?? port.value;
      hardwareId.value = loadedConfig?.hardware_id ?? hardwareId.value;
      selectedTemplateReference.value = templatesForType.value.find(
        (template) => normalizePath(template.file_path) === normalizePath(currentSourceTemplate.value),
      )?.file_path ?? templatesForType.value[0]?.file_path ?? "";
    } else {
      selectedTemplateReference.value = templatesForType.value[0]?.file_path ?? "";
      useTemplateParameters(selectedTemplate.value);
    }
    await loadSelectedTemplateSource();
    loadState.value = "ready";
  } catch (reason) {
    loadState.value = "error";
    loadError.value = reason instanceof Error ? reason.message : "Could not load device settings.";
  }
});

async function renameIfChanged() {
  const trimmed = name.value.trim();
  if (!trimmed || trimmed === (props.device.nickname ?? "")) return;
  if (!hardwareId.value) return;
  await registerDeviceName({ type: deviceType.value, hardware_id: hardwareId.value, nickname: trimmed });
}

// --- Save from the form -----------------------------------------------------

async function onSave() {
  errorMsg.value = "";
  busy.value = true;
  try {
    if (mode === "create") {
      await onCreate();
    } else {
      await beginDecision(props.device.configId, buildParametersFromRows());
    }
  } catch (reason) {
    errorMsg.value = reason instanceof Error ? reason.message : "Save failed.";
  } finally {
    busy.value = false;
  }
}

async function onCreate() {
  if (!hardwareId.value.trim()) throw new Error("Hardware ID is required to create a config.");
  if (!port.value.trim()) throw new Error("Port is required to create a config.");
  if (!selectedTemplateReference.value) throw new Error("Pick a device template first.");
  await beginDecision(null, buildParametersFromRows());
}

// Ask the backend which templates (if any) the parameters already match, then
// move to the decision step. On a "no change" result we save straight through.
async function beginDecision(configId, parameters) {
  targetConfigId.value = configId;

  try {
    matchResult.value = await matchDeviceTemplate({ type: deviceType.value, parameters });
    matchError.value = "";
  } catch (reason) {
    matchResult.value = null;
    matchError.value = reason instanceof Error ? reason.message : "Template matching is unavailable.";
    step.value = "decision";
    return;
  }

  switchTargetPath.value = matchingTemplates.value[0]?.file_path ?? "";
  decisionChoice.value = matchingTemplates.value.length ? "switch" : "new";
  step.value = "decision";
}

// --- Execute the chosen decision -------------------------------------------

async function commit(patch) {
  await editDeviceConfig(targetConfigId.value, patch);
  emit("saved");
}

async function onDecide() {
  errorMsg.value = "";
  busy.value = true;
  try {
    const parameters = buildParametersFromRows();
    let targetTemplate = null;

    if (decisionChoice.value === "switch") {
      if (!switchTargetPath.value) throw new Error("Pick a template to switch to.");
      targetTemplate = matchingTemplates.value.find((template) => template.file_path === switchTargetPath.value) ?? null;
    } else if (decisionChoice.value === "new") {
      const templateName = newTemplateName.value.trim();
      if (!templateName) throw new Error("Enter a name for the new template.");
      targetTemplate = await createDeviceTemplate({ name: templateName, type: deviceType.value, parameters });
    }
    if (!targetTemplate) throw new Error("Choose a matching template or create a new one.");

    if (mode === "create") {
      await createDeviceConfigFromTemplate({
        template_name: templateReference(targetTemplate),
        hardware_id: hardwareId.value.trim(),
        port: port.value.trim(),
        nickname: name.value.trim() || null,
      });
      emit("saved");
    } else {
      await renameIfChanged();
      await commit({ parameters, source_template: targetTemplate.file_path ?? targetTemplate.name });
    }
  } catch (reason) {
    errorMsg.value = reason instanceof Error ? reason.message : "Could not apply the change.";
  } finally {
    busy.value = false;
  }
}

function displayLabel(value) {
  return { available: "Available", not_found: "Not found", unopenable: "Unopenable", free: "Free", claimed: "Claimed", unconfigured: "Unconfigured" }[value] ?? value;
}
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="$emit('close')">
    <section class="dialog device-dialog" role="dialog" aria-modal="true" :aria-label="`${device.name} settings`">
      <header>
        <div>
          <h2>{{ mode === "create" ? "Create device config" : "Device settings" }}</h2>
          
          <div class="device-dialog__badges">
        
            <p>{{ device.name }} · <code>{{ device.type }}</code></p>
            <StatusBadge compact :value="displayLabel(device.availability)" />
            <StatusBadge compact :value="displayLabel(device.status)" />
          </div>
        </div>
        <button class="icon-button" type="button" aria-label="Close dialog" @click="$emit('close')"><X :size="19" /></button>
      </header>

      <div class="dialog__content">
        <p v-if="loadState === 'loading'" class="empty-state" aria-busy="true">Loading settings…</p>
        <p v-else-if="loadState === 'error'" class="empty-state" role="alert">{{ loadError }}</p>

        <!-- Settings / create form -->
        <div v-else-if="step === 'form'" class="dialog-form">
          

          <div class="form-grid">
            <label class="field">
              <span>Name</span>
              <input v-model="name" type="text" placeholder="Operator name" :disabled="!hardwareId" />
            </label>
            <label class="field">
              <span>Hardware ID</span>
              <input v-model="hardwareId" type="text" :readonly="mode === 'edit'" placeholder="FTDI serial" />
            </label>
            <label class="field">
              <span>Port</span>
              <input v-model="port" type="text" :readonly="mode === 'edit'" />
            </label>
            <label class="field">
              <span>Type</span>
              <input :value="device.type" type="text" readonly />
            </label>
          </div>

          <label class="field field--wide">
            <span>{{ mode === "edit" ? "Current template" : "Start from template" }}</span>
            <select v-model="selectedTemplateReference" @change="selectTemplate">
              <option value="" disabled>Select a {{ device.type }} template…</option>
              <option v-for="template in templatesForType" :key="template.file_path" :value="template.file_path">{{ template.name }} — {{ template.file_path }}</option>
            </select>
            <small v-if="mode === 'edit'">Currently linked to <code>{{ currentSourceTemplate ?? "no template" }}</code>. Choosing another template loads its canonical values below.</small>
            <small v-if="!templatesForType.length">No templates exist for this device type. Create one from Templates before configuring this device.</small>
          </label>
          <div v-if="selectedTemplateReference" class="device-toml field--wide">
            <div class="device-toml__header">
              <span>Template TOML</span>
              <code>{{ selectedTemplate?.file_path ?? selectedTemplateReference }}</code>
            </div>
            <p v-if="templateSourceState === 'loading'" class="device-toml__state" aria-busy="true">Loading TOML source…</p>
            <p v-else-if="templateSourceState === 'error'" class="device-toml__state" role="alert">{{ templateSourceError }}</p>
            <pre v-else class="device-toml__source" tabindex="0" aria-label="Read-only device template TOML"><code>{{ templateSource }}</code></pre>
          </div>
        </div>

        <!-- Decision step -->
        <div v-else class="dialog-form">
          <div v-if="decisionKind === 'error'" class="dialog-notice">
            <strong>Couldn't check templates.</strong>
            <p>{{ matchError }}</p>
            <p>The settings were not saved because dashboard-managed devices must remain linked to a template.</p>
          </div>
          <div v-else-if="decisionKind === 'match'" class="dialog-notice">
            <strong>These settings match an existing device template.</strong>
            <p>The canonical hash matches an existing template. Link the device to that template.</p>
          </div>
          <div v-else class="dialog-notice">
            <strong>These settings are unique.</strong>
            <p>They don't match any existing device template. Name a new template to save and link these values.</p>
          </div>

          <template v-if="decisionKind !== 'error'">
            <label v-if="decisionKind === 'match'" class="field field--wide">
              <span><input v-model="decisionChoice" type="radio" value="switch" /> Link to matching template</span>
              <select v-model="switchTargetPath" :disabled="decisionChoice !== 'switch'">
                <option v-for="template in matchingTemplates" :key="template.file_path" :value="template.file_path">{{ template.name }} — {{ template.file_path }}</option>
              </select>
            </label>

            <label class="field field--wide">
              <span><input v-model="decisionChoice" type="radio" value="new" /> Make a new template</span>
              <input v-model="newTemplateName" type="text" placeholder="New template name" :disabled="decisionChoice !== 'new'" />
            </label>

          </template>
        </div>

        <p v-if="errorMsg" class="validation-copy" role="alert">{{ errorMsg }}</p>
      </div>

      <footer>
        <BaseButton variant="secondary" :disabled="busy" @click="step === 'decision' && mode !== 'create' ? (step = 'form') : $emit('close')">
          {{ step === "decision" && mode !== "create" ? "Back" : "Cancel" }}
        </BaseButton>
        <BaseButton v-if="loadState === 'ready' && step === 'form'" :disabled="busy || !selectedTemplateReference" @click="onSave">
          {{ mode === "create" ? "Create config" : "Save" }}
        </BaseButton>
        <BaseButton v-else-if="step === 'decision' && decisionKind !== 'error'" :disabled="!canApplyDecision" @click="onDecide">Apply</BaseButton>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.device-dialog { width: min(720px, 100%); }
.device-dialog__badges { display: flex; gap: var(--space-2); margin-top: var(--space);}
.device-dialog .field span { display: flex; align-items: center; gap: 0.4rem; }
.device-dialog input[type="radio"] { width: auto; min-height: auto; }
.device-toml { display: grid; min-width: 0; gap: var(--space-2); }
.device-toml__header { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-3); }
.device-toml__header span { color: var(--text-heading); font-size: var(--fs-sm); font-weight: var(--fw-bold); }
.device-toml__header code { color: var(--text-muted); overflow-wrap: anywhere; text-align: right; }
.device-toml__source,
.device-toml__state {
  min-height: 280px;
  margin: 0;
  padding: var(--space-4);
  overflow: auto;
  color: #edf6f0;
  border: 1px solid var(--green-950);
  border-radius: var(--radius-md);
  background: #10271a;
  font: var(--fs-xs)/1.65 var(--font-mono);
  white-space: pre;
  tab-size: 2;
}
.device-toml__source:focus-visible { outline: 2px solid var(--yellow-300); outline-offset: 2px; }
.device-toml__state { display: grid; place-items: center; color: var(--text-on-dark-muted); white-space: normal; }
@media (max-width: 560px) {
  .device-toml__header { align-items: flex-start; flex-direction: column; }
  .device-toml__header code { text-align: left; }
}
</style>
