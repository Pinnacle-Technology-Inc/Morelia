<script setup>
import { computed, nextTick, onMounted, ref } from "vue";
import { AlertTriangle, X } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import DeviceTemplateStatusIcon from "./DeviceTemplateStatusIcon.vue";
import { loadDeviceTemplateSource, validateDeviceTemplateToml } from "../templates-api";
import { formatCentralTimestamp } from "../datetime";

const props = defineProps({ template: { type: Object, required: true } });
const emit = defineEmits(["close", "delete", "repair", "validated"]);

const dialog = ref(null);
const validating = ref(false);
const validationError = ref(props.template.validation_error ?? "");
const displayedStatus = ref(props.template.status ?? "NEEDS_VALIDATION");

const statusLabel = computed(() => ({
  VALID: "Valid",
  NEEDS_VALIDATION: "Needs validation",
  INVALID: "Invalid",
}[displayedStatus.value] ?? "Needs validation"));

const parameters = computed(() => Object.entries(props.template.content?.parameters ?? {})
  .sort(([left], [right]) => left.localeCompare(right)));

const reference = computed(() => props.template.file_path ?? props.template.name);

function formatValue(value) {
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function formatModified(value) {
  return formatCentralTimestamp(value, { fallback: "Unavailable", second: undefined });
}

function describeError(error, fallback) {
  return error?.problem?.detail ?? error?.problem?.message ?? error?.message ?? fallback;
}

async function validate() {
  validating.value = true;
  validationError.value = "";
  try {
    const source = await loadDeviceTemplateSource(reference.value);
    const result = await validateDeviceTemplateToml(source.toml);
    displayedStatus.value = "VALID";
    emit("validated", {
      ...props.template,
      status: "VALID",
      validation_error: null,
      content: result.content,
      type: result.content?.type ?? props.template.type,
    });
  } catch (error) {
    displayedStatus.value = "INVALID";
    validationError.value = describeError(error, "This device template is invalid.");
    emit("validated", { ...props.template, status: "INVALID", validation_error: validationError.value });
  } finally {
    validating.value = false;
  }
}

onMounted(async () => {
  await nextTick();
  dialog.value?.focus();
});
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="emit('close')">
    <section
      ref="dialog"
      class="dialog device-template-inspector"
      role="dialog"
      aria-modal="true"
      aria-labelledby="device-template-inspector-title"
      tabindex="-1"
      @keydown.esc="emit('close')"
    >
      <header>
        <div>
          <h2 id="device-template-inspector-title">Device template</h2>
          <p><strong>{{ template.name }}</strong> · <code>{{ template.type || "Unknown type" }}</code></p>
        </div>
        <button type="button" class="icon-button" aria-label="Close device template" @click="emit('close')">
          <X :size="19" />
        </button>
      </header>

      <div class="dialog__content">
        <table class="inspector-table">
          <tbody>
            <tr class="inspector-table__section"><th colspan="2">Validation</th></tr>
            <tr>
              <th scope="row">Status</th>
              <td class="inspector-status">
                <DeviceTemplateStatusIcon :status="displayedStatus" />
                <span>{{ statusLabel }}</span>
              </td>
            </tr>
            <tr v-if="validationError">
              <th scope="row">Issue</th>
              <td class="inspector-error"><AlertTriangle :size="16" aria-hidden="true" /> {{ validationError }}</td>
            </tr>

            <tr class="inspector-table__section"><th colspan="2">Template details</th></tr>
            <tr><th scope="row">Name</th><td>{{ template.name }}</td></tr>
            <tr><th scope="row">Device type</th><td><code>{{ template.type || "Unavailable" }}</code></td></tr>
            <tr><th scope="row">File path</th><td><code>{{ template.file_path }}</code></td></tr>
            <tr><th scope="row">Modified</th><td>{{ formatModified(template.modified_at ?? template.created_at) }}</td></tr>

            <tr class="inspector-table__section"><th colspan="2">Parameters</th></tr>
            <tr v-for="([key, value]) in parameters" :key="key">
              <th scope="row"><code>{{ key }}</code></th>
              <td><code>{{ formatValue(value) }}</code></td>
            </tr>
            <tr v-if="!parameters.length"><th scope="row">Parameters</th><td>None available</td></tr>
          </tbody>
        </table>
      </div>

      <footer>
        <BaseButton variant="danger" @click="emit('delete', template)">Delete template</BaseButton>
        <span class="device-template-inspector__spacer" />
        <BaseButton variant="secondary" :disabled="validating" @click="validate">
          {{ validating ? "Validating…" : "Validate" }}
        </BaseButton>
        <BaseButton v-if="displayedStatus === 'INVALID'" @click="emit('repair', template)">
          Repair template
        </BaseButton>
        <BaseButton v-else @click="emit('close')">Done</BaseButton>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.device-template-inspector {
  width: min(720px, 100%);
  max-height: calc(100vh - 2rem);
  display: flex;
  flex-direction: column;
}

.device-template-inspector:focus { outline: none; }
.device-template-inspector .dialog__content { overflow: auto; padding: var(--space-5); }
.device-template-inspector__spacer { flex: 1; }

.inspector-table {
  width: 100%;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--border-card);
  border-collapse: separate;
  border-spacing: 0;
  border-radius: var(--radius-md);
}

.inspector-table tbody tr { cursor: default; }

.inspector-table th,
.inspector-table td {
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--border-card);
  background: var(--surface-card);
  text-align: left;
  text-transform: none;
  letter-spacing: normal;
}

.inspector-table tr:first-child th { border-top: 0; }
.inspector-table th[scope="row"] {
  width: 32%;
  color: var(--text-muted);
  font: var(--fw-semibold) var(--fs-xs) var(--font-body);
}

.inspector-table__section th {
  color: var(--text-accent);
  background: var(--surface-sage);
  font: var(--fw-bold) var(--fs-xs) var(--font-display);
  text-transform: uppercase;
  letter-spacing: var(--ls-wide);
}

.inspector-status { display: flex; align-items: center; gap: var(--space-2); font-weight: var(--fw-bold); }
.inspector-error { color: var(--error); overflow-wrap: anywhere; }
.inspector-error svg { margin-right: var(--space-1); vertical-align: text-bottom; }
.inspector-table code { overflow-wrap: anywhere; }

@media (max-width: 560px) {
  .device-template-inspector .dialog__content { padding: var(--space-3); }
  .device-template-inspector footer { flex-wrap: wrap; }
  .device-template-inspector__spacer { display: none; }
}
</style>
