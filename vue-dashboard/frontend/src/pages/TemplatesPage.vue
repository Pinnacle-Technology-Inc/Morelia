<script setup>
import { Archive, ArrowDown, ArrowUp, ArrowUpDown, Download, Filter, Plus, Radar, Trash2, Wrench } from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import DeviceTemplateInspectorDialog from "../components/DeviceTemplateInspectorDialog.vue";
import DeviceTemplateStatusIcon from "../components/DeviceTemplateStatusIcon.vue";
import PageHeader from "../components/PageHeader.vue";
import RepairDeviceTemplateDialog from "../components/RepairDeviceTemplateDialog.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import RepairTemplateDialog from "../components/RepairTemplateDialog.vue";
import TemplateDetailPage from "./TemplateDetailPage.vue";
import { sessionLifecycleLabel } from "../session-api";
import {
  archiveTemplate,
  deleteDeviceTemplate,
  deleteSessionTemplate,
  duplicateTemplateFrom,
  importSessionTemplate,
  loadDeviceTemplateCatalog,
  loadSessionTemplateCatalog,
  registerDiscoveredTemplate,
  templateControls,
  templateFlowSummary,
  templateStateHint,
} from "../templates-api";

const props = defineProps({
  templateId: { type: String, default: null },
  // null renders the catalog; "detail"/"review" delegate to the detail page.
  view: { type: String, default: null },
});
const emit = defineEmits(["open-template", "review-template", "run-template", "new-template", "back"]);

const activeTab = ref("session-templates");
const deviceTemplates = ref([]);
const selectedDeviceTemplate = ref(null);
const repairingDeviceTemplate = ref(null);
const deviceTemplateActionError = ref("");
const sessionTemplates = ref([]);
const state = ref("loading");
const errors = ref({ device: "", session: "" });
const importError = ref("");
const importing = ref(false);
const scanError = ref("");
const rowActionError = ref("");
const busyReference = ref("");
const repairTemplate = ref(null);
const fileInput = ref(null);
const filterMenu = ref(null);
const filterOpen = ref(false);
const sessionSort = ref("state");
const sessionSortDirection = ref("asc");
const tabs = [
  { id: "session-templates", label: "Session Templates" },
  { id: "device-templates", label: "Device Templates" },
];

const showingDetail = computed(() => props.view === "detail" || props.view === "review");
const scanning = computed(() => state.value === "loading");
const stateSortOrder = new Map([
  ["ACTIVE", 0],
  ["MISSING", 1],
  ["INVALID", 2],
  ["CHANGED", 3],
  ["PENDING", 4],
  ["AMBIGUOUS_RENAME", 5],
  ["DUPLICATE", 6],
  ["ARCHIVED", 7],
  ["DISCOVERED", 8],
]);
const sessionStateOptions = [...stateSortOrder.keys()].map((value) => ({
  value,
  label: value.charAt(0) + value.slice(1).toLowerCase().replaceAll("_", " "),
}));
const defaultSessionStates = sessionStateOptions
  .filter(({ value }) => value !== "ARCHIVED")
  .map(({ value }) => value);
const selectedSessionStates = ref([...defaultSessionStates]);

function compareNames(left, right) {
  return left.name.localeCompare(right.name, undefined, { sensitivity: "base" });
}

const visibleSessionTemplates = computed(() =>
  sessionTemplates.value.filter((template) => selectedSessionStates.value.includes(template.state)),
);

const emptySessionTemplateLabel = computed(() => {
  if (!selectedSessionStates.value.length) return "Select at least one template state to show.";
  return "No session templates match the selected states.";
});

function showAllSessionStates() {
  selectedSessionStates.value = sessionStateOptions.map(({ value }) => value);
}

function resetSessionStates() {
  selectedSessionStates.value = [...defaultSessionStates];
}

function closeFilterOnOutsideClick(event) {
  if (filterOpen.value && !filterMenu.value?.contains(event.target)) filterOpen.value = false;
}

function setSessionSort(column) {
  if (sessionSort.value === column) {
    if (sessionSortDirection.value === "asc") {
      sessionSortDirection.value = "desc";
    } else {
      sessionSort.value = null;
      sessionSortDirection.value = "asc";
    }
    return;
  }
  sessionSort.value = column;
  sessionSortDirection.value = "asc";
}

function sortIconFor(column) {
  if (sessionSort.value !== column) return ArrowUpDown;
  return sessionSortDirection.value === "asc" ? ArrowUp : ArrowDown;
}

function sortAriaFor(column) {
  if (sessionSort.value !== column) return "none";
  return sessionSortDirection.value === "asc" ? "ascending" : "descending";
}

function compareText(left, right) {
  return String(left ?? "").localeCompare(String(right ?? ""), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function compareByColumn(left, right) {
  if (sessionSort.value === "name") return compareNames(left, right);
  if (sessionSort.value === "state") {
    return (stateSortOrder.get(left.state) ?? Number.MAX_SAFE_INTEGER) -
      (stateSortOrder.get(right.state) ?? Number.MAX_SAFE_INTEGER);
  }
  if (sessionSort.value === "flow") {
    const leftFlow = templateFlowSummary(left);
    const rightFlow = templateFlowSummary(right);
    return leftFlow.streams - rightFlow.streams || leftFlow.sinks - rightFlow.sinks;
  }
  if (sessionSort.value === "recovery") {
    return compareText(left.content?.policy ?? "Unavailable", right.content?.policy ?? "Unavailable");
  }
  if (sessionSort.value === "runs") return (left.runCount ?? -1) - (right.runCount ?? -1);
  if (sessionSort.value === "latest") return compareText(latestSessionLabel(left), latestSessionLabel(right));
  if (sessionSort.value === "information") {
    return compareText(informationFor(left).join(" "), informationFor(right).join(" "));
  }
  return 0;
}

const sortedSessionTemplates = computed(() => {
  const templates = [...visibleSessionTemplates.value];
  if (!sessionSort.value) return templates;
  return templates.sort((left, right) => {
    const comparison = compareByColumn(left, right);
    return (sessionSortDirection.value === "desc" ? -comparison : comparison) || compareNames(left, right);
  });
});

async function refresh() {
  state.value = "loading";
  errors.value = { device: "", session: "" };
  scanError.value = "";
  rowActionError.value = "";
  const [deviceResult, sessionResult] = await Promise.allSettled([loadDeviceTemplateCatalog(), loadSessionTemplateCatalog()]);
  deviceTemplates.value = deviceResult.status === "fulfilled" ? deviceResult.value : [];
  sessionTemplates.value = sessionResult.status === "fulfilled" ? sessionResult.value : [];

  let sessionError = sessionResult.status === "rejected"
    ? (sessionResult.reason?.message ?? "Session templates unavailable.")
    : "";

  // A catalog read is also a registry scan. Adopt every newly discovered file
  // immediately, then reload once so the table presents durable resources.
  // Register sequentially so duplicate and lineage decisions stay deterministic
  // when several files arrive together.
  if (sessionResult.status === "fulfilled") {
    const failures = [];
    const discovered = sessionResult.value.filter((template) => template.state === "DISCOVERED");
    for (const template of discovered) {
      try {
        await registerDiscoveredTemplate(template.reference);
      } catch (reason) {
        failures.push({ template, reason });
      }
    }

    if (discovered.length) {
      try {
        sessionTemplates.value = await loadSessionTemplateCatalog();
      } catch (reason) {
        sessionError = reason?.message ?? "The template registry could not be reloaded after scanning.";
      }
    }

    if (failures.length === 1) {
      const [{ template, reason }] = failures;
      const detail = reason?.problem?.detail ?? reason?.message ?? "Registration failed.";
      scanError.value = `${template.reference}: ${detail}`;
    } else if (failures.length > 1) {
      scanError.value = `${failures.length} newly discovered templates could not be registered. Scan again to retry.`;
    }
  }

  errors.value = {
    device: deviceResult.status === "rejected" ? (deviceResult.reason?.message ?? "Device templates unavailable.") : "",
    session: sessionError,
  };
  state.value = "ready";
}

function controlsFor(template) {
  // Registration is scan-owned and navigation is row-owned now. Keep only the
  // actions that perform work beyond opening this template.
  return templateControls(template).filter(
    (control) => !["register", "open", "open_original"].includes(control.id),
  );
}

function rowOpenTarget(template) {
  return template.templateId ?? template.duplicateOfTemplateId ?? null;
}

function openTemplateRow(template) {
  const templateId = rowOpenTarget(template);
  if (templateId) emit("open-template", templateId);
}

function stateHint(template) {
  if (template.state === "DISCOVERED") {
    return "Automatic registration did not complete. Scan templates to retry.";
  }
  return templateStateHint(template);
}

function informationFor(template) {
  const messages = [stateHint(template), ...(template.warnings ?? [])]
    .map((message) => String(message).trim())
    .filter(Boolean);
  return [...new Set(messages)];
}

/** The `streams / sinks` cell, e.g. `2 / 4`. */
function flowSummary(template) {
  const { streams, sinks } = templateFlowSummary(template);
  return `${streams} / ${sinks}`;
}

/**
 * The newest run this revision produced, e.g. `Run 18 · Active`.
 *
 * An em dash covers two different things on purpose — a template nobody has
 * started, and a route that did not count runs — because neither is a number the
 * operator can act on, and inventing "0 runs" for the second would be a guess.
 */
function latestSessionLabel(template) {
  const latest = template.latestSession;
  if (!latest) return "—";
  return `${latest.name} · ${sessionLifecycleLabel(latest.status)}`;
}

/**
 * Start run is the one action a row is for; the rest stay quiet.
 *
 * Same rule the detail page uses, so a control does not change weight when the
 * operator follows it from the catalog into the template.
 */
function variantFor(control) {
  return control.id === "run" ? "primary" : "quiet";
}

async function activate(template, control) {
  if (control.id === "run") return emit("run-template", template.templateId);

  // Everything else already has an identity, and needs the detail page's
  // context and confirmation copy rather than firing from a table row.
  return emit(control.id === "accept_change" ? "review-template" : "open-template", template.templateId);
}

function openRepair(template) {
  rowActionError.value = "";
  repairTemplate.value = template;
}

function openDeviceTemplate(template) {
  deviceTemplateActionError.value = "";
  selectedDeviceTemplate.value = template;
}

function updateDeviceTemplate(updated) {
  const reference = updated.file_path;
  deviceTemplates.value = deviceTemplates.value.map((template) =>
    template.file_path === reference ? updated : template,
  );
  selectedDeviceTemplate.value = updated;
}

function openDeviceTemplateRepair(template) {
  selectedDeviceTemplate.value = null;
  repairingDeviceTemplate.value = template;
}

function returnToDeviceTemplateInspector() {
  selectedDeviceTemplate.value = repairingDeviceTemplate.value;
  repairingDeviceTemplate.value = null;
}

async function deviceTemplateRepaired(repairedTemplate) {
  const reference = repairingDeviceTemplate.value?.file_path ?? repairedTemplate.file_path;
  repairingDeviceTemplate.value = null;
  await refresh();
  selectedDeviceTemplate.value = deviceTemplates.value.find((template) => template.file_path === reference) ?? repairedTemplate;
}

function deviceTemplateRouteName(template) {
  const filename = String(template.file_path ?? "").split("/").pop();
  return filename?.replace(/\.toml$/i, "") || template.name;
}

async function removeDeviceTemplate(template) {
  if (!window.confirm(
    `Permanently delete device template “${template.name}”?\n\nThis action cannot be undone.`,
  )) return;
  deviceTemplateActionError.value = "";
  try {
    await deleteDeviceTemplate(deviceTemplateRouteName(template));
    selectedDeviceTemplate.value = null;
    await refresh();
  } catch (error) {
    deviceTemplateActionError.value = error?.problem?.detail ?? error?.message ?? "The device template could not be deleted.";
  }
}

function formatDeviceTemplateModified(template) {
  const value = template.modified_at ?? template.created_at;
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
  }).format(date);
}

async function repaired() {
  repairTemplate.value = null;
  await refresh();
}

async function archiveMissing(template) {
  const prompt = "Archive this missing template?\n\nIt will stop appearing in the template catalog.";
  if (!window.confirm(prompt)) return;
  rowActionError.value = "";
  busyReference.value = template.reference;
  try {
    await archiveTemplate(template.templateId);
    await refresh();
  } catch (error) {
    rowActionError.value = error?.problem?.detail ?? error?.message ?? "The missing template could not be archived.";
  } finally {
    busyReference.value = "";
  }
}

async function deleteMissing(template) {
  if (!window.confirm(
    `Permanently delete the registry record for “${template.name}”?\n\n` +
    "The template file is already missing. This action cannot be undone.",
  )) return;
  rowActionError.value = "";
  busyReference.value = template.reference;
  try {
    await deleteSessionTemplate(template.reference);
    await refresh();
  } catch (error) {
    rowActionError.value = error?.problem?.detail ?? error?.message ?? "The missing template could not be deleted.";
  } finally {
    busyReference.value = "";
  }
}

/**
 * Import a template the operator authored elsewhere.
 *
 * A TOML file is imported by dropping it in the templates folder, then running
 * a template scan; the scan adopts it without the portal touching the bytes.
 * This picker covers the other direction: structured configuration exported
 * from somewhere else, sent through the same create contract.
 */
async function importFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  importError.value = "";
  importing.value = true;
  try {
    const text = await file.text();
    let payload;
    try {
      payload = JSON.parse(text);
    } catch {
      importError.value =
        "That file is not structured template configuration. To import a TOML template, " +
        "put the file in the session-templates folder, then choose Scan Templates.";
      return;
    }
    const created = await importSessionTemplate(payload);
    emit("open-template", created.template_id);
  } catch (error) {
    // One configuration, one identity: a duplicate opens the template that
    // already holds it rather than renaming or retrying this one.
    const existing = duplicateTemplateFrom(error);
    if (existing) {
      emit("open-template", existing.template_id);
      return;
    }
    importError.value = error?.problem?.detail ?? error?.message ?? "That template could not be imported.";
  } finally {
    importing.value = false;
    if (fileInput.value) fileInput.value.value = "";
  }
}

onMounted(() => {
  refresh();
  document.addEventListener("pointerdown", closeFilterOnOutsideClick);
});

onBeforeUnmount(() => document.removeEventListener("pointerdown", closeFilterOnOutsideClick));
</script>

<template>
  <TemplateDetailPage
    v-if="showingDetail"
    :template-id="props.templateId"
    :view="props.view"
    @back="emit('back')"
    @run-template="emit('run-template', $event)"
    @open-template="emit('open-template', $event)"
    @changed="refresh"
  />

  <div v-else class="page page--workspace">
    <PageHeader
      eyebrow="Reusable configuration"
      title="Templates"
      description="Manage reusable device and session templates."
    >
      <BaseButton @click="emit('new-template')"><Plus :size="16" /> New Template</BaseButton>
      <BaseButton variant="secondary" :disabled="importing" @click="fileInput?.click()">
        <Download :size="16" /> {{ importing ? "Importing…" : "Import Template" }}
      </BaseButton>
      <BaseButton variant="secondary" :disabled="scanning" @click="refresh">
        <Radar :size="16" /> {{ scanning ? "Scanning…" : "Scan Templates" }}
      </BaseButton>
      <input ref="fileInput" type="file" accept=".json,application/json" hidden @change="importFile" />
    </PageHeader>

    <BaseCard class="workspace-card">
      <div class="workspace-chrome">
        <TabBar :tabs="tabs" :active="activeTab" @change="activeTab = $event" />
        <div v-if="activeTab === 'session-templates' && state !== 'loading'" class="toolbar template-toolbar">
          <div ref="filterMenu" class="template-filter" @keydown.esc="filterOpen = false">
            <button
              type="button"
              class="template-filter-trigger"
              aria-label="Filter session templates by state"
              aria-haspopup="true"
              aria-controls="session-template-state-filter"
              :aria-expanded="filterOpen"
              title="Filter templates"
              @click="filterOpen = !filterOpen"
            >
              <Filter :size="18" />
            </button>
            <div v-if="filterOpen" id="session-template-state-filter" class="template-filter-popover">
              <strong>Template state</strong>
              <div class="template-filter-options">
                <label v-for="option in sessionStateOptions" :key="option.value">
                  <input v-model="selectedSessionStates" type="checkbox" :value="option.value" />
                  <span>{{ option.label }}</span>
                </label>
              </div>
              <div class="template-filter-actions">
                <button type="button" @click="showAllSessionStates">Select all</button>
                <button type="button" @click="resetSessionStates">Reset</button>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div v-if="state === 'loading'" class="empty-state" aria-busy="true">Loading templates…</div>
      <div v-else class="table-wrap">
        <p v-if="activeTab === 'device-templates' && errors.device" role="alert">{{ errors.device }}</p>
        <p v-if="activeTab === 'device-templates' && deviceTemplateActionError" role="alert">{{ deviceTemplateActionError }}</p>
        <p v-if="activeTab === 'session-templates' && errors.session" role="alert">{{ errors.session }}</p>
        <p v-if="activeTab === 'session-templates' && importError" role="alert">{{ importError }}</p>
        <p v-if="activeTab === 'session-templates' && scanError" role="alert">{{ scanError }}</p>
        <p v-if="activeTab === 'session-templates' && rowActionError" role="alert">{{ rowActionError }}</p>
        <table v-if="activeTab === 'device-templates'" class="data-table">
          <thead>
            <tr>
              <th>Template</th>
              <th class="device-template-status-column">Status</th>
              <th>Device Type</th>
              <th>File Path</th>
              <th>Modified</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="template in deviceTemplates"
              :key="template.file_path ?? template.name"
              class="template-row--clickable"
              tabindex="0"
              @click="openDeviceTemplate(template)"
              @keydown.enter="openDeviceTemplate(template)"
              @keydown.space.prevent="openDeviceTemplate(template)"
            >
              <td><strong>{{ template.name }}</strong></td>
              <td class="device-template-status-column">
                <DeviceTemplateStatusIcon :status="template.status ?? 'NEEDS_VALIDATION'" />
              </td>
              <td>{{ template.type || "Unknown" }}</td>
              <td><code>{{ template.file_path }}</code></td>
              <td>{{ formatDeviceTemplateModified(template) }}</td>
            </tr>
            <tr v-if="!deviceTemplates.length"><td colspan="5" class="records-empty">No device templates to show.</td></tr>
          </tbody>
        </table>

        <!-- Every row's state and non-registration controls come from the
             server. Registration is the one scan-owned transition. -->
        <table v-else class="data-table">
          <thead>
            <tr>
              <th :aria-sort="sortAriaFor('name')">
                <span class="sortable-heading">Template<button type="button" aria-label="Sort by Template" @click="setSessionSort('name')"><component :is="sortIconFor('name')" :size="14" /></button></span>
              </th>
              <th :aria-sort="sortAriaFor('state')">
                <span class="sortable-heading">State<button type="button" aria-label="Sort by State" @click="setSessionSort('state')"><component :is="sortIconFor('state')" :size="14" /></button></span>
              </th>
              <th :aria-sort="sortAriaFor('flow')">
                <span class="sortable-heading">Streams / sinks<button type="button" aria-label="Sort by Streams and sinks" @click="setSessionSort('flow')"><component :is="sortIconFor('flow')" :size="14" /></button></span>
              </th>
              <th :aria-sort="sortAriaFor('recovery')">
                <span class="sortable-heading">Recovery<button type="button" aria-label="Sort by Recovery" @click="setSessionSort('recovery')"><component :is="sortIconFor('recovery')" :size="14" /></button></span>
              </th>
              <th :aria-sort="sortAriaFor('runs')">
                <span class="sortable-heading">Runs<button type="button" aria-label="Sort by Runs" @click="setSessionSort('runs')"><component :is="sortIconFor('runs')" :size="14" /></button></span>
              </th>
              <th :aria-sort="sortAriaFor('latest')">
                <span class="sortable-heading">Latest session<button type="button" aria-label="Sort by Latest session" @click="setSessionSort('latest')"><component :is="sortIconFor('latest')" :size="14" /></button></span>
              </th>
              <th :aria-sort="sortAriaFor('information')">
                <span class="sortable-heading">Information<button type="button" aria-label="Sort by Information" @click="setSessionSort('information')"><component :is="sortIconFor('information')" :size="14" /></button></span>
              </th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="template in sortedSessionTemplates"
              :key="template.reference"
              :class="{ 'template-row--clickable': rowOpenTarget(template) }"
              :tabindex="rowOpenTarget(template) ? 0 : undefined"
              @click="openTemplateRow(template)"
              @keydown.enter="openTemplateRow(template)"
            >
              <td><strong :title="template.reference">{{ template.name }}</strong></td>
              <td><StatusBadge :value="template.state" compact /></td>
              <td><code>{{ flowSummary(template) }}</code></td>
              <td>{{ template.content?.policy ?? "Unavailable" }}</td>
              <td>{{ template.runCount ?? "—" }}</td>
              <td>{{ latestSessionLabel(template) }}</td>
              <td class="template-information">
                <small v-if="!informationFor(template).length">—</small>
                <small v-for="message in informationFor(template)" :key="message">{{ message }}</small>
              </td>
              <td @click.stop @keydown.stop>
                <div class="row-actions">
                  <BaseButton
                    v-if="template.state === 'INVALID'"
                    size="small"
                    variant="secondary"
                    @click="openRepair(template)"
                  >
                    <Wrench :size="14" /> Repair template
                  </BaseButton>
                  <template v-if="template.state === 'MISSING'">
                    <BaseButton
                      size="small"
                      variant="secondary"
                      :disabled="busyReference === template.reference"
                      @click="archiveMissing(template)"
                    >
                      <Archive :size="14" /> Archive
                    </BaseButton>
                    <BaseButton
                      size="small"
                      variant="danger"
                      :disabled="busyReference === template.reference"
                      @click="deleteMissing(template)"
                    >
                      <Trash2 :size="14" /> Delete
                    </BaseButton>
                  </template>
                  <BaseButton
                    v-for="control in controlsFor(template)"
                    :key="control.id"
                    size="small"
                    :variant="variantFor(control)"
                    :title="control.title"
                    @click="activate(template, control)"
                  >
                    {{ control.label }}
                  </BaseButton>
                </div>
              </td>
            </tr>
            <tr v-if="!sortedSessionTemplates.length">
              <td colspan="8" class="records-empty">{{ emptySessionTemplateLabel }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </BaseCard>

    <RepairTemplateDialog
      v-if="repairTemplate"
      :template="repairTemplate"
      :issues="informationFor(repairTemplate)"
      @close="repairTemplate = null"
      @repaired="repaired"
    />
    <DeviceTemplateInspectorDialog
      v-if="selectedDeviceTemplate"
      :template="selectedDeviceTemplate"
      @close="selectedDeviceTemplate = null"
      @delete="removeDeviceTemplate"
      @repair="openDeviceTemplateRepair"
      @validated="updateDeviceTemplate"
    />
    <RepairDeviceTemplateDialog
      v-if="repairingDeviceTemplate"
      :template="repairingDeviceTemplate"
      @back="returnToDeviceTemplateInspector"
      @close="repairingDeviceTemplate = null"
      @repaired="deviceTemplateRepaired"
    />
  </div>
</template>

<style scoped>
.template-toolbar {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.template-filter {
  position: relative;
}

.template-filter-trigger {
  display: inline-grid;
  width: 40px;
  height: 40px;
  place-items: center;
  color: var(--text-body);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--surface-card);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-standard),
    border-color var(--dur-fast) var(--ease-standard),
    background var(--dur-fast) var(--ease-standard),
    box-shadow var(--dur-fast) var(--ease-standard);
}

.template-filter-trigger:hover,
.template-filter-trigger[aria-expanded="true"] {
  color: var(--primary);
  border-color: var(--sage-400);
  background: var(--sage-50);
}

.template-filter-trigger:focus-visible {
  border-color: var(--primary);
  box-shadow: var(--shadow-focus);
  outline: none;
}

.template-filter-popover {
  position: absolute;
  z-index: 10;
  top: calc(100% + var(--space-2));
  right: 0;
  width: 18rem;
  padding: var(--space-3);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--surface-card);
  box-shadow: var(--shadow-md);
}

.template-filter-popover > strong {
  display: block;
  margin-bottom: var(--space-3);
  color: var(--ink);
  font-size: var(--fs-sm);
}

.template-filter-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2) var(--space-3);
}

.template-filter-options label {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-body);
  cursor: pointer;
  font-size: var(--fs-sm);
}

.template-filter-options input {
  width: 1rem;
  height: 1rem;
  margin: 0;
  accent-color: var(--primary);
}

.template-filter-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-card);
}

.template-filter-actions button {
  padding: 0;
  color: var(--primary);
  border: 0;
  background: transparent;
  cursor: pointer;
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
}

.sortable-heading {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.sortable-heading button {
  display: inline-grid;
  width: 1.5rem;
  height: 1.5rem;
  flex: 0 0 auto;
  padding: 0;
  place-items: center;
  color: var(--text-muted);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-standard),
    background var(--dur-fast) var(--ease-standard);
}

.sortable-heading button:hover {
  color: var(--primary);
  background: var(--sage-50);
}

.sortable-heading button:focus-visible {
  color: var(--primary);
  box-shadow: var(--shadow-focus);
  outline: none;
}

.template-information {
  width: 13rem;
  min-width: 11rem;
  max-width: 13rem;
  white-space: normal;
  overflow-wrap: anywhere;
}

.template-information small {
  display: block;
  color: var(--text-muted);
  line-height: 1.45;
}

.template-information small + small {
  margin-top: var(--space-1);
}

.template-row--clickable {
  cursor: pointer;
}

.template-row--clickable:hover {
  background: var(--sage-50);
}

.template-row--clickable:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}

.device-template-status-column {
  width: 5.5rem;
  text-align: center;
}
</style>
