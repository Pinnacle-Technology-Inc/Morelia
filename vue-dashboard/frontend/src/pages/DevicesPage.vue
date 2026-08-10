<script setup>
import { Check, Clock3, Pencil, Radar, X } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import DeviceSettingsDialog from "../components/DeviceSettingsDialog.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import { computed, nextTick, onMounted, ref } from "vue";
import { loadDeviceConfigs, loadDevicePool, registerDeviceName } from "../devices-api";

const activeTab = ref("all");
const devices = ref([]);
const state = ref("loading");
const error = ref("");
const scanId = ref(null);
const scannedAt = ref(null);

// Inline rename state, keyed by device.id.
const renamingId = ref(null);
const renameValue = ref("");
const renameInput = ref(null);
const renameError = ref("");

// Settings / create dialog target.
const activeDevice = ref(null);

const tabs = [
  { id: "all", label: "All Devices" },
  { id: "available", label: "Available" },
  { id: "claimed", label: "Claimed" },
];

// "Available" = physically present AND not claimed by a session. A configured
// device that is FREE but not_found must NOT appear here (that was the bug):
// claim state and physical presence are independent axes.
function isAvailable(device) {
  return device.availability === "available" && device.status !== "claimed";
}

const counts = computed(() => ({
  all: devices.value.length,
  available: devices.value.filter(isAvailable).length,
  claimed: devices.value.filter((device) => device.status === "claimed").length,
}));

const visibleDevices = computed(() => {
  if (activeTab.value === "available") return devices.value.filter(isAvailable);
  if (activeTab.value === "claimed") return devices.value.filter((device) => device.status === "claimed");
  return devices.value;
});

// Render the scan timestamp as a readable local date/time, falling back to the
// raw value if it is not a parseable date.
const scannedAtLabel = computed(() => {
  if (!scannedAt.value) return "—";
  const date = new Date(scannedAt.value);
  return Number.isNaN(date.getTime()) ? scannedAt.value : date.toLocaleString();
});

async function refresh() {
  state.value = "loading";
  error.value = "";
  devices.value = [];
  try {
    const [pool, configs] = await Promise.all([loadDevicePool(), loadDeviceConfigs()]);
    const configById = new Map(configs.map((config) => [config.id, config]));
    devices.value = pool.devices.map((device) => {
      const config = configById.get(device.configId);
      if (!config) return device;
      return {
        ...device,
        configSource: config.source_template ?? null,
        sourceTemplateHash: config.source_template_hash ?? null,
      };
    });
    scanId.value = pool.scanId;
    scannedAt.value = pool.scannedAt;
    state.value = pool.devices.length ? "ready" : "empty";
  } catch (reason) {
    state.value = "unavailable";
    error.value = reason instanceof Error ? reason.message : "Device pool is unavailable.";
  }
}

onMounted(() => {
  refresh();
});

function displayLabel(value) {
  return {
    available: "Available",
    not_found: "Not found",
    unopenable: "Unopenable",
    free: "Free",
    claimed: "Claimed",
    unconfigured: "Unconfigured",
  }[value] ?? value;
}

// --- Rename -----------------------------------------------------------------

async function startRename(device) {
  if (!device.hardwareId) return; // registration keys on hardware identity
  renameError.value = "";
  renamingId.value = device.id;
  renameValue.value = device.nickname ?? device.name ?? "";
  await nextTick();
  // A `ref` inside v-for can resolve to an array; only one input is rendered.
  const el = Array.isArray(renameInput.value) ? renameInput.value[0] : renameInput.value;
  el?.focus?.();
  el?.select?.();
}

function cancelRename() {
  renamingId.value = null;
  renameValue.value = "";
  renameError.value = "";
}

async function confirmRename(device) {
  const nickname = renameValue.value.trim();
  if (!nickname || nickname === (device.nickname ?? "")) {
    cancelRename();
    return;
  }
  try {
    await registerDeviceName({ type: device.type, hardware_id: device.hardwareId, nickname });
    cancelRename();
    await refresh();
  } catch (reason) {
    renameError.value = reason instanceof Error ? reason.message : "Rename failed.";
  }
}

// --- Settings dialog --------------------------------------------------------

function openSettings(device) {
  activeDevice.value = device;
}

async function onSaved() {
  activeDevice.value = null;
  await refresh();
}
</script>

<template>
  <div class="page page--workspace">
    <PageHeader
      eyebrow="Hardware inventory"
      title="Devices"
      description="Review connected hardware, configured devices, availability, and session ownership."
    >
      <BaseButton variant="secondary" :disabled="state === 'loading'" @click="refresh"><Radar :size="16" /> Scan Devices</BaseButton>
    </PageHeader>

    <BaseCard class="workspace-card">
      <TabBar :tabs="tabs" :active="activeTab" :counts="counts" @change="activeTab = $event" />
      <p v-if="state === 'loading'" class="empty-state" aria-busy="true">Loading device pool…</p>
      <p v-else-if="state === 'unavailable'" class="empty-state" role="alert">{{ error }}</p>
      <p v-else-if="state === 'empty'" class="empty-state">No devices found in scan {{ scanId ?? "-" }}.</p>
      <div v-else class="table-wrap">
        <p v-if="error" class="validation-copy" role="alert">{{ error }}</p>
        <table class="data-table data-table--clickable">
          <thead>
            <tr>
              <th>Device</th>
              <th>Type</th>
              <th>Hardware ID</th>
              <th>Port</th>
              <th>Availability</th>
              <th>Status</th>
              <th>Device Template</th>
              <th>Owning Session</th>
              <th>Last Seen</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="device in visibleDevices"
              :key="device.id"
              tabindex="0"
              @click="openSettings(device)"
              @keydown.enter="openSettings(device)"
            >
              <!-- Name cell: single click never opens settings; double-click renames. -->
              <td class="device-name" @click.stop @dblclick="startRename(device)">
                <template v-if="renamingId === device.id">
                  <span class="device-name__edit">
                    <input
                      ref="renameInput"
                      v-model="renameValue"
                      type="text"
                      aria-label="Device name"
                      @keydown.enter="confirmRename(device)"
                      @keydown.esc="cancelRename"
                    />
                    <button class="icon-button icon-button--sm" type="button" aria-label="Save name" @click="confirmRename(device)"><Check :size="15" /></button>
                    <button class="icon-button icon-button--sm" type="button" aria-label="Cancel rename" @click="cancelRename"><X :size="15" /></button>
                  </span>
                  <small v-if="renameError" class="validation-copy">{{ renameError }}</small>
                </template>
                <span v-else class="device-name__display">
                  <strong>{{ device.name }}</strong>
                  <button
                    v-if="device.hardwareId"
                    class="icon-button icon-button--sm"
                    type="button"
                    aria-label="Rename device"
                    title="Rename"
                    @click="startRename(device)"
                  ><Pencil :size="14" /></button>
                </span>
              </td>
              <td>{{ device.type }}</td>
              <td><code>{{ device.hardwareId }}</code></td>
              <td><code>{{ device.port }}</code><small v-if="device.portMismatch">Configured port differs from latest scan</small></td>
              <td><StatusBadge compact :value="displayLabel(device.availability)" /></td>
              <td><StatusBadge compact :value="displayLabel(device.status)" /></td>
              <td><code>{{ device.configSource ?? (device.status === "unconfigured" ? "Not configured" : "No template") }}</code><small v-if="device.templateDrift">Template drift</small></td>
              <td>{{ device.owningSession ?? "—" }}</td>
              <td><code>{{ device.lastSeen ?? "—" }}</code></td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="state === 'ready' || state === 'empty'" class="scan-meta">
        <Clock3 :size="12" aria-hidden="true" />
        Scan <code>{{ scanId ?? "—" }}</code> · {{ scannedAtLabel }}
      </p>
    </BaseCard>

    <DeviceSettingsDialog
      v-if="activeDevice"
      :device="activeDevice"
      @close="activeDevice = null"
      @saved="onSaved"
    />
  </div>
</template>

<style scoped>
.data-table--clickable tbody tr { cursor: pointer; }
.data-table--clickable tbody tr:hover { background: var(--sage-50); }
.data-table--clickable tbody tr:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }
.device-name { cursor: default; }
.device-name__display, .device-name__edit { display: inline-flex; align-items: center; gap: 0.4rem; }
.device-name__edit input { min-height: 32px; padding: 0.2rem 0.5rem; border: 1px solid var(--border-card); border-radius: var(--radius); background: var(--surface-sage); }
.device-name__display .icon-button--sm { opacity: 0; transition: opacity 120ms; }
.device-name:hover .icon-button--sm { opacity: 1; }
.icon-button--sm { width: 26px; height: 26px; }
/* Footer band welded to the bottom edge of the workspace card. `flex: 0 0 auto`
   keeps it out of the internal table scroll, so it stays put as the list scrolls. */
.workspace-card > .scan-meta {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-1);
  margin: 0;
  padding: var(--space-2) var(--space-4);
  color: var(--muted);
  border-top: 1px solid var(--border-card);
  background: var(--sage-50);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}
.scan-meta code { color: inherit; font-size: var(--fs-xs); }
.scan-meta svg { opacity: 0.6; }
</style>
