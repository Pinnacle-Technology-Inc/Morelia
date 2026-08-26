<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { AlertTriangle, ArrowLeft, Check, Copy, ExternalLink } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import { formatCentralTimestamp } from "../datetime";
import {
  acceptTemplateChange,
  archiveTemplate,
  canRunTemplate,
  loadDeviceTemplates,
  loadSessionTemplate,
  loadSessionTemplateSource,
  registerDiscoveredTemplate,
  refreshTemplateDependencyRevision,
  resolveTemplateRename,
  templateControls,
  templateFlowSummary,
  templateStateHint,
} from "../templates-api";

const props = defineProps({
  templateId: { type: String, default: null },
  // "detail" or "review" — review opens straight into the change comparison.
  view: { type: String, default: "detail" },
});
const emit = defineEmits(["back", "run-template", "open-template", "changed"]);

const TABS = [
  { id: "configuration", label: "Configuration" },
  { id: "revision", label: "File & revision" },
  { id: "usage", label: "Use in code" },
];

const template = ref(null);
const state = ref("loading");
const loadError = ref("");
const actionError = ref("");
const busy = ref("");
const selectedRenamePath = ref("");
const templateToml = ref("");
const sourceError = ref("");
const deviceTemplates = ref([]);
const deviceTemplatesError = ref("");
const copied = ref("");
// `review` opens on the tab that carries the hashes, which is what a change
// review is: comparing the trusted revision against what is on disk now.
const activeTab = ref(props.view === "review" ? "revision" : "configuration");

// `open` is navigation to this very page, so it renders as a button that does
// nothing. `run` is the same action as the Start run control the header already
// draws from this list — it is not a second button.
const controls = computed(() => templateControls(template.value).filter((control) => control.id !== "open"));
const hint = computed(() => templateStateHint(template.value));
const runnable = computed(() => canRunTemplate(template.value));
const summary = computed(() => templateFlowSummary(template.value));
// A drifted file is the one case where both hashes matter to the operator:
// trusted is what the accepted revision says, observed is what is on disk now.
const drifted = computed(
  () =>
    Boolean(template.value?.registeredHash) &&
    Boolean(template.value?.observedHash) &&
    template.value.registeredHash !== template.value.observedHash,
);
const renameCandidates = computed(() =>
  (template.value?.warnings ?? []).filter((warning) => warning.includes(".toml")),
);
const showRenamePicker = computed(
  () => template.value?.state === "AMBIGUOUS_RENAME" || renameCandidates.value.length > 0,
);
// Rename candidates ARE warnings. Listing them as alerts and again as the radio
// options prints every candidate path on screen twice, so the picker takes
// ownership of them whenever it renders.
const warnings = computed(() => {
  const all = template.value?.warnings ?? [];
  return showRenamePicker.value ? all.filter((warning) => !renameCandidates.value.includes(warning)) : all;
});

/**
 * The template's device flows, flattened into what the page actually draws.
 *
 * Every field the canonical content can carry is surfaced here. The previous
 * page rendered only `device_template_path` and a comma-joined list of sink
 * types, which silently dropped the nickname, the hardware pin, the port, the
 * device-template revision pin, and each sink's name, destination and
 * parameters — that is, most of what distinguishes one template from another.
 */
function normalizeTemplatePath(value) {
  return String(value ?? "").replaceAll("\\", "/").replace(/^\.\//, "").toLowerCase();
}

function statLabel(key) {
  return String(key)
    .replaceAll("_", " ")
    .split(" ")
    .map((word) => ({ id: "ID", ss: "SS" })[word.toLowerCase()] ?? `${word.charAt(0).toUpperCase()}${word.slice(1)}`)
    .join(" ");
}

function statValue(value) {
  if (Array.isArray(value)) {
    const groups = [];
    for (const item of value) {
      const display = statValue(item);
      const last = groups.at(-1);
      if (last?.value === display) last.count += 1;
      else groups.push({ value: display, count: 1 });
    }
    return groups.map((group) => `${group.value}${group.count > 1 ? ` x${group.count}` : ""}`).join(", ");
  }
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const deviceTemplatesByPath = computed(() => new Map(
  deviceTemplates.value.map((item) => [normalizeTemplatePath(item?.file_path), item]),
));

const flows = computed(() =>
  (template.value?.content?.device_flows ?? []).map((flow, index) => {
    const path = typeof flow?.device_template_path === "string" ? flow.device_template_path : "";
    const sinks = Array.isArray(flow?.sinks) ? flow.sinks : [];
    const linkedTemplate = deviceTemplatesByPath.value.get(normalizeTemplatePath(path));
    const parameters = linkedTemplate?.content?.parameters;
    const stats = [];
    const deviceType = linkedTemplate?.type ?? linkedTemplate?.content?.type;
    if (deviceType != null) stats.push({ label: "Device type", value: statValue(deviceType) });
    if (parameters && typeof parameters === "object") {
      for (const [key, value] of Object.entries(parameters)) {
        if (value != null) stats.push({ label: statLabel(key), value: statValue(value) });
      }
    }
    if (flow?.hardware_id != null) stats.push({ label: "Hardware ID", value: statValue(flow.hardware_id) });
    if (flow?.port != null) stats.push({ label: "Port", value: statValue(flow.port) });
    return {
      index,
      // The nickname is the operator's own word for this stream. Without one,
      // the device template's filename is the only other thing naming it.
      title: flow?.nickname || path.split("/").pop()?.replace(/\.toml$/i, "") || `Stream ${index + 1}`,
      devicePath: path,
      stats,
      statsUnavailable: linkedTemplate ? "" : deviceTemplatesError.value || "Linked device template not found.",
      sinks: sinks.map((sink, sinkIndex) => ({
        key: `${index}-${sinkIndex}`,
        // sink_name defaults to the sink type on the backend, so the two are
        // equal far more often than not; showing both would repeat the token.
        name: sink?.sink_name || sink?.sink_type || "—",
        type: sink?.sink_type ?? "—",
        location: sink?.sink_location ?? null,
        parameters: Object.entries(sink?.sink_parameters ?? {}),
      })),
    };
  }),
);

// The strip answers "is there anything in here" before the tab is opened. A
// template whose file failed to parse has no flows, which is a defect, not a
// zero worth showing in the same green as a healthy count.
const tabCounts = computed(() => ({ configuration: flows.value.length }));
const tabTones = computed(() => ({ configuration: flows.value.length ? "good" : "bad" }));

const policyLabel = computed(() => {
  const policy = template.value?.content?.policy;
  return policy ? policy.charAt(0).toUpperCase() + policy.slice(1) : null;
});
const cliCommand = computed(() => `pinnacle session run --template ${JSON.stringify(template.value?.name ?? "")}`);
const apiIdentity = computed(() => JSON.stringify({
  source_template_id: template.value?.templateId ?? null,
  expected_template_hash: template.value?.registeredHash ?? null,
}, null, 2));
const canonicalJson = computed(() => JSON.stringify(template.value?.content ?? {}, null, 2));

function countLabel(count, noun) {
  return `${count} ${count === 1 ? noun : `${noun}s`}`;
}

function formatTimestamp(value) {
  return formatCentralTimestamp(value, { fallback: value ? String(value) : "—" });
}

function variantFor(control) {
  if (control.id === "run") return "primary";
  // Archive is the only control here that takes a revision out of service. At
  // the top of the page beside Start run, `secondary` made them look alike.
  if (control.id === "archive") return "danger";
  return "secondary";
}

async function refresh() {
  if (!props.templateId) {
    state.value = "ready";
    loadError.value = "No template selected.";
    return;
  }
  state.value = "loading";
  loadError.value = "";
  try {
    template.value = await loadSessionTemplate(props.templateId);
    sourceError.value = "";
    deviceTemplatesError.value = "";
    templateToml.value = "";
    deviceTemplates.value = [];
    const [sourceResult, deviceTemplatesResult] = await Promise.allSettled([
      template.value?.reference
        ? loadSessionTemplateSource(template.value.reference)
        : Promise.resolve({ toml: "" }),
      loadDeviceTemplates(),
    ]);
    if (sourceResult.status === "fulfilled") {
      templateToml.value = sourceResult.value.toml;
    } else {
      sourceError.value = sourceResult.reason?.message ?? "The TOML source is unavailable.";
    }
    if (deviceTemplatesResult.status === "fulfilled") {
      deviceTemplates.value = deviceTemplatesResult.value;
    } else {
      deviceTemplatesError.value = deviceTemplatesResult.reason?.message ?? "Device template stats are unavailable.";
    }
    state.value = "ready";
  } catch (error) {
    template.value = null;
    loadError.value = error?.message ?? "This template could not be loaded.";
    state.value = "ready";
  }
}

async function copyValue(value, label) {
  try {
    await navigator.clipboard.writeText(value);
    copied.value = label;
    window.setTimeout(() => { if (copied.value === label) copied.value = ""; }, 1600);
  } catch {
    actionError.value = "Clipboard access is unavailable. Select the value and copy it manually.";
  }
}

// Every action re-reads the resource from its own response, so what the page
// shows next is the server's post-action state rather than a guess about what
// the action did.
async function run(control) {
  if (control.confirm && !window.confirm(control.confirm)) return;
  actionError.value = "";
  busy.value = control.id;
  try {
    if (control.id === "register") {
      template.value = await registerDiscoveredTemplate(template.value.reference);
    } else if (control.id === "accept_change") {
      template.value = await acceptTemplateChange(template.value.templateId);
    } else if (control.id === "refresh_dependency_revision") {
      const previousTemplateId = template.value.templateId;
      template.value = await refreshTemplateDependencyRevision(template.value.templateId);
      if (template.value.templateId !== previousTemplateId) {
        emit("open-template", template.value.templateId);
      }
    } else if (control.id === "archive") {
      template.value = await archiveTemplate(template.value.templateId);
    } else if (control.id === "resolve_rename") {
      if (!selectedRenamePath.value) {
        actionError.value = "Choose which file is the renamed original first.";
        return;
      }
      template.value = await resolveTemplateRename(template.value.templateId, selectedRenamePath.value);
    }
    emit("changed");
  } catch (error) {
    // Show the backend's own conflict guidance rather than restating it.
    actionError.value = error?.problem?.detail ?? error?.message ?? "That action could not be completed.";
  } finally {
    busy.value = "";
  }
}

function activate(control) {
  if (control.kind === "navigate") {
    if (control.id === "run") emit("run-template", template.value.templateId);
    if (control.id === "open_original") emit("open-template", template.value.duplicateOfTemplateId);
    return;
  }
  run(control);
}

onMounted(refresh);
watch(() => props.templateId, refresh);
</script>

<template>
  <!-- page--detail, not page--workspace. The workspace shell is a flex column
       with overflow:hidden whose `> .card` rule hands every card `flex: 1 1 auto`
       — right for the one full-height card wrapping a scrolling table that the
       list pages use, wrong for a stack of independent panels, which it squeezed
       to equal heights inside a page that could not scroll. -->
  <div class="page page--detail">
    <button class="back-link" type="button" @click="emit('back')">
      <ArrowLeft :size="16" /> Templates
    </button>

    <BaseCard v-if="state === 'loading'" class="detail-panel">
      <div class="empty-state" aria-busy="true">Loading template…</div>
    </BaseCard>
    <BaseCard v-else-if="loadError" class="detail-panel">
      <div class="empty-state" role="alert">
        <h3>Template unavailable</h3>
        <p>{{ loadError }}</p>
      </div>
    </BaseCard>

    <template v-else-if="template">
      <!-- Identity, verdict and every available action in one always-visible
           band, so switching tabs never puts the controls out of reach. -->
      <header class="detail-header">
        <div>
          <div class="title-row">
            <h1>{{ template.name }}</h1>
            <StatusBadge :value="template.state" />
          </div>
          <div class="detail-metadata">
            <span>{{ countLabel(summary.streams, "stream") }} / {{ countLabel(summary.sinks, "sink") }}</span>
            <span v-if="policyLabel">{{ policyLabel }} recovery</span>
            <span v-if="template.updatedAt">Updated {{ formatTimestamp(template.updatedAt) }}</span>
          </div>
        </div>
        <div class="detail-actions">
          <BaseButton
            v-for="control in controls"
            :key="control.id"
            :variant="variantFor(control)"
            :title="control.title"
            :disabled="Boolean(busy)"
            @click="activate(control)"
          >
            {{ busy === control.id ? "Working…" : control.label }}
          </BaseButton>
        </div>
      </header>

      <!-- One region for everything that wants the operator's attention, above
           the tabs so no tab can hide it. `hint` is the single narrative
           explanation of the state: it used to be restated by a paragraph in the
           revision card, by the rename card's intro, and by each action's own
           title and confirm text. -->
      <div v-if="hint || warnings.length || actionError" class="template-attention">
        <div v-if="hint" class="detail-alert" role="status">
          <AlertTriangle :size="18" aria-hidden="true" />
          <span>{{ hint }}</span>
        </div>
        <div v-for="warning in warnings" :key="warning" class="detail-alert" role="status">
          <AlertTriangle :size="18" aria-hidden="true" />
          <span>{{ warning }}</span>
        </div>
        <div v-if="actionError" class="form-notice" role="alert">
          <AlertTriangle :size="18" aria-hidden="true" />
          <span>{{ actionError }}</span>
        </div>
      </div>

      <!-- The decision blocks running, so it sits above the tabs rather than
           inside one. The intro paragraph is gone: its first sentence repeated
           the AMBIGUOUS_RENAME hint verbatim, and only the consequence — what
           happens to the files you do not pick — was new. -->
      <BaseCard v-if="showRenamePicker" class="detail-panel">
        <h3>Which file is the original?</h3>
        <p>The file you select keeps this template ID. The rest become duplicates.</p>
        <div class="rename-options">
          <label v-for="candidate in renameCandidates" :key="candidate" class="cascade-option">
            <input v-model="selectedRenamePath" type="radio" name="rename-original" :value="candidate" />
            <code>{{ candidate }}</code>
          </label>
        </div>
      </BaseCard>

      <BaseCard class="detail-content">
        <TabBar
          class="detail-tabs"
          :tabs="TABS"
          :active="activeTab"
          :counts="tabCounts"
          :tones="tabTones"
          @change="activeTab = $event"
        />

        <!-- A template source is intentionally more compact than a live-session
             flow. It describes the reusable device template and preference; the
             concrete device config is selected only when a run starts. -->
        <div v-if="activeTab === 'configuration'" class="flow-list" role="tabpanel" aria-label="Configuration">
          <div v-if="!flows.length" class="records-empty">
            This template has no readable device flows. Repair the TOML file on disk.
          </div>
          <BaseCard v-for="flow in flows" :key="flow.index" class="flow-card template-flow-card">
            <header class="source-header">
              <div class="source-identity">
                <span class="eyebrow">Source {{ flow.index + 1 }}</span>
                <h3>{{ flow.title }}</h3>
                <code>{{ flow.devicePath || "No device template recorded" }}</code>
              </div>
              <dl v-if="flow.stats.length" class="source-facts" aria-label="Device template stats">
                <div v-for="stat in flow.stats" :key="stat.label">
                  <dt>{{ stat.label }}</dt>
                  <dd><code :title="stat.value">{{ stat.value }}</code></dd>
                </div>
              </dl>
              <span v-else class="source-stats-unavailable" :title="flow.statsUnavailable">
                Stats unavailable
              </span>
            </header>
            <div class="sink-section">
              <div class="sink-section__heading">
                <h4>Sinks</h4>
                <span>{{ flow.sinks.length }}</span>
              </div>
              <div class="sink-list">
                <div v-for="sink in flow.sinks" :key="sink.key">
                  <strong>{{ sink.name }}</strong>
                  <!-- What this sink actually does with the data: a folder for file
                       sinks, its connection parameters for service sinks. -->
                  <div class="sink-target">
                    <code v-if="sink.location">{{ sink.location }}</code>
                    <template v-else-if="sink.parameters.length">
                      <code v-for="[key, value] in sink.parameters" :key="key">{{ key }} = {{ value }}</code>
                    </template>
                  </div>
                  <code class="sink-type">{{ sink.type }}</code>
                </div>
              </div>
            </div>
          </BaseCard>
          <p class="helper-copy">
            Read-only. Change this template by editing its TOML file on disk, then accept the change here.
          </p>
        </div>

        <!-- Diagnostics, not identity: the operator never types either hash. -->
        <div v-else-if="activeTab === 'revision'" class="detail-grid" role="tabpanel" aria-label="File and revision">
          <BaseCard class="detail-panel">
            <h3>File</h3>
            <dl class="detail-list">
              <div><dt>On disk</dt><dd><code>{{ template.reference }}</code></dd></div>
              <div>
                <dt>Template ID</dt>
                <dd><code>{{ template.templateId ?? "Not registered" }}</code></dd>
              </div>
              <div>
                <dt>Trusted hash</dt>
                <dd><code :title="template.registeredHash ?? undefined">{{ template.registeredHash ?? "Not registered" }}</code></dd>
              </div>
              <div>
                <dt>Observed on disk</dt>
                <dd>
                  <code :title="template.observedHash ?? undefined">{{ template.observedHash ?? "Unreadable" }}</code>
                  <!-- Marks WHICH value drifted. The reason and the remedy are
                       stated once, in the attention band above. -->
                  <StatusBadge v-if="drifted" value="Needs action" compact />
                </dd>
              </div>
            </dl>
          </BaseCard>

          <BaseCard class="detail-panel">
            <h3>Lineage</h3>
            <dl class="detail-list">
              <div><dt>Lifecycle</dt><dd>{{ template.lifecycleState ?? "—" }}</dd></div>
              <div><dt>Integrity</dt><dd>{{ template.integrityState ?? "—" }}</dd></div>
              <div>
                <dt>Previous revision</dt>
                <dd>
                  <code v-if="template.lineageParentId">{{ template.lineageParentId }}</code>
                  <span v-else>None — this is the first revision</span>
                </dd>
              </div>
              <div v-if="template.duplicateOfTemplateId">
                <dt>Duplicate of</dt>
                <dd>
                  <code>{{ template.duplicateOfTemplateId }}</code>
                  <BaseButton
                    variant="quiet"
                    size="small"
                    @click="emit('open-template', template.duplicateOfTemplateId)"
                  >
                    <ExternalLink :size="14" /> Open original
                  </BaseButton>
                </dd>
              </div>
              <div><dt>Registered</dt><dd>{{ formatTimestamp(template.createdAt) }}</dd></div>
              <div><dt>Last updated</dt><dd>{{ formatTimestamp(template.updatedAt) }}</dd></div>
            </dl>
          </BaseCard>
        </div>

        <div v-else class="usage-panel" role="tabpanel" aria-label="Use in code">
          <p class="usage-intro">Copy the stable reference for commands, or inspect the exact canonical configuration your code will receive.</p>
          <BaseCard class="usage-card">
            <div class="usage-card__heading"><div><h3>Template reference</h3><p>Use the human-readable name with the Pinnacle CLI.</p></div><BaseButton size="small" variant="quiet" @click="copyValue(template.name, 'reference')"><Check v-if="copied === 'reference'" :size="14" /><Copy v-else :size="14" /> {{ copied === 'reference' ? 'Copied' : 'Copy' }}</BaseButton></div>
            <pre><code>{{ template.name }}</code></pre>
          </BaseCard>
          <BaseCard class="usage-card">
            <div class="usage-card__heading"><div><h3>CLI</h3><p>Starts the registered template through the normal assignment flow.</p></div><BaseButton size="small" variant="quiet" @click="copyValue(cliCommand, 'cli')"><Check v-if="copied === 'cli'" :size="14" /><Copy v-else :size="14" /> {{ copied === 'cli' ? 'Copied' : 'Copy' }}</BaseButton></div>
            <pre><code>{{ cliCommand }}</code></pre>
          </BaseCard>
          <BaseCard class="usage-card">
            <div class="usage-card__heading"><div><h3>API identity</h3><p>The hash is the expected revision token. A run request also needs assignments and an idempotency key.</p></div><BaseButton size="small" variant="quiet" @click="copyValue(apiIdentity, 'api')"><Check v-if="copied === 'api'" :size="14" /><Copy v-else :size="14" /> {{ copied === 'api' ? 'Copied' : 'Copy' }}</BaseButton></div>
            <pre><code>{{ apiIdentity }}</code></pre>
          </BaseCard>
          <BaseCard class="usage-card">
            <div class="usage-card__heading"><div><h3>Canonical JSON</h3><p>The normalized value represented by this registered template revision.</p></div><BaseButton size="small" variant="quiet" @click="copyValue(canonicalJson, 'json')"><Check v-if="copied === 'json'" :size="14" /><Copy v-else :size="14" /> {{ copied === 'json' ? 'Copied' : 'Copy' }}</BaseButton></div>
            <pre><code>{{ canonicalJson }}</code></pre>
          </BaseCard>
          <BaseCard class="usage-card">
            <div class="usage-card__heading"><div><h3>TOML source</h3><p>The portable source stored in the session-template library.</p></div><BaseButton v-if="templateToml" size="small" variant="quiet" @click="copyValue(templateToml, 'toml')"><Check v-if="copied === 'toml'" :size="14" /><Copy v-else :size="14" /> {{ copied === 'toml' ? 'Copied' : 'Copy' }}</BaseButton></div>
            <p v-if="sourceError" class="validation-copy" role="status">{{ sourceError }}</p>
            <pre v-else><code>{{ templateToml }}</code></pre>
          </BaseCard>
        </div>
      </BaseCard>
    </template>
  </div>
</template>

<style scoped>
/* .detail-alert and .form-notice carry no outer margin — everywhere else they
   are spaced by the grid or flex parent that holds them. */
.template-attention {
  display: grid;
  gap: var(--space-2);
}
.detail-content {
  overflow: visible;
}
.detail-tabs {
  position: sticky;
  top: calc(-1 * var(--space-6));
  z-index: 10;
  border-radius: var(--radius-md) var(--radius-md) 0 0;
  background: var(--sage-50);
  box-shadow: 0 1px 0 var(--border-card), 0 8px 16px rgb(5 48 25 / 8%);
}
/* .detail-panel > p sets margin-bottom: 1rem for prose that leads into content;
   the rename picker's line is the last text before the options, so the wrapper
   below supplies the gap instead. */
.detail-panel > p:last-child {
  margin-bottom: 0;
}
/* .field is the usual wrapper for a labelled control stack, but `.field input`
   sizes inputs to width: 100% / min-height: 44px — correct for text fields,
   wrong for radios, which would render as full-width boxes. */
.rename-options {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-4);
}
.rename-options .cascade-option {
  gap: var(--space-3);
}
/* .detail-list dd is a block, so the drift badge and the "Open original" button
   would sit on their own line under the value they annotate. */
.detail-list dd {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}
/* Template sources use a compact, borderless facts row populated from the
   linked device template's actual parameters. */
.template-flow-card {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-4);
  box-shadow: none;
}
.template-flow-card .source-header {
  display: grid;
  grid-template-columns: minmax(14rem, 1fr) auto;
  align-items: center;
  gap: var(--space-4);
}
.source-identity {
  min-width: 0;
}
.source-identity .eyebrow {
  display: block;
  margin-bottom: var(--space-1);
}
.source-identity h3 {
  margin-bottom: var(--space-1);
}
.source-identity > code {
  display: block;
  color: var(--text-muted);
  overflow-wrap: anywhere;
}
.source-facts {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2) var(--space-4);
}
.source-facts > div {
  display: grid;
  gap: 0.1rem;
  min-width: 6rem;
}
.source-facts dt {
  color: var(--text-muted);
  font-size: var(--fs-xs);
}
.source-facts dd {
  max-width: 16rem;
  font: var(--fs-xs) var(--font-mono);
  overflow-wrap: anywhere;
}
.source-stats-unavailable {
  color: var(--text-muted);
  font-size: var(--fs-xs);
}
.sink-section {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: var(--space-3);
}
.sink-section__heading {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 4.5rem;
  padding: var(--space-2) 0;
}
.sink-section__heading h4 {
  font-size: var(--fs-xs);
  text-transform: uppercase;
}
.sink-section__heading span {
  display: inline-grid;
  min-width: 1.25rem;
  min-height: 1.25rem;
  place-items: center;
  color: var(--text-accent);
  border-radius: var(--radius-pill);
  background: var(--surface-sage);
  font: var(--fs-xs) var(--font-mono);
}
.template-flow-card .sink-list {
  display: grid;
  gap: var(--space-2);
  min-width: 0;
}
.template-flow-card .sink-list > div {
  display: grid;
  grid-template-columns: minmax(7rem, auto) minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--surface-sage);
}
/* A service sink can carry several parameters, and a file sink an absolute
   path, so the middle column stacks and wraps rather than widening the card. */
.sink-target {
  display: grid;
  gap: 0.2rem;
  min-width: 0;
}
.sink-target code {
  overflow-wrap: anywhere;
}
/* The type is the controlled vocabulary token that appears in the TOML file,
   pinned to the right of every row so the sinks stay scannable by kind. */
.sink-type {
  justify-self: end;
  padding: 0.2rem 0.5rem;
  color: var(--text-accent);
  border-radius: var(--radius-pill);
  background: var(--surface-sage);
}
/* The flow cards already sit on the sage tray with their own padding. */
.flow-list > .helper-copy {
  margin-top: 0;
}
.usage-panel { display: grid; gap: var(--space-4); padding: var(--space-5); }
.usage-intro { color: var(--text-muted); }
.usage-card { min-width: 0; display: grid; gap: var(--space-3); padding: var(--space-4); box-shadow: none; }
.usage-card__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.usage-card__heading h3 { font-size: var(--fs-sm); }
.usage-card__heading p { margin-top: var(--space-1); color: var(--text-muted); font-size: var(--fs-xs); }
.usage-card pre { max-height: 320px; margin: 0; padding: var(--space-4); overflow: auto; border-radius: var(--radius-sm); color: #edf6f0; background: #10271a; white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 760px) {
  .template-flow-card .source-header {
    grid-template-columns: 1fr;
  }
  .source-facts {
    justify-content: flex-start;
  }
  .sink-section {
    grid-template-columns: 1fr;
    gap: var(--space-1);
  }
  .template-flow-card .sink-list > div {
    grid-template-columns: 1fr auto;
  }
  .template-flow-card .sink-target {
    grid-column: 1 / -1;
    grid-row: 2;
  }
  .template-flow-card .sink-type {
    grid-column: 2;
    grid-row: 1;
  }
  .usage-card__heading { flex-direction: column; }
}
</style>
