<script setup>
import { computed } from "vue";
import { AlertTriangle, X } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";

// The session template says one thing, the configured device says another. The
// operator picks a side for the whole device — this dialog only presents the
// comparison and reports the choice; the parent owns the write.
const props = defineProps({
  // The device-pool row being added as a stream.
  device: { type: Object, required: true },
  // The device template the session template's flow points at.
  templateName: { type: String, default: "" },
  // Rows from compareParameters(): { key, templateValue, deviceValue,
  // inTemplate, inDevice, same }. Both sides are canonical (the backend runs
  // template content and config parameters through the same registry), so a
  // difference here is a real difference, not a formatting artifact.
  rows: { type: Array, required: true },
  busy: { type: Boolean, default: false },
  error: { type: String, default: "" },
  // Some callers can accept either side. Start Run cannot: the backend only
  // accepts an exact template match, so keeping the current settings simply
  // means cancelling this repair and choosing another device.
  allowDeviceSettings: { type: Boolean, default: true },
});

const emit = defineEmits(["choose", "close"]);

const differences = computed(() => props.rows.filter((row) => !row.same));

// Adopting the template removes anything it doesn't mention, so name those keys
// explicitly rather than letting the operator discover the loss afterwards.
const droppedKeys = computed(() =>
  differences.value.filter((row) => !row.inTemplate).map((row) => row.key),
);

function formatValue(row, side) {
  const present = side === "template" ? row.inTemplate : row.inDevice;
  if (!present) return null;
  const value = side === "template" ? row.templateValue : row.deviceValue;
  return typeof value === "object" && value !== null ? JSON.stringify(value) : String(value);
}
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="$emit('close')">
    <section class="dialog drift-dialog" role="dialog" aria-modal="true" aria-label="Confirm device settings">
      <header>
        <div>
          <h2>Settings differ from the session template</h2>
          <p>{{ device.name }} · <code>{{ device.type }}</code></p>
        </div>
        <button class="icon-button" type="button" aria-label="Close dialog" @click="$emit('close')"><X :size="19" /></button>
      </header>

      <div class="dialog__content">
        <div class="dialog-notice">
          <strong>This session's template expects <code>{{ templateName }}</code>.</strong>
          <p>
            {{ differences.length }}
            setting{{ differences.length === 1 ? "" : "s" }} on this device
            {{ differences.length === 1 ? "does" : "do" }} not match it.
            <template v-if="allowDeviceSettings">Choose which side to use.</template>
            <template v-else>Apply the template settings to make this device available for the run.</template>
          </p>
        </div>

        <div class="table-wrap">
          <table class="data-table drift-table">
            <thead>
              <tr>
                <th>Setting</th>
                <th>A · Template</th>
                <th>B · This device</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.key" :class="{ 'drift-row--same': row.same }">
                <td><code>{{ row.key }}</code></td>
                <td>
                  <code v-if="formatValue(row, 'template') !== null">{{ formatValue(row, "template") }}</code>
                  <span v-else class="drift-unset">not set</span>
                </td>
                <td>
                  <code v-if="formatValue(row, 'device') !== null">{{ formatValue(row, "device") }}</code>
                  <span v-else class="drift-unset">not set</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Choosing A is a permanent write, not a per-session override: a
             session's device flow carries only a device_config_id, so there is
             nowhere to record "use these parameters just this once". -->
        <div class="form-notice" role="note">
          <AlertTriangle :size="18" />
          <span>
            Using the template's settings rewrites this device's saved configuration
            for every future session, not just this one.
            <template v-if="droppedKeys.length">
              It also clears
              <code v-for="(key, index) in droppedKeys" :key="key">{{ key }}{{ index < droppedKeys.length - 1 ? ", " : "" }}</code>,
              which the template does not specify.
            </template>
          </span>
        </div>

        <p v-if="error" class="validation-copy" role="alert">{{ error }}</p>
      </div>

      <footer class="drift-footer">
        <BaseButton variant="secondary" :disabled="busy" @click="$emit('close')">Cancel</BaseButton>
        <div>
          <BaseButton v-if="allowDeviceSettings" variant="secondary" :disabled="busy" @click="emit('choose', 'device')">
            B · Keep this device's settings
          </BaseButton>
          <BaseButton :disabled="busy" @click="emit('choose', 'template')">
            {{ busy ? "Applying…" : "A · Use the template's settings" }}
          </BaseButton>
        </div>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.drift-dialog {
  width: min(720px, 100%);
}
.drift-dialog header p {
  margin: var(--space) 0 0;
}
/* The table floor in styles.css is wider than this dialog; three short columns
   don't need it, and keeping it would force a horizontal scrollbar. */
.drift-table {
  min-width: 0;
}
.drift-table code {
  overflow-wrap: anywhere;
}
/* Matching rows stay visible for context but recede, so the eye lands on the
   rows that actually need a decision. */
.drift-row--same {
  color: var(--text-muted);
}
.drift-unset {
  color: var(--text-muted);
  font-style: italic;
}
/* Two choices of equal weight sit together on the right, away from Cancel. */
.drift-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.drift-footer > div {
  display: flex;
  gap: var(--space-2);
}
</style>
