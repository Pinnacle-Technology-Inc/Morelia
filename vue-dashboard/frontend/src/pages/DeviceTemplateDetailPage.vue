<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { AlertTriangle, ArrowLeft, Check, Copy, Pencil, Trash2 } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import TabBar from "../components/TabBar.vue";
import {
  deleteDeviceTemplate,
  loadDeviceTemplate,
  loadDeviceTemplateCatalog,
  loadDeviceTemplateSource,
  repairDeviceTemplateSource,
  validateDeviceTemplateToml,
} from "../templates-api";

const props = defineProps({ templateName: { type: String, required: true } });
const emit = defineEmits(["back", "changed"]);
const tabs = [{ id: "configuration", label: "Configuration" }, { id: "source", label: "Source & hash" }];
const activeTab = ref("configuration");
const template = ref(null);
const source = ref("");
const draft = ref("");
const state = ref("loading");
const error = ref("");
const editing = ref(false);
const validationState = ref("idle");
const validationError = ref("");
const validation = ref(null);
const busy = ref(false);
const copied = ref("");

const parameters = computed(() => Object.entries(template.value?.content?.parameters ?? {}).sort(([a], [b]) => a.localeCompare(b)));
const fileReference = computed(() => template.value?.file_path?.split(/[\\/]/).pop()?.replace(/\.toml$/i, "") ?? template.value?.name ?? "");
const duplicateMatches = computed(() => (validation.value?.matches ?? []).filter((row) => row.file_path !== template.value?.file_path));
const canSave = computed(() => validationState.value === "valid" && !duplicateMatches.value.length);

function describeError(reason, fallback) {
  return reason?.problem?.detail ?? reason?.message ?? fallback;
}

async function refresh() {
  state.value = "loading";
  error.value = "";
  try {
    let loaded;
    try {
      loaded = await loadDeviceTemplate(props.templateName);
    } catch (reason) {
      const catalog = await loadDeviceTemplateCatalog();
      loaded = catalog.find((row) => {
        const reference = row.file_path?.split(/[\\/]/).pop()?.replace(/\.toml$/i, "") ?? row.name;
        return reference === props.templateName;
      });
      if (!loaded) throw reason;
      activeTab.value = "source";
      error.value = loaded.error ?? "This template is invalid. Edit and validate its TOML source to repair it.";
    }
    const loadedSource = await loadDeviceTemplateSource(loaded.file_path);
    template.value = loaded;
    source.value = loadedSource.toml;
    draft.value = loadedSource.toml;
    editing.value = false;
    validationState.value = "idle";
    state.value = "ready";
  } catch (reason) {
    error.value = describeError(reason, "This device template could not be loaded.");
    state.value = "ready";
  }
}

watch(() => props.templateName, refresh);
watch(draft, () => {
  if (!editing.value) return;
  validationState.value = "dirty";
  validationError.value = "";
  validation.value = null;
});
onMounted(refresh);

async function validate() {
  validationState.value = "validating";
  validationError.value = "";
  try {
    validation.value = await validateDeviceTemplateToml(draft.value);
    validationState.value = "valid";
  } catch (reason) {
    validationState.value = "error";
    validationError.value = describeError(reason, "This device template is invalid.");
  }
}

async function save() {
  if (!canSave.value) return;
  busy.value = true;
  error.value = "";
  try {
    template.value = await repairDeviceTemplateSource(template.value.file_path, draft.value);
    source.value = draft.value;
    editing.value = false;
    validationState.value = "idle";
    emit("changed");
  } catch (reason) {
    error.value = describeError(reason, "The device template could not be saved.");
  } finally {
    busy.value = false;
  }
}

async function remove() {
  if (!window.confirm(`Permanently delete device template “${template.value.name}”?\n\nThis action cannot be undone.`)) return;
  busy.value = true;
  try {
    await deleteDeviceTemplate(fileReference.value);
    emit("changed");
    emit("back");
  } catch (reason) {
    error.value = describeError(reason, "The device template could not be deleted.");
  } finally {
    busy.value = false;
  }
}

async function copy(value, label) {
  try {
    await navigator.clipboard.writeText(value);
    copied.value = label;
    window.setTimeout(() => { if (copied.value === label) copied.value = ""; }, 1600);
  } catch {
    error.value = "Clipboard access is unavailable. Select the value and copy it manually.";
  }
}
</script>

<template>
  <div class="page page--workspace device-template-detail-page">
    <div v-if="state === 'loading'" class="empty-state" aria-busy="true">Loading device template…</div>
    <template v-else-if="template">
      <PageHeader eyebrow="Device template" :title="template.name" :description="template.file_path">
        <BaseButton variant="quiet" @click="emit('back')"><ArrowLeft :size="16" /> Templates</BaseButton>
        <BaseButton v-if="!editing" variant="secondary" @click="activeTab = 'source'; editing = true"><Pencil :size="16" /> Edit source</BaseButton>
        <BaseButton variant="danger" :disabled="busy" @click="remove"><Trash2 :size="16" /> Delete</BaseButton>
      </PageHeader>
      <p v-if="error" class="form-notice" role="alert"><AlertTriangle :size="18" /> {{ error }}</p>
      <BaseCard class="detail-content">
        <TabBar :tabs="tabs" :active="activeTab" @change="activeTab = $event" />
        <section v-if="activeTab === 'configuration'" class="detail-panel" role="tabpanel">
          <dl class="identity-grid"><div><dt>Device type</dt><dd><code>{{ template.type }}</code></dd></div><div><dt>Parameters</dt><dd>{{ parameters.length }}</dd></div><div><dt>Status</dt><dd>{{ template.status }}</dd></div></dl>
          <table class="parameter-table"><thead><tr><th>Parameter</th><th>Canonical value</th></tr></thead><tbody><tr v-for="([key, value]) in parameters" :key="key"><th scope="row"><code>{{ key }}</code></th><td><code>{{ typeof value === 'string' ? value : JSON.stringify(value) }}</code></td></tr></tbody></table>
        </section>
        <section v-else class="source-panel" role="tabpanel">
          <div v-if="template.content_hash" class="source-meta"><div><span>Content hash</span><code>{{ template.content_hash }}</code></div><BaseButton size="small" variant="quiet" @click="copy(template.content_hash, 'hash')"><Check v-if="copied === 'hash'" :size="14" /><Copy v-else :size="14" /> {{ copied === 'hash' ? 'Copied' : 'Copy hash' }}</BaseButton></div>
          <textarea v-if="editing" v-model="draft" aria-label="Device template TOML" spellcheck="false" />
          <pre v-else><code>{{ source }}</code></pre>
          <div v-if="editing" class="edit-status">
            <p v-if="validationError" class="validation-copy" role="alert">{{ validationError }}</p>
            <div v-if="duplicateMatches.length" class="form-notice" role="alert"><AlertTriangle :size="18" /><span>These values match {{ duplicateMatches.map((row) => row.name).join(', ') }}. Use that template instead of creating repeated content.</span></div>
            <div class="edit-actions"><BaseButton variant="quiet" :disabled="busy" @click="draft = source; editing = false">Cancel</BaseButton><BaseButton variant="secondary" :disabled="validationState === 'validating'" @click="validate">{{ validationState === 'validating' ? 'Validating…' : 'Validate' }}</BaseButton><BaseButton :disabled="busy || !canSave" @click="save">{{ busy ? 'Saving…' : 'Save template' }}</BaseButton></div>
          </div>
        </section>
      </BaseCard>
    </template>
    <div v-else class="empty-state" role="alert"><p>{{ error }}</p><BaseButton variant="secondary" @click="emit('back')">Back to templates</BaseButton></div>
  </div>
</template>

<style scoped>
.device-template-detail-page { overflow-y: auto; }
.detail-content { overflow: hidden; }
.detail-panel, .source-panel { display: grid; gap: var(--space-5); padding: var(--space-5); }
.identity-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); margin: 0; }
.identity-grid > div { padding: var(--space-4); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--surface-muted); }
.identity-grid dt, .source-meta span { color: var(--text-muted); font-size: var(--fs-xs); }
.identity-grid dd { margin: var(--space-1) 0 0; color: var(--text-heading); font-weight: var(--fw-bold); }
.parameter-table { width: 100%; border-collapse: collapse; }
.parameter-table th, .parameter-table td { padding: var(--space-3); border-bottom: 1px solid var(--border-card); text-align: left; }
.parameter-table th[scope='row'] { width: 34%; color: var(--text-muted); }
.parameter-table code { overflow-wrap: anywhere; }
.source-meta { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.source-meta > div { min-width: 0; display: grid; gap: var(--space-1); }
.source-meta code { overflow-wrap: anywhere; }
.source-panel textarea, .source-panel pre { min-height: 420px; margin: 0; padding: var(--space-5); overflow: auto; border: 1px solid var(--green-950); border-radius: var(--radius-md); color: #edf6f0; background: #10271a; font: var(--fs-sm)/1.7 var(--font-mono); white-space: pre-wrap; }
.source-panel textarea { width: 100%; resize: vertical; }
.edit-status { display: grid; gap: var(--space-3); }
.edit-actions { display: flex; justify-content: flex-end; gap: var(--space-3); }
@media (max-width: 700px) { .identity-grid { grid-template-columns: 1fr; } .source-meta { align-items: flex-start; flex-direction: column; } }
</style>
