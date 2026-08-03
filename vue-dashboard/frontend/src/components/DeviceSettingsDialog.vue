<script setup>
import { computed, onMounted, ref } from "vue";
import { X } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import StatusBadge from "./StatusBadge.vue";
import {
  createDeviceConfig,
  createDeviceConfigFromTemplate,
  editDeviceConfig,
  loadDeviceConfig,
  matchDeviceTemplate,
  registerDeviceName,
} from "../devices-api";
import { createDeviceTemplate, loadDeviceTemplates } from "../templates-api";

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

// Edit mode: the persisted config and its parameters as typed, editable rows.
const config = ref(null);
const paramRows = ref([]);

// Create mode: pick an existing template or author raw parameters.
const createSource = ref("template"); // template | custom
const templates = ref([]);
const selectedTemplateName = ref("");
const rawParameters = ref("{}");

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
  templatesForType.value.find((template) => template.name === selectedTemplateName.value) ?? null,
);

function normalizePath(value) {
  if (!value) return "";
  return String(value).replace(/\\/g, "/").replace(/^device-templates\//, "").replace(/\.toml$/i, "");
}

// Split matches into "the template this config already points at" vs. others.
const otherMatches = computed(() => {
  const current = normalizePath(currentSourceTemplate.value);
  return (matchResult.value?.matches ?? []).filter(
    (template) => normalizePath(template.file_path) !== current,
  );
});

const decisionKind = computed(() => {
  if (matchError.value) return "error";
  if (otherMatches.value.length) return "match";
  return "unique";
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
    }
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
  const nickname = name.value.trim() || null;

  if (createSource.value === "template") {
    if (!selectedTemplateName.value) throw new Error("Pick a device template first.");
    await createDeviceConfigFromTemplate({
      template_name: selectedTemplateName.value,
      hardware_id: hardwareId.value.trim(),
      port: port.value.trim(),
      nickname,
    });
    emit("saved");
    return;
  }

  // Custom create: persist the config, then offer to capture it as a template.
  let parameters;
  try {
    parameters = JSON.parse(rawParameters.value || "{}");
  } catch {
    throw new Error("Parameters must be valid JSON.");
  }
  const created = await createDeviceConfig({
    type: deviceType.value,
    hardware_id: hardwareId.value.trim(),
    port: port.value.trim(),
    parameters,
    nickname,
  });
  currentSourceTemplate.value = null;
  await beginDecision(created.id, parameters, { skipRename: true });
}

// Ask the backend which templates (if any) the parameters already match, then
// move to the decision step. On a "no change" result we save straight through.
async function beginDecision(configId, parameters, { skipRename = false } = {}) {
  targetConfigId.value = configId;
  if (!skipRename) await renameIfChanged();

  try {
    matchResult.value = await matchDeviceTemplate({ type: deviceType.value, parameters });
    matchError.value = "";
  } catch (reason) {
    matchResult.value = null;
    matchError.value = reason instanceof Error ? reason.message : "Template matching is unavailable.";
    step.value = "decision";
    return;
  }

  const matches = matchResult.value?.matches ?? [];
  const current = normalizePath(currentSourceTemplate.value);
  const onlyCurrent = matches.length > 0 && matches.every((t) => normalizePath(t.file_path) === current);
  if (onlyCurrent) {
    // Parameters still equal the linked template — nothing to decide. Keep the
    // link via the existing `update_source_template` contract (a no-op rewrite of
    // the identical template), so this path does not depend on the D-04 relink.
    await commit({ parameters, update_source_template: true });
    return;
  }

  switchTargetPath.value = otherMatches.value[0]?.file_path ?? "";
  decisionChoice.value = otherMatches.value.length ? "switch" : "new";
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
    const parameters =
      mode === "create" ? JSON.parse(rawParameters.value || "{}") : buildParametersFromRows();

    if (decisionChoice.value === "switch") {
      if (!switchTargetPath.value) throw new Error("Pick a template to switch to.");
      await commit({ parameters, source_template: switchTargetPath.value });
    } else if (decisionChoice.value === "new") {
      const templateName = newTemplateName.value.trim();
      if (!templateName) throw new Error("Enter a name for the new template.");
      const created = await createDeviceTemplate({ name: templateName, type: deviceType.value, parameters });
      await commit({ parameters, source_template: created.file_path ?? created.name });
    } else {
      // Keep as a custom config with no template link.
      await commit({ parameters, update_source_template: false });
    }
  } catch (reason) {
    errorMsg.value = reason instanceof Error ? reason.message : "Could not apply the change.";
  } finally {
    busy.value = false;
  }
}

// Fallback when the match endpoint is unavailable: save params, drop the link.
async function onSaveWithoutMatching() {
  errorMsg.value = "";
  busy.value = true;
  try {
    const parameters =
      mode === "create" ? JSON.parse(rawParameters.value || "{}") : buildParametersFromRows();
    await commit({ parameters, update_source_template: false });
  } catch (reason) {
    errorMsg.value = reason instanceof Error ? reason.message : "Save failed.";
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

          <!-- Edit: typed parameter rows -->
          <template v-if="mode === 'edit'">
            <div class="field field--wide">
              <span>Source template</span>
              <p class="device-dialog__source"><code>{{ currentSourceTemplate ?? "Custom (no template)" }}</code></p>
            </div>
            <p v-if="!paramRows.length" class="empty-state">This config has no editable parameters.</p>
            <div v-else class="form-grid">
              <label v-for="row in paramRows" :key="row.key" class="field" :class="{ 'field--wide': row.type === 'json' }">
                <span>{{ row.key }}</span>
                <select v-if="row.type === 'boolean'" v-model="row.value">
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
                <input v-else-if="row.type === 'number'" v-model="row.value" type="number" step="any" />
                <textarea v-else-if="row.type === 'json'" v-model="row.value" spellcheck="false" />
                <input v-else v-model="row.value" type="text" />
              </label>
            </div>
          </template>

          <!-- Create: template picker or raw JSON -->
          <template v-else>
            <div class="field field--wide">
              <span>Configure from</span>
              <div class="device-dialog__toggle">
                <label><input v-model="createSource" type="radio" value="template" /> Existing template</label>
                <label><input v-model="createSource" type="radio" value="custom" /> Custom parameters</label>
              </div>
            </div>
            <label v-if="createSource === 'template'" class="field field--wide">
              <span>Device template</span>
              <select v-model="selectedTemplateName">
                <option value="" disabled>Select a {{ device.type }} template…</option>
                <option v-for="template in templatesForType" :key="template.name" :value="template.name">{{ template.name }}</option>
              </select>
              <small v-if="!templatesForType.length">No templates exist for this device type yet.</small>
              <pre v-if="selectedTemplate" class="device-dialog__preview">{{ JSON.stringify(selectedTemplate.content?.parameters ?? {}, null, 2) }}</pre>
            </label>
            <label v-else class="field field--wide">
              <span>Parameters (JSON)</span>
              <textarea v-model="rawParameters" spellcheck="false" rows="6" />
            </label>
          </template>
        </div>

        <!-- Decision step -->
        <div v-else class="dialog-form">
          <div v-if="decisionKind === 'error'" class="dialog-notice">
            <strong>Couldn't check templates.</strong>
            <p>{{ matchError }}</p>
            <p>Save the parameters anyway? The device will keep no template link.</p>
          </div>
          <div v-else-if="decisionKind === 'match'" class="dialog-notice">
            <strong>These settings match an existing device template.</strong>
            <p>Switch this device to that template, or capture the settings as a new one.</p>
          </div>
          <div v-else class="dialog-notice">
            <strong>These settings are unique.</strong>
            <p>They don't match any existing device template. Save them as a new template, or keep this device as a custom config.</p>
          </div>

          <template v-if="decisionKind !== 'error'">
            <label v-if="decisionKind === 'match'" class="field field--wide">
              <span><input v-model="decisionChoice" type="radio" value="switch" /> Switch to existing template</span>
              <select v-model="switchTargetPath" :disabled="decisionChoice !== 'switch'">
                <option v-for="template in otherMatches" :key="template.file_path" :value="template.file_path">{{ template.name }} — {{ template.file_path }}</option>
              </select>
            </label>

            <label class="field field--wide">
              <span><input v-model="decisionChoice" type="radio" value="new" /> Make a new template</span>
              <input v-model="newTemplateName" type="text" placeholder="New template name" :disabled="decisionChoice !== 'new'" />
            </label>

            <label class="field field--wide">
              <span><input v-model="decisionChoice" type="radio" value="custom" /> Keep as a custom config (no template link)</span>
            </label>
          </template>
        </div>

        <p v-if="errorMsg" class="validation-copy" role="alert">{{ errorMsg }}</p>
      </div>

      <footer>
        <BaseButton variant="secondary" :disabled="busy" @click="step === 'decision' && mode !== 'create' ? (step = 'form') : $emit('close')">
          {{ step === "decision" && mode !== "create" ? "Back" : "Cancel" }}
        </BaseButton>
        <BaseButton v-if="loadState === 'ready' && step === 'form'" :disabled="busy" @click="onSave">
          {{ mode === "create" ? "Create config" : "Save" }}
        </BaseButton>
        <BaseButton v-else-if="step === 'decision' && decisionKind === 'error'" :disabled="busy" @click="onSaveWithoutMatching">Save parameters</BaseButton>
        <BaseButton v-else-if="step === 'decision'" :disabled="busy" @click="onDecide">Apply</BaseButton>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.device-dialog { width: min(720px, 100%); }
.device-dialog__badges { display: flex; gap: var(--space-2); margin-top: var(--space);}
.device-dialog__toggle { display: flex; gap: 1.2rem; font-size: 0.8rem; }
.device-dialog__toggle label { display: flex; align-items: center; gap: 0.4rem; font-weight: 600; }
.device-dialog__source { margin: 0; }
.device-dialog__source code, .device-dialog__preview { overflow-wrap: anywhere; }
.device-dialog__preview { max-height: 180px; overflow: auto; margin: 0; padding: var(--space-3); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-muted); font: 0.72rem var(--font-mono); }
.device-dialog .field span { display: flex; align-items: center; gap: 0.4rem; }
</style>
