<script setup>
import { FileUp, RefreshCw } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import BaseCard from "./BaseCard.vue";

const props = defineProps({
  modelValue: { type: String, required: true },
  filename: { type: String, required: true },
  state: { type: String, default: "idle" },
  error: { type: String, default: "" },
  summary: { type: Object, default: null },
  deviceTemplates: { type: Array, default: () => [] },
});

const emit = defineEmits(["update:modelValue", "validate"]);

async function importFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  emit("update:modelValue", await file.text());
  event.target.value = "";
}
</script>

<template>
  <div class="toml-editor-layout">
    <section class="toml-editor-shell" aria-labelledby="toml-editor-title">
      <header class="toml-editor-toolbar">
        <div>
          <strong id="toml-editor-title">Session template source</strong>
          <span>TOML</span>
        </div>
        <code>{{ filename }}</code>
      </header>
      <label class="visually-hidden" for="session-template-toml">Session template TOML</label>
      <textarea
        id="session-template-toml"
        :value="modelValue"
        spellcheck="false"
        autocomplete="off"
        autocapitalize="off"
        @input="emit('update:modelValue', $event.target.value)"
      />
    </section>

    <aside class="toml-editor-side" aria-label="TOML validation and help">
      <div
        class="toml-validation"
        :class="{
          'toml-validation--valid': state === 'valid',
          'toml-validation--error': state === 'error',
        }"
        role="status"
        aria-live="polite"
      >
        <template v-if="state === 'valid' && summary">
          <strong>Template is valid</strong>
          <span>
            {{ summary.device_flows }} device requirement{{ summary.device_flows === 1 ? "" : "s" }} ·
            {{ summary.sinks }} sink{{ summary.sinks === 1 ? "" : "s" }} ·
            {{ summary.hardware_preferences }} hardware preference{{ summary.hardware_preferences === 1 ? "" : "s" }}
          </span>
        </template>
        <template v-else-if="state === 'error'">
          <strong>Template needs attention</strong>
          <span>{{ error }}</span>
        </template>
        <template v-else-if="state === 'validating'">
          <strong>Validating template…</strong>
          <span>Checking TOML syntax, device-template references, sinks, and policy.</span>
        </template>
        <template v-else>
          <strong>{{ state === "dirty" ? "Changes need validation" : "Not validated yet" }}</strong>
          <span>Validation is read-only and does not create or modify template files.</span>
        </template>
      </div>

      <BaseCard class="toml-help-card">
        <h3>Authoring rules</h3>
        <ul>
          <li>The template name comes from Step 1 and becomes the filename.</li>
          <li>Each flow references a reusable <code>device_template_path</code>.</li>
          <li><code>hardware_id</code> is optional; omit it to accept the closest compatible device.</li>
          <li>Omit a file sink’s <code>sink_location</code> to use Morelia’s generated, collision-safe filename.</li>
        </ul>
      </BaseCard>

      <BaseCard class="toml-help-card">
        <h3>Available device templates</h3>
        <ul v-if="deviceTemplates.length" class="toml-reference-list">
          <li v-for="template in deviceTemplates" :key="template.file_path">
            <code>{{ template.file_path }}</code>
            <span>{{ template.type }}</span>
          </li>
        </ul>
        <p v-else>No device templates are available yet. Create or import one before validating this session template.</p>
      </BaseCard>

      <BaseButton :disabled="state === 'validating'" @click="emit('validate')">
        <RefreshCw :size="16" /> {{ state === "validating" ? "Validating…" : "Validate TOML" }}
      </BaseButton>
      <label class="toml-import-button">
        <FileUp :size="16" /> Import .toml file
        <input type="file" accept=".toml,application/toml,text/plain" @change="importFile" />
      </label>
    </aside>
  </div>
</template>

<style scoped>
.toml-editor-layout { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(260px, 0.45fr); gap: var(--space-4); align-items: start; }
.toml-editor-shell { min-width: 0; overflow: hidden; border: 1px solid var(--green-950); border-radius: var(--radius-md); background: #10271a; box-shadow: var(--shadow-card); }
.toml-editor-toolbar { min-height: 46px; display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: 0 var(--space-4); color: var(--sage-100); background: #17452d; }
.toml-editor-toolbar > div { display: flex; align-items: center; gap: var(--space-2); }
.toml-editor-toolbar strong { font-family: var(--font-display); font-size: var(--fs-xs); }
.toml-editor-toolbar span { padding: 0.2rem 0.45rem; border: 1px solid rgba(255, 255, 255, 0.22); border-radius: var(--radius-sm); color: var(--sage-200); font-size: 0.62rem; font-weight: var(--fw-bold); }
.toml-editor-toolbar code { overflow: hidden; color: var(--sage-200); text-overflow: ellipsis; white-space: nowrap; }
textarea { width: 100%; min-height: 560px; display: block; padding: var(--space-5); resize: vertical; border: 0; outline: 0; color: #edf6f0; background: #10271a; font: 0.8rem/1.7 var(--font-mono); tab-size: 2; }
textarea:focus-visible { box-shadow: inset var(--shadow-focus); }
.toml-editor-side { display: grid; gap: var(--space-3); }
.toml-validation { display: grid; gap: var(--space-1); padding: var(--space-4); border: 1px solid var(--border-card); border-left: var(--border-accent) solid var(--gray-400); border-radius: var(--radius-md); background: var(--paper); }
.toml-validation strong { color: var(--text-heading); font-family: var(--font-display); font-size: var(--fs-sm); }
.toml-validation span { color: var(--text-muted); font-size: var(--fs-xs); line-height: var(--lh-snug); }
.toml-validation--valid { border-color: var(--sage-300); border-left-color: var(--success); background: var(--sage-50); }
.toml-validation--valid strong { color: var(--success); }
.toml-validation--error { border-color: #dfaaa6; border-left-color: var(--error); background: #faf0ef; }
.toml-validation--error strong { color: var(--error); }
.toml-help-card { padding: var(--space-4); box-shadow: none; }
.toml-help-card h3 { font-size: var(--fs-sm); }
.toml-help-card p, .toml-help-card ul { margin-top: var(--space-2); color: var(--text-muted); font-size: var(--fs-xs); line-height: var(--lh-body); }
.toml-help-card ul { padding-left: 1.1rem; }
.toml-help-card li + li { margin-top: var(--space-2); }
.toml-reference-list { max-height: 152px; overflow: auto; padding: 0 !important; list-style: none; }
.toml-reference-list li { display: grid; gap: 0.15rem; padding-top: var(--space-2); border-top: 1px solid var(--border-card); }
.toml-reference-list li:first-child { padding-top: 0; border-top: 0; }
.toml-reference-list code { overflow-wrap: anywhere; color: var(--text-accent); }
.toml-reference-list span { color: var(--text-muted); font-size: 0.65rem; }
.toml-import-button { min-height: 40px; display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2); padding: 0 var(--space-4); border: 1px solid var(--border-card); border-radius: var(--radius-pill); color: var(--text-body); background: var(--surface-card); font-family: var(--font-display); font-size: var(--fs-xs); font-weight: var(--fw-bold); cursor: pointer; }
.toml-import-button:hover { border-color: var(--primary); background: var(--surface-muted); }
.toml-import-button:focus-within { box-shadow: var(--shadow-focus); }
.toml-import-button input { position: absolute; width: 1px; height: 1px; opacity: 0; }
@media (max-width: 980px) { .toml-editor-layout { grid-template-columns: 1fr; } textarea { min-height: 480px; } }
@media (max-width: 540px) { .toml-editor-toolbar { align-items: flex-start; flex-direction: column; padding-block: var(--space-3); } textarea { min-height: 420px; padding: var(--space-4); font-size: 0.72rem; } }
</style>
