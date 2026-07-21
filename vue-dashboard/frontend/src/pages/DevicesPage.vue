<script setup>
import { Plus, Radar } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import { devices } from "../data";
import { computed, ref } from "vue";

const activeTab = ref("all");
const tabs = [
  { id: "all", label: "All Devices" },
  { id: "available", label: "Available" },
  { id: "claimed", label: "Claimed" },
];

const counts = computed(() => ({
  all: devices.length,
  available: devices.filter((device) => device.status === "free").length,
  claimed: devices.filter((device) => device.status === "claimed").length,
}));

const visibleDevices = computed(() => {
  if (activeTab.value === "available") return devices.filter((device) => device.status === "free");
  if (activeTab.value === "claimed") return devices.filter((device) => device.status === "claimed");
  return devices;
});

function displayLabel(value) {
  return {
    available: "Available",
    not_found: "Not found",
    free: "Free",
    claimed: "Claimed",
    unconfigured: "Unconfigured",
  }[value] ?? value;
}
</script>

<template>
  <div class="page page--workspace">
    <PageHeader
      eyebrow="Hardware inventory"
      title="Devices"
      description="Review connected hardware, configured devices, availability, and session ownership."
    >
      <BaseButton variant="secondary"><Radar :size="16" /> Scan Devices</BaseButton>
      <BaseButton><Plus :size="16" /> Add Device Config</BaseButton>
    </PageHeader>

    <BaseCard class="workspace-card">
      <TabBar :tabs="tabs" :active="activeTab" :counts="counts" @change="activeTab = $event" />
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Device</th>
              <th>Type</th>
              <th>Hardware ID</th>
              <th>Port</th>
              <th>Availability</th>
              <th>Status</th>
              <th>Config Source</th>
              <th>Owning Session</th>
              <th>Last Seen</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="device in visibleDevices" :key="device.hardwareId">
              <td><strong>{{ device.name }}</strong></td>
              <td>{{ device.type }}</td>
              <td><code>{{ device.hardwareId }}</code></td>
              <td><code>{{ device.port }}</code><small v-if="device.portMismatch">Configured port differs from latest scan</small></td>
              <td><StatusBadge compact :value="displayLabel(device.availability)" /></td>
              <td><StatusBadge compact :value="displayLabel(device.status)" /></td>
              <td>{{ device.configSource }}<small v-if="device.templateDrift">Template drift</small></td>
              <td>{{ device.owningSession }}</td>
              <td><code>{{ device.lastSeen }}</code></td>
              <td>
                <div class="row-actions">
                  <button class="table-action" type="button">Open</button>
                  <button v-if="device.status === 'free'" class="table-action" type="button">Edit Config</button>
                  <button v-if="device.status === 'unconfigured'" class="table-action" type="button">Create Device Config</button>
                  <button v-if="device.status !== 'unconfigured'" class="table-action" type="button">Export Template</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </BaseCard>
  </div>
</template>
