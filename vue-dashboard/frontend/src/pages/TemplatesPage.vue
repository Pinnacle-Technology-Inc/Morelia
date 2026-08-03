<script setup>
import { Download, Plus } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import { loadDeviceTemplates, loadSessionTemplateCatalog } from "../templates-api";

const activeTab = ref("device-templates");
const deviceTemplates = ref([]);
const sessionTemplates = ref([]);
const state = ref("loading");
const errors = ref({ device: "", session: "" });
const tabs = [
  { id: "device-templates", label: "Device Templates" },
  { id: "session-templates", label: "Session Templates" },
];

async function refresh() {
  state.value = "loading";
  errors.value = { device: "", session: "" };
  const [deviceResult, sessionResult] = await Promise.allSettled([loadDeviceTemplates(), loadSessionTemplateCatalog()]);
  deviceTemplates.value = deviceResult.status === "fulfilled" ? deviceResult.value : [];
  sessionTemplates.value = sessionResult.status === "fulfilled" ? sessionResult.value : [];
  errors.value = {
    device: deviceResult.status === "rejected" ? (deviceResult.reason?.message ?? "Device templates unavailable.") : "",
    session: sessionResult.status === "rejected" ? (sessionResult.reason?.message ?? "Session templates unavailable.") : "",
  };
  state.value = "ready";
}

onMounted(refresh);
</script>

<template>
  <div class="page page--workspace">
    <PageHeader
      eyebrow="Reusable configuration"
      title="Templates"
      description="Manage reusable device and session templates."
    >
      <BaseButton><Plus :size="16" /> New Template</BaseButton>
      <BaseButton variant="secondary"><Download :size="16" /> Import Template</BaseButton>
    </PageHeader>

    <BaseCard class="workspace-card">
      <TabBar :tabs="tabs" :active="activeTab" @change="activeTab = $event" />
      <div v-if="state === 'loading'" class="empty-state" aria-busy="true">Loading templates…</div>
      <div v-else class="table-wrap">
        <p v-if="activeTab === 'device-templates' && errors.device" role="alert">{{ errors.device }}</p>
        <p v-if="activeTab === 'session-templates' && errors.session" role="alert">{{ errors.session }}</p>
        <table v-if="activeTab === 'device-templates'" class="data-table">
          <thead>
            <tr>
              <th>Template</th>
              <th>Device Type</th>
              <th>Content Hash</th>
              <th>File Path</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="template in deviceTemplates" :key="template.name">
              <td><strong>{{ template.name }}</strong></td>
              <td>{{ template.type }}</td>
              <td><code>{{ template.content_hash }}</code></td>
              <td><code>{{ template.file_path }}</code></td>
              <td><div class="row-actions"><button type="button" class="table-action">Open</button><button type="button" class="table-action">Edit</button><button type="button" class="table-action">Rename</button><button type="button" class="table-action">Delete</button><button type="button" class="table-action" disabled title="No export HTTP route is defined">Export</button></div></td>
            </tr>
          </tbody>
        </table>

        <table v-else class="data-table">
          <thead>
            <tr>
              <th>Template</th>
              <th>Source</th>
              <th>Policy</th>
              <th>Content Hash</th>
              <th>Warnings</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="template in sessionTemplates" :key="`${template.source}:${template.reference}`">
              <td><strong :title="template.reference">{{ template.name }}</strong></td>
              <td><StatusBadge :value="template.source === 'stored' ? 'Stored' : 'Draft'" compact /></td>
              <td>{{ template.content?.policy ?? "Unavailable" }}</td>
              <td><code>{{ template.content_hash }}</code></td>
              <td>{{ template.warnings?.length ?? "Unavailable" }}</td>
              <td><div class="row-actions"><button type="button" class="table-action">Open</button><button type="button" class="table-action">Use Template</button><button type="button" class="table-action">Delete</button><button type="button" class="table-action" disabled title="No export HTTP route is defined">Export</button></div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </BaseCard>
  </div>
</template>
