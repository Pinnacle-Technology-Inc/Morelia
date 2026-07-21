<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { AlertTriangle, RefreshCw, ShieldCheck } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { listOperations, resolveOperation } from "../operations-api";

const operations = ref([]);
const isLoading = ref(false);
const loadError = ref("");
const selectedOperationId = ref(null);
const resolvingId = ref(null);
const resolution = reactive({
  resolvedBy: "",
  resolutionNote: "",
});

const selectedOperation = computed(() =>
  operations.value.find((operation) => operation.operation_id === selectedOperationId.value) ?? null,
);

onMounted(loadUncertainOperations);

async function loadUncertainOperations() {
  isLoading.value = true;
  loadError.value = "";
  try {
    operations.value = await listOperations({ state: "uncertain" });
    if (!operations.value.some((operation) => operation.operation_id === selectedOperationId.value)) {
      selectedOperationId.value = operations.value[0]?.operation_id ?? null;
    }
  } catch (error) {
    loadError.value = error.problem?.detail ?? error.message ?? "Unable to load operations.";
  } finally {
    isLoading.value = false;
  }
}

async function submitResolution() {
  if (!selectedOperation.value) return;
  resolvingId.value = selectedOperation.value.operation_id;
  loadError.value = "";
  try {
    await resolveOperation(selectedOperation.value.operation_id, resolution);
    resolution.resolvedBy = "";
    resolution.resolutionNote = "";
    await loadUncertainOperations();
  } catch (error) {
    loadError.value = error.problem?.detail ?? error.message ?? "Unable to resolve operation.";
  } finally {
    resolvingId.value = null;
  }
}

function stateLabel(value) {
  if (!value) return "Unknown";
  return value[0].toUpperCase() + value.slice(1);
}

function formatTimestamp(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function operationSession(operation) {
  return operation.session_name ?? operation.details?.session_name ?? (operation.session_id ? `Session ${operation.session_id}` : "-");
}

function operationStream(operation) {
  return operation.stream_label ?? operation.details?.stream_label ?? operation.target_device_id ?? "-";
}

function operationScope(operation) {
  const session = operationSession(operation);
  const stream = operationStream(operation);
  return operation.scope === "stream" && stream !== "-"
    ? `${session} · ${stream}`
    : session;
}
</script>

<template>
  <div class="page page--workspace">
    <PageHeader
      eyebrow="Operator resolution"
      title="Operations"
      description="Review interrupted command outcomes before continuing guarded lifecycle work."
    >
      <BaseButton variant="secondary" :disabled="isLoading" @click="loadUncertainOperations">
        <RefreshCw :size="16" />
        Refresh
      </BaseButton>
    </PageHeader>

    <BaseCard class="workspace-card">
      <div class="operation-toolbar">
        <div>
          <strong>{{ operations.length }}</strong>
          <span>uncertain</span>
        </div>
        <p v-if="loadError" role="alert"><AlertTriangle :size="16" /> {{ loadError }}</p>
      </div>

      <div v-if="isLoading" class="empty-state" aria-busy="true">
        <h3>Loading operations</h3>
      </div>

      <div v-else-if="!operations.length" class="empty-state">
        <ShieldCheck :size="36" />
        <h3>No uncertain operations</h3>
      </div>

      <div v-else class="operation-resolution-layout">
        <div class="table-wrap">
          <table class="data-table operations-table">
            <thead>
              <tr>
                <th>Operation</th>
                <th>Command</th>
                <th>Scope</th>
                <th>Session</th>
                <th>Stream</th>
                <th>Outcome</th>
                <th>Finished</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="operation in operations"
                :key="operation.operation_id"
                :class="{ selected: operation.operation_id === selectedOperationId }"
                @click="selectedOperationId = operation.operation_id"
              >
                <td>
                  <code>{{ operation.operation_id }}</code>
                  <small v-if="operation.error_code">{{ operation.error_code }}</small>
                </td>
                <td>{{ operation.command }}</td>
                <td>{{ operationScope(operation) }}</td>
                <td>{{ operationSession(operation) }}</td>
                <td><code>{{ operationStream(operation) }}</code></td>
                <td><StatusBadge :value="stateLabel(operation.state)" /></td>
                <td><code>{{ formatTimestamp(operation.finished_at) }}</code></td>
                <td><button class="table-action" type="button" @click.stop="selectedOperationId = operation.operation_id">Resolve</button></td>
              </tr>
            </tbody>
          </table>
        </div>

        <aside class="operation-resolution-panel" aria-labelledby="resolution-title">
          <header>
            <h2 id="resolution-title">Resolution</h2>
            <code v-if="selectedOperation">{{ selectedOperation.operation_id }}</code>
          </header>

          <dl v-if="selectedOperation" class="detail-list">
            <div><dt>Command</dt><dd>{{ selectedOperation.command }}</dd></div>
            <div><dt>Scope</dt><dd>{{ operationScope(selectedOperation) }}</dd></div>
            <div><dt>Session</dt><dd>{{ operationSession(selectedOperation) }}</dd></div>
            <div><dt>Stream</dt><dd>{{ operationStream(selectedOperation) }}</dd></div>
            <div><dt>Error</dt><dd>{{ selectedOperation.error_message ?? selectedOperation.error_code ?? "-" }}</dd></div>
          </dl>

          <form v-if="selectedOperation" class="resolution-form" @submit.prevent="submitResolution">
            <label class="field">
              <span>Resolved by</span>
              <input v-model.trim="resolution.resolvedBy" required type="text" autocomplete="name" />
            </label>
            <label class="field">
              <span>Resolution note</span>
              <textarea v-model.trim="resolution.resolutionNote" required />
            </label>
            <BaseButton
              type="submit"
              :disabled="!resolution.resolvedBy || !resolution.resolutionNote || resolvingId === selectedOperation.operation_id"
            >
              <ShieldCheck :size="16" />
              Record Resolution
            </BaseButton>
          </form>
          <section v-if="selectedOperation" class="command-diagnostics" aria-labelledby="command-diagnostics-title">
            <h3 id="command-diagnostics-title">Command Diagnostics</h3>
            <dl class="detail-list">
              <div><dt>Operation ID</dt><dd><code>{{ selectedOperation.operation_id }}</code></dd></div>
              <div><dt>Command ID</dt><dd><code>{{ selectedOperation.command_id ?? "-" }}</code></dd></div>
              <div><dt>Runtime ID</dt><dd><code>{{ selectedOperation.runtime_id ?? "-" }}</code></dd></div>
              <div><dt>Command status</dt><dd>{{ stateLabel(selectedOperation.state) }}</dd></div>
            </dl>
          </section>
        </aside>
      </div>
    </BaseCard>
  </div>
</template>
