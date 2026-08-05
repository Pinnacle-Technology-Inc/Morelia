<script setup>
import { Download, Plus, Radar } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import TemplateDetailPage from "./TemplateDetailPage.vue";
import { sessionLifecycleLabel } from "../session-api";
import {
  duplicateTemplateFrom,
  importSessionTemplate,
  loadDeviceTemplates,
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
const sessionTemplates = ref([]);
const state = ref("loading");
const errors = ref({ device: "", session: "" });
const importError = ref("");
const importing = ref(false);
const scanError = ref("");
const fileInput = ref(null);
const sessionSort = ref("status");
const tabs = [
  { id: "device-templates", label: "Device Templates" },
  { id: "session-templates", label: "Session Templates" },
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

function compareNames(left, right) {
  return left.name.localeCompare(right.name, undefined, { sensitivity: "base" });
}

function updatedTime(template) {
  const value = Date.parse(template.updatedAt ?? template.createdAt ?? "");
  return Number.isNaN(value) ? 0 : value;
}

const sortedSessionTemplates = computed(() => {
  const templates = [...sessionTemplates.value];
  if (sessionSort.value === "name") return templates.sort(compareNames);
  if (sessionSort.value === "updated") {
    return templates.sort((left, right) => updatedTime(right) - updatedTime(left) || compareNames(left, right));
  }
  return templates.sort((left, right) =>
    (stateSortOrder.get(left.state) ?? Number.MAX_SAFE_INTEGER) -
      (stateSortOrder.get(right.state) ?? Number.MAX_SAFE_INTEGER) ||
    compareNames(left, right),
  );
});

async function refresh() {
  state.value = "loading";
  errors.value = { device: "", session: "" };
  scanError.value = "";
  const [deviceResult, sessionResult] = await Promise.allSettled([loadDeviceTemplates(), loadSessionTemplateCatalog()]);
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

onMounted(refresh);
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
          <label class="template-sort">
            <span>Sort by</span>
            <select v-model="sessionSort">
              <option value="status">Status — Active first</option>
              <option value="name">Name — A to Z</option>
              <option value="updated">Recently updated</option>
            </select>
          </label>
        </div>
      </div>
      <div v-if="state === 'loading'" class="empty-state" aria-busy="true">Loading templates…</div>
      <div v-else class="table-wrap">
        <p v-if="activeTab === 'device-templates' && errors.device" role="alert">{{ errors.device }}</p>
        <p v-if="activeTab === 'session-templates' && errors.session" role="alert">{{ errors.session }}</p>
        <p v-if="activeTab === 'session-templates' && importError" role="alert">{{ importError }}</p>
        <p v-if="activeTab === 'session-templates' && scanError" role="alert">{{ scanError }}</p>
        <table v-if="activeTab === 'device-templates'" class="data-table">
          <thead>
            <tr>
              <th>Template</th>
              <th>Device Type</th>
              <th>File Path</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="template in deviceTemplates" :key="template.name">
              <td><strong>{{ template.name }}</strong></td>
              <td>{{ template.type }}</td>
              <td><code>{{ template.file_path }}</code></td>
              <td><div class="row-actions"><button type="button" class="table-action">Open</button><button type="button" class="table-action">Edit</button><button type="button" class="table-action">Rename</button><button type="button" class="table-action">Delete</button><button type="button" class="table-action" disabled title="No export HTTP route is defined">Export</button></div></td>
            </tr>
          </tbody>
        </table>

        <!-- Every row's state and non-registration controls come from the
             server. Registration is the one scan-owned transition. -->
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>Template</th>
              <th>State</th>
              <th>Information</th>
              <th>Streams / sinks</th>
              <th>Recovery</th>
              <th>Runs</th>
              <th>Latest session</th>
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
              <td class="template-information">
                <small v-if="!informationFor(template).length">—</small>
                <small v-for="message in informationFor(template)" :key="message">{{ message }}</small>
              </td>
              <td><code>{{ flowSummary(template) }}</code></td>
              <td>{{ template.content?.policy ?? "Unavailable" }}</td>
              <td>{{ template.runCount ?? "—" }}</td>
              <td>{{ latestSessionLabel(template) }}</td>
              <td @click.stop @keydown.stop>
                <div class="row-actions">
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
          </tbody>
        </table>
      </div>
    </BaseCard>
  </div>
</template>

<style scoped>
.template-toolbar {
  justify-content: flex-end;
}

.template-sort {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.template-sort::after {
  position: absolute;
  top: 50%;
  right: var(--space-3);
  width: 0.45rem;
  height: 0.45rem;
  color: var(--text-muted);
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  content: "";
  pointer-events: none;
  transform: translateY(-70%) rotate(45deg);
}

.template-sort > span {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
}

.template-sort select {
  width: min(15rem, 48vw);
  min-height: 40px;
  padding: 0 calc(var(--space-4) + var(--space-3)) 0 var(--space-3);
  appearance: none;
  color: var(--text-body);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--surface-card);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  font-size: var(--fs-sm);
  font-weight: var(--fw-semibold);
  transition:
    color var(--dur-fast) var(--ease-standard),
    border-color var(--dur-fast) var(--ease-standard),
    background var(--dur-fast) var(--ease-standard),
    box-shadow var(--dur-fast) var(--ease-standard);
}

.template-sort:hover select {
  color: var(--ink);
  border-color: var(--sage-400);
  background: var(--sage-50);
}

.template-sort:focus-within > span,
.template-sort:focus-within::after {
  color: var(--primary);
}

.template-sort select:focus-visible {
  border-color: var(--primary);
  background: var(--surface-card);
  box-shadow: var(--shadow-focus);
}

.template-sort option {
  color: var(--text-body);
  background: var(--surface-card);
}

.template-information {
  min-width: 18rem;
  white-space: normal;
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
</style>
