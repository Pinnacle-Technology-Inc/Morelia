<script setup>
import { Download, Plus } from "@lucide/vue";
import { ref } from "vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import TabBar from "../components/TabBar.vue";
import { deviceTemplates, sessionTemplates } from "../data";

const activeTab = ref("device-templates");
const tabs = [
  { id: "device-templates", label: "Device Templates" },
  { id: "session-templates", label: "Session Templates" },
];
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
      <div class="table-wrap">
        <table v-if="activeTab === 'device-templates'" class="data-table">
          <thead>
            <tr>
              <th>Template</th>
              <th>Device Type</th>
              <th>Schema Version</th>
              <th>Content Hash</th>
              <th>Sessions Using</th>
              <th>Created</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="template in deviceTemplates" :key="template.name">
              <td><strong>{{ template.name }}</strong></td>
              <td>{{ template.type }}</td>
              <td><code>{{ template.schemaVersion }}</code></td>
              <td><code>{{ template.contentHash }}</code></td>
              <td>{{ template.sessionsUsing }}</td>
              <td><code>{{ template.created }}</code></td>
              <td><div class="row-actions"><button type="button" class="table-action">Open</button><button type="button" class="table-action">Edit</button><button type="button" class="table-action">Rename</button><button type="button" class="table-action">Delete</button><button type="button" class="table-action">Export</button></div></td>
            </tr>
          </tbody>
        </table>

        <table v-else class="data-table">
          <thead>
            <tr>
              <th>Template</th>
              <th>Streams</th>
              <th>Sinks</th>
              <th>Policy</th>
              <th>Source Session</th>
              <th>Last Exported</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="template in sessionTemplates" :key="template.name">
              <td><strong>{{ template.name }}</strong></td>
              <td>{{ template.streams }}</td>
              <td>{{ template.sinks }}</td>
              <td>{{ template.policy }}</td>
              <td>{{ template.sourceSession }}</td>
              <td><code>{{ template.lastExported }}</code></td>
              <td><div class="row-actions"><button type="button" class="table-action">Open</button><button type="button" class="table-action">Use Template</button><button type="button" class="table-action">Delete</button><button type="button" class="table-action">Export</button></div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </BaseCard>
  </div>
</template>
