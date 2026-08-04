<script setup>
// The device-pool picker, shared by the template wizard (pick any number of
// devices to define streams from) and the start-run dialog (pick exactly one
// device per template flow). Device discovery is a live serial scan rather than
// a cached read, so both carry an explicit rescan for hardware plugged in after
// the surface opened.
//
// Rows are supplied already filtered: what counts as a candidate differs between
// the two callers, and the pool row itself can't say. What this component owns is
// how a row *reads* — selectable, unconfigured, or claimed — and it uses
// isDeviceSelectable() so that reading matches the callers' own gating exactly.
import { AlertTriangle, Radar } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import { isDeviceSelectable } from "../devices-api";

const props = defineProps({
  // Pool rows to display, in the order the caller wants them.
  devices: { type: Array, default: () => [] },
  // Device ids currently selected. A single-select caller passes 0 or 1 id.
  selected: { type: Array, default: () => [] },
  // Checkboxes (many streams) vs radios (one device for this flow).
  multiple: { type: Boolean, default: false },
  // Radio groups must be named or every table on the page shares one group.
  group: { type: String, default: "device-scan" },
  scanning: { type: Boolean, default: false },
  scanError: { type: String, default: "" },
  emptyMessage: { type: String, default: "No available devices to stream from." },
  // Optional per-row caption — the run dialog uses it to say why the planner
  // suggested a device ("Exact match", "Type match", …).
  annotate: { type: Function, default: null },
});
const emit = defineEmits(["toggle", "configure", "rescan"]);

// Kept in sync with the header below so the empty-state row spans the table.
const COLUMN_COUNT = 6;

function isSelected(device) {
  return device.id != null && props.selected.includes(device.id);
}

// Present but unconfigured hardware is listed on purpose so an operator can see
// (and set up) a device that is plugged in but not yet usable. Clicking such a
// row opens configuration rather than silently doing nothing.
function onRow(device) {
  if (!isDeviceSelectable(device)) {
    if (device.status === "unconfigured") emit("configure", device);
    return;
  }
  emit("toggle", device);
}
</script>

<template>
  <div class="device-scan">
    <div class="device-scan__head">
      <slot name="heading" />
      <BaseButton variant="secondary" :disabled="scanning" @click="emit('rescan')">
        <Radar :size="16" /> {{ scanning ? "Scanning…" : "Scan Devices" }}
      </BaseButton>
    </div>

    <slot name="intro" />

    <div v-if="scanError" class="form-notice" role="alert">
      <AlertTriangle :size="18" /> {{ scanError }} Showing the previous scan.
    </div>

    <slot name="notices" />

    <div class="table-wrap">
      <table class="data-table">
        <!-- Availability and Status are dropped: callers filter to available,
             unclaimed hardware, so both read the same on every row, and
             "configured or not" is carried by the checkbox-vs-warning cell. -->
        <thead>
          <tr><th class="select-col" /><th>Device</th><th>Type</th><th>Hardware ID</th><th>Port</th><th /></tr>
        </thead>
        <tbody>
          <tr v-if="!devices.length"><td :colspan="COLUMN_COUNT">{{ emptyMessage }}</td></tr>
          <tr
            v-for="device in devices"
            :key="device.hardwareId ?? device.id"
            :class="{
              'row-selected': isSelected(device),
              'row-selectable': isDeviceSelectable(device),
              'row-unconfigured': !isDeviceSelectable(device),
            }"
            @click="onRow(device)"
          >
            <td class="select-cell">
              <!-- @click.stop: the row handler already toggles, so let the
                   control own its own click rather than firing twice. -->
              <input
                v-if="isDeviceSelectable(device)"
                :type="multiple ? 'checkbox' : 'radio'"
                :name="multiple ? undefined : group"
                class="row-checkbox"
                :checked="isSelected(device)"
                :aria-label="`Use ${device.name}`"
                @click.stop="emit('toggle', device)"
              />
              <span
                v-else
                class="row-warning"
                title="Configure this device before using it as a stream."
                aria-label="Configure this device before using it as a stream."
              ><AlertTriangle :size="16" /></span>
            </td>
            <td>
              <strong>{{ device.name }}</strong>
              <span v-if="!isDeviceSelectable(device)" class="row-warning-copy">Configure before use</span>
              <span v-else-if="annotate && annotate(device)" class="row-annotation">{{ annotate(device) }}</span>
            </td>
            <td>{{ device.type }}</td>
            <td><code>{{ device.hardwareId }}</code></td>
            <td><code>{{ device.port }}</code></td>
            <td>
              <button
                v-if="device.status !== 'free'"
                type="button"
                class="table-action"
                @click.stop="emit('configure', device)"
              >
                Configure
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <slot name="footer" />
  </div>
</template>

<style scoped>
.device-scan__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.device-scan__head :deep(h3) {
  margin: 0;
}
/* styles.css floors every table at 780px, which is wider than the panes this
   table lives in and would force a horizontal scrollbar inside each one. With
   the columns trimmed there's nothing left that needs the floor, so drop it and
   let the table fit. .table-wrap keeps overflow-x as the escape hatch. */
.data-table {
  min-width: 0;
}
/* Global cell padding (16px/24px) is tuned for full-width tables; halve the
   horizontal share to buy back roughly 60px per row at these widths. */
.data-table th,
.data-table td {
  padding-right: var(--space-3);
  padding-left: var(--space-3);
}
.data-table td {
  padding-top: var(--space-3);
  padding-bottom: var(--space-3);
}
/* Auto table layout only compresses a column as far as its content's min-content
   width. Hardware IDs and ports are unbroken strings, so without this they'd act
   as struts holding the table wider than its pane. */
.data-table code {
  overflow-wrap: anywhere;
}
/* Only free devices can be toggled; unconfigured rows keep the default cursor
   so the row doesn't advertise an affordance that onRow() rejects. */
.row-selectable {
  cursor: pointer;
}
.row-selectable:hover {
  background: var(--sage-50);
}
/* Inset bar rather than a border so the row's height doesn't shift on select. */
.row-selected {
  background: var(--sage-100);
  box-shadow: inset 3px 0 0 var(--accent);
}
.row-selected:hover {
  background: var(--sage-200);
}
/* Unconfigured hardware: muted text, warning glyph where the checkbox would be.
   It is still clickable — a click opens the settings dialog — so it keeps the
   pointer that advertises that. */
.row-unconfigured {
  color: var(--text-muted);
  cursor: pointer;
}
.row-unconfigured:hover {
  background: var(--sage-50);
}
.row-unconfigured strong {
  font-weight: 500;
}
.row-warning {
  display: inline-flex;
  color: var(--warning);
}
.row-warning-copy {
  display: block;
  color: var(--warning);
  font-size: var(--fs-xs);
}
.row-annotation {
  display: block;
  color: var(--muted);
  font-size: var(--fs-xs);
}
.select-col {
  width: 2.5rem;
}
.select-cell {
  text-align: center;
}
.row-checkbox {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
  cursor: pointer;
}
</style>
