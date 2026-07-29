<script setup>
import { onMounted, ref } from "vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import { archiveExperiment, createExperiment, deleteExperiment, loadExperiments } from "../experiments-api";

const experiments = ref([]);
const state = ref("loading");
const error = ref("");
const includeArchived = ref(false);
const name = ref("");
const description = ref("");
const busy = ref(false);

async function refresh() {
  state.value = "loading";
  error.value = "";
  try {
    const result = await loadExperiments({ includeArchived: includeArchived.value });
    experiments.value = Array.isArray(result) ? result : [];
    state.value = "live";
  } catch (err) {
    experiments.value = [];
    state.value = "unavailable";
    error.value = err instanceof Error ? err.message : "Experiments are unavailable.";
  }
}

async function create() {
  if (!name.value.trim()) return;
  busy.value = true;
  try {
    await createExperiment({ name: name.value, description: description.value || null });
    name.value = "";
    description.value = "";
    await refresh();
  } catch (err) { error.value = err instanceof Error ? err.message : "Could not create experiment."; } finally { busy.value = false; }
}

async function archive(row) {
  if (!window.confirm(`Archive ${row.name}? It cannot receive new session assignments.`)) return;
  busy.value = true;
  try { await archiveExperiment(row.id); await refresh(); } catch (err) { error.value = err instanceof Error ? err.message : "Could not archive experiment."; } finally { busy.value = false; }
}

async function hardDelete(row) {
  if (!window.confirm(`Permanently delete ${row.name}?`)) return;
  busy.value = true;
  try { await deleteExperiment(row.id); await refresh(); } catch (err) { error.value = err instanceof Error ? err.message : "Could not delete experiment."; } finally { busy.value = false; }
}

onMounted(refresh);
</script>

<template>
  <div class="page page--workspace">
    <PageHeader eyebrow="Organizational workspace" title="Experiments" description="Group related sessions without affecting hardware execution." />
    <BaseCard class="workspace-card">
      <div class="detail-tab-actions"><label><input v-model="includeArchived" type="checkbox" @change="refresh" /> Include archived</label></div>
      <form class="dialog-form" @submit.prevent="create"><label class="field"><span>Name</span><input v-model="name" required maxlength="255" /></label><label class="field"><span>Description</span><textarea v-model="description" maxlength="4000" /></label><BaseButton type="submit" :disabled="busy">Create Experiment</BaseButton></form>
      <p v-if="state === 'loading'">Loading experiments…</p>
      <p v-else-if="state === 'unavailable'" class="detail-alert">{{ error }}</p>
      <p v-else-if="!experiments.length">No experiments found.</p>
      <div v-else class="table-wrap"><table class="data-table"><thead><tr><th>Name</th><th>Description</th><th>State</th><th /></tr></thead><tbody><tr v-for="row in experiments" :key="row.id"><td><strong>{{ row.name }}</strong></td><td>{{ row.description ?? "—" }}</td><td>{{ row.archived_at ? "Archived" : "Active" }}</td><td><button v-if="!row.archived_at" class="table-action" type="button" @click="archive(row)">Archive</button><button v-if="row.archived_at" class="table-action" type="button" @click="hardDelete(row)">Delete</button></td></tr></tbody></table></div>
      <p v-if="error && state === 'live'" class="detail-alert">{{ error }}</p>
    </BaseCard>
  </div>
</template>
