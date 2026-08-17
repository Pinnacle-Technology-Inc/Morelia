<script setup>
import {
  Archive,
  FlaskConical,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  SearchX,
  Trash2,
} from "@lucide/vue";
import { computed, nextTick, onMounted, ref } from "vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import GuardedDialog from "../components/GuardedDialog.vue";
import PageHeader from "../components/PageHeader.vue";
import {
  archiveExperiment,
  createExperiment,
  deleteExperiment,
  loadExperiments,
  updateExperiment,
} from "../experiments-api";
import {
  experimentErrorMessage,
  filterExperiments,
  summarizeExperiments,
} from "../experiment-utils";
import { formatCentralTimestamp } from "../datetime";

const experiments = ref([]);
const state = ref("loading");
const pageError = ref("");
const notice = ref("");
const includeArchived = ref(false);
const search = ref("");

const formOpen = ref(false);
const editingExperiment = ref(null);
const formName = ref("");
const formDescription = ref("");
const formError = ref("");
const nameInput = ref(null);

const pendingAction = ref(null);
const busyAction = ref("");

const summary = computed(() => summarizeExperiments(experiments.value));
const visibleExperiments = computed(() => filterExperiments(experiments.value, search.value));
const isEditing = computed(() => Boolean(editingExperiment.value));
const formTitle = computed(() => isEditing.value ? "Edit experiment" : "New experiment");
const formDescriptionText = computed(() => isEditing.value
  ? "Update the organizational details shown across Morelia."
  : "Create an organizational group for related session runs.");
const formSubmitLabel = computed(() => {
  if (busyAction.value === "save") return isEditing.value ? "Saving…" : "Creating…";
  return isEditing.value ? "Save changes" : "Create experiment";
});
const confirmTitle = computed(() => pendingAction.value?.kind === "delete"
  ? "Permanently delete experiment?"
  : "Archive experiment?");
const confirmDescription = computed(() => pendingAction.value?.kind === "delete"
  ? "This cannot be undone. Deletion succeeds only when no sessions reference the experiment."
  : "Existing sessions keep their historical link, but new sessions can no longer use this experiment.");
const confirmLabel = computed(() => {
  if (busyAction.value === "confirm") return pendingAction.value?.kind === "delete" ? "Deleting…" : "Archiving…";
  return pendingAction.value?.kind === "delete" ? "Delete permanently" : "Archive experiment";
});

function formatDate(value) {
  return formatCentralTimestamp(value, { second: undefined });
}

async function refresh({ silent = false } = {}) {
  if (!silent) state.value = "loading";
  pageError.value = "";
  try {
    const result = await loadExperiments({ includeArchived: includeArchived.value });
    experiments.value = Array.isArray(result) ? result : [];
    state.value = "live";
  } catch (error) {
    if (!silent) experiments.value = [];
    state.value = silent && experiments.value.length ? "live" : "unavailable";
    pageError.value = experimentErrorMessage(error);
  }
}

function openForm(experiment = null) {
  editingExperiment.value = experiment;
  formName.value = experiment?.name ?? "";
  formDescription.value = experiment?.description ?? "";
  formError.value = "";
  notice.value = "";
  formOpen.value = true;
  nextTick(() => nameInput.value?.focus());
}

function closeForm() {
  if (busyAction.value) return;
  formOpen.value = false;
}

async function submitForm() {
  const normalizedName = formName.value.trim();
  if (!normalizedName || busyAction.value) return;
  busyAction.value = "save";
  formError.value = "";
  try {
    const payload = {
      name: normalizedName,
      description: formDescription.value.trim() || null,
    };
    if (editingExperiment.value) {
      await updateExperiment(editingExperiment.value.id, payload);
      notice.value = `Saved changes to ${normalizedName}.`;
    } else {
      await createExperiment(payload);
      notice.value = `Created ${normalizedName}.`;
    }
    formOpen.value = false;
    await refresh({ silent: true });
  } catch (error) {
    formError.value = experimentErrorMessage(error, "Could not save this experiment.");
  } finally {
    busyAction.value = "";
  }
}

function requestAction(experiment, kind) {
  notice.value = "";
  pageError.value = "";
  pendingAction.value = { experiment, kind };
}

function closeConfirmation() {
  if (busyAction.value) return;
  pendingAction.value = null;
}

async function confirmAction() {
  if (!pendingAction.value || busyAction.value) return;
  const { experiment, kind } = pendingAction.value;
  busyAction.value = "confirm";
  pageError.value = "";
  try {
    if (kind === "delete") {
      await deleteExperiment(experiment.id);
      notice.value = `Permanently deleted ${experiment.name}.`;
    } else {
      await archiveExperiment(experiment.id);
      notice.value = `Archived ${experiment.name}.`;
    }
    pendingAction.value = null;
    await refresh({ silent: true });
  } catch (error) {
    pendingAction.value = null;
    pageError.value = experimentErrorMessage(error, `Could not ${kind} this experiment.`);
  } finally {
    busyAction.value = "";
  }
}

onMounted(refresh);
</script>

<template>
  <div class="page page--workspace experiments-page">
    <PageHeader
      eyebrow="Organizational workspace"
      title="Experiments"
      description="Group related session runs without changing device, dataflow, or runtime behavior."
    >
      <BaseButton @click="openForm()"><Plus :size="16" /> New experiment</BaseButton>
    </PageHeader>

    <BaseCard class="workspace-card">
      <div class="experiment-summary" aria-label="Experiment summary">
        <div><strong>{{ summary.active }}</strong><span>Active</span></div>
        <div>
          <strong>{{ includeArchived ? summary.archived : "—" }}</strong>
          <span>{{ includeArchived ? "Archived" : "Archived hidden" }}</span>
        </div>
        <div><strong>{{ summary.total }}</strong><span>Loaded</span></div>
      </div>

      <div class="experiment-toolbar">
        <label class="search-field">
          <Search :size="16" aria-hidden="true" />
          <span class="visually-hidden">Search experiments</span>
          <input v-model="search" type="search" placeholder="Search name or description…" />
        </label>
        <label class="archive-toggle">
          <input v-model="includeArchived" type="checkbox" @change="refresh()" />
          <span>Show archived</span>
        </label>
        <BaseButton
          variant="quiet"
          size="small"
          :disabled="state === 'loading'"
          @click="refresh()"
        ><RefreshCw :size="15" /> Refresh</BaseButton>
      </div>

      <div v-if="notice" class="experiment-notice" role="status">
        <span>{{ notice }}</span>
        <button type="button" aria-label="Dismiss message" @click="notice = ''">Dismiss</button>
      </div>
      <div v-if="pageError && state === 'live'" class="detail-alert" role="alert">
        <span>{{ pageError }}</span>
        <button type="button" @click="refresh({ silent: true })">Try again</button>
      </div>

      <div v-if="state === 'loading'" class="experiment-loading" aria-busy="true" aria-label="Loading experiments">
        <div v-for="row in 4" :key="row" />
      </div>

      <div v-else-if="state === 'unavailable'" class="empty-state" role="alert">
        <FlaskConical :size="38" aria-hidden="true" />
        <h2>Experiments are unavailable</h2>
        <p>{{ pageError }}</p>
        <BaseButton variant="secondary" @click="refresh()"><RefreshCw :size="15" /> Try again</BaseButton>
      </div>

      <div v-else-if="!experiments.length" class="empty-state">
        <FlaskConical :size="38" aria-hidden="true" />
        <h2>{{ includeArchived ? "No experiments yet" : "No active experiments yet" }}</h2>
        <p>Create an experiment to organize related session runs.</p>
        <BaseButton @click="openForm()"><Plus :size="15" /> New experiment</BaseButton>
      </div>

      <div v-else-if="!visibleExperiments.length" class="empty-state" role="status">
        <SearchX :size="38" aria-hidden="true" />
        <h2>No matching experiments</h2>
        <p>Try a different name or description.</p>
        <BaseButton variant="quiet" @click="search = ''">Clear search</BaseButton>
      </div>

      <div v-else class="table-wrap">
        <table class="data-table experiments-table">
          <thead>
            <tr><th>Experiment</th><th>Status</th><th>Last updated</th><th><span class="visually-hidden">Actions</span></th></tr>
          </thead>
          <tbody>
            <tr v-for="experiment in visibleExperiments" :key="experiment.id">
              <td>
                <strong>{{ experiment.name }}</strong>
                <p>{{ experiment.description || "No description" }}</p>
              </td>
              <td>
                <span class="status-badge" :class="experiment.archived_at ? 'status-badge--neutral' : 'status-badge--green'">
                  {{ experiment.archived_at ? "Archived" : "Active" }}
                </span>
              </td>
              <td><time :datetime="experiment.updated_at">{{ formatDate(experiment.updated_at) }}</time></td>
              <td>
                <div class="row-actions">
                  <BaseButton
                    v-if="!experiment.archived_at"
                    variant="quiet"
                    size="small"
                    :aria-label="`Edit ${experiment.name}`"
                    @click="openForm(experiment)"
                  ><Pencil :size="14" /> Edit</BaseButton>
                  <BaseButton
                    v-if="!experiment.archived_at"
                    variant="ghost"
                    size="small"
                    :aria-label="`Archive ${experiment.name}`"
                    @click="requestAction(experiment, 'archive')"
                  ><Archive :size="14" /> Archive</BaseButton>
                  <BaseButton
                    v-else
                    variant="danger"
                    size="small"
                    :aria-label="`Permanently delete ${experiment.name}`"
                    @click="requestAction(experiment, 'delete')"
                  ><Trash2 :size="14" /> Delete</BaseButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </BaseCard>

    <GuardedDialog
      v-if="formOpen"
      :title="formTitle"
      :description="formDescriptionText"
      :confirm-label="formSubmitLabel"
      :confirm-disabled="!formName.trim() || Boolean(busyAction)"
      @close="closeForm"
      @confirm="submitForm"
    >
      <form class="dialog-form" @submit.prevent="submitForm">
        <label class="field">
          <span>Name</span>
          <input ref="nameInput" v-model="formName" required maxlength="255" autocomplete="off" />
        </label>
        <label class="field">
          <span>Description <small>(optional)</small></span>
          <textarea v-model="formDescription" maxlength="4000" rows="5" />
        </label>
        <p class="form-helper">Experiments organize sessions only. They never start or stop hardware.</p>
        <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
        <button class="visually-hidden" type="submit" tabindex="-1">Submit</button>
      </form>
    </GuardedDialog>

    <GuardedDialog
      v-if="pendingAction"
      :title="confirmTitle"
      :description="confirmDescription"
      :confirm-label="confirmLabel"
      :confirm-disabled="Boolean(busyAction)"
      :danger="pendingAction.kind === 'delete'"
      @close="closeConfirmation"
      @confirm="confirmAction"
    >
      <div class="confirmation-target">
        <span>Experiment</span>
        <strong>{{ pendingAction.experiment.name }}</strong>
      </div>
    </GuardedDialog>
  </div>
</template>

<style scoped>
.experiment-summary {
  display: flex;
  flex: 0 0 auto;
  gap: var(--space-6);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--border-card);
  background: var(--sage-50);
}

.experiment-summary > div { display: flex; align-items: baseline; gap: var(--space-2); }
.experiment-summary strong { color: var(--primary); font: var(--fw-xbold) var(--fs-lg) var(--font-mono); }
.experiment-summary span { color: var(--text-muted); font-size: var(--fs-xs); font-weight: var(--fw-semibold); }

.experiment-toolbar {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-card);
}

.experiment-toolbar .search-field { flex: 1 1 260px; }
.archive-toggle { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--text-body); font-size: var(--fs-xs); font-weight: var(--fw-bold); cursor: pointer; }
.archive-toggle input { width: 16px; height: 16px; accent-color: var(--primary); }

.experiment-notice {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
  color: var(--success);
  border-bottom: 1px solid var(--sage-200);
  background: var(--sage-50);
  font-size: var(--fs-sm);
  font-weight: var(--fw-semibold);
}

.experiment-notice button { color: var(--primary); border: 0; background: transparent; font-size: var(--fs-xs); font-weight: var(--fw-bold); cursor: pointer; }
.workspace-card > .detail-alert { margin: var(--space-3) var(--space-4) 0; }

.experiment-loading { display: grid; flex: 1 1 auto; align-content: start; gap: 1px; background: var(--border-card); }
.experiment-loading div { height: 72px; background: linear-gradient(90deg, var(--surface-card), var(--sage-50), var(--surface-card)); background-size: 200% 100%; animation: shimmer 1.2s linear infinite; }
@keyframes shimmer { to { background-position: -200% 0; } }

.empty-state { padding: var(--space-6); }
.empty-state svg { color: var(--text-accent); }
.empty-state h2 { font-size: var(--fs-lg); }
.empty-state p { max-width: 440px; color: var(--text-muted); font-size: var(--fs-sm); line-height: var(--lh-body); }
.empty-state .button { margin-top: var(--space-3); }

.experiments-table { min-width: 760px; }
.experiments-table tbody tr { cursor: default; }
.experiments-table td:first-child { width: 52%; }
.experiments-table td:first-child p { max-width: 620px; margin-top: var(--space-1); overflow: hidden; color: var(--text-muted); font-size: var(--fs-xs); line-height: var(--lh-body); text-overflow: ellipsis; white-space: nowrap; }
.experiments-table time { color: var(--text-muted); font: var(--fs-xs) var(--font-mono); white-space: nowrap; }
.experiments-table th:last-child, .experiments-table td:last-child { text-align: right; }

.field small { color: var(--text-muted); font-weight: var(--fw-regular); }
.form-helper { color: var(--text-muted); font-size: var(--fs-xs); line-height: var(--lh-body); }
.form-error { padding: var(--space-3); color: var(--error); border: 1px solid #dfaaa6; border-radius: var(--radius-md); background: #faf0ef; font-size: var(--fs-xs); }
.confirmation-target { display: grid; gap: var(--space-1); padding: var(--space-4); border: 1px solid var(--border-card); border-radius: var(--radius-md); background: var(--sage-50); }
.confirmation-target span { color: var(--text-muted); font-size: var(--fs-xs); font-weight: var(--fw-bold); text-transform: uppercase; }

@media (max-width: 640px) {
  .experiment-summary { justify-content: space-between; gap: var(--space-3); }
  .experiment-summary > div { display: grid; gap: 0; }
  .experiment-toolbar .search-field { flex-basis: 100%; }
  .experiment-toolbar .button { flex: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .experiment-loading div { animation: none; }
}
</style>
