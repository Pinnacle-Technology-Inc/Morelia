<script setup>
// Folder picker for sink destinations. This browses the machine running the
// backend over the API — the same machine that opens the sink file — and
// returns whole absolute paths. A native browser file dialog is not usable
// here: it can only see the machine the BROWSER runs on, and it never reveals
// the chosen directory at all, only a filename.
import { computed, ref, watch } from "vue";
import { AlertTriangle, ChevronRight, CornerLeftUp, Folder, FolderPlus, HardDrive } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import { browseDirectories, browseRoots, createDirectory } from "../filesystem-api";

const props = defineProps({
  // Absolute host folder to open on. Blank starts at the host's OUTPUT_DIR.
  modelValue: { type: String, default: "" },
});
const emit = defineEmits(["close", "select"]);

const listing = ref(null);
const roots = ref(null);
const state = ref("loading");
const error = ref("");
const creating = ref(false);
const newFolderName = ref("");

// At a filesystem root the backend reports parent: null — there is nothing to
// go up to, so offer the drive list instead of a dead "Up" button.
const atRoot = computed(() => listing.value != null && listing.value.parent == null);

async function open(path) {
  state.value = "loading";
  error.value = "";
  roots.value = null;
  try {
    listing.value = await browseDirectories(path);
    state.value = "ready";
  } catch (problem) {
    state.value = "error";
    error.value = problem.problem?.detail ?? problem.message ?? "Unable to read that folder.";
  }
}

async function showRoots() {
  state.value = "loading";
  error.value = "";
  try {
    roots.value = (await browseRoots()).roots;
    state.value = "ready";
  } catch (problem) {
    state.value = "error";
    error.value = problem.problem?.detail ?? problem.message ?? "Unable to list drives.";
  }
}

async function addFolder() {
  const name = newFolderName.value.trim();
  if (!name) return;
  try {
    // The API returns the NEW folder's listing, so creating also navigates into
    // it — the operator's next action is almost always "use this one".
    listing.value = await createDirectory(listing.value?.path ?? "", name);
    state.value = "ready";
    creating.value = false;
    newFolderName.value = "";
    error.value = "";
  } catch (problem) {
    error.value = problem.problem?.detail ?? problem.message ?? "Unable to create that folder.";
  }
}

watch(() => props.modelValue, (path) => open(path ?? ""), { immediate: true });
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="$emit('close')">
    <section class="dialog folder-picker" role="dialog" aria-modal="true" aria-label="Choose output folder">
      <header>
        <div>
          <h2>Choose output folder</h2>
          <p>Folders on this machine. Starts at the configured output directory.</p>
        </div>
      </header>

      <div class="dialog__content">
        <div class="folder-crumbs">
          <button v-if="!atRoot" type="button" class="table-action" :disabled="!listing" @click="open(listing.parent)">
            <CornerLeftUp :size="14" /> Up
          </button>
          <button v-else type="button" class="table-action" @click="showRoots">
            <HardDrive :size="14" /> Drives
          </button>
          <code class="folder-crumb-path">{{ roots ? "Drives" : listing?.path ?? "…" }}</code>
        </div>

        <p v-if="error" class="form-notice" role="alert"><AlertTriangle :size="18" /> {{ error }}</p>
        <!-- "Missing" and "read-only" are different problems with different
             fixes, and the backend reports them separately. Collapsing both into
             "not writable" sends an operator hunting for a permission problem
             when the path simply isn't a directory — which is what happens when
             a template's sink_location names a FILE. -->
        <p v-else-if="listing && !roots && !listing.exists" class="form-notice">
          <AlertTriangle :size="18" />
          <span>
            No folder at this path — it may have been moved, renamed, or it names
            a file rather than a directory. Go up and pick an existing folder, or
            create one below.
          </span>
        </p>
        <p v-else-if="listing && !roots && !listing.writable" class="form-notice">
          <AlertTriangle :size="18" /> This folder is not writable — a session writing here will fail to start.
        </p>

        <ul v-if="state === 'ready' && roots" class="folder-list">
          <li v-for="root in roots" :key="root.path">
            <button type="button" @click="open(root.path)">
              <HardDrive :size="15" /><span>{{ root.name }}</span><ChevronRight :size="14" />
            </button>
          </li>
        </ul>
        <ul v-else-if="state === 'ready'" class="folder-list">
          <li v-if="!listing.directories.length" class="folder-empty">No subfolders here.</li>
          <li v-for="entry in listing.directories" :key="entry.path">
            <button type="button" @click="open(entry.path)">
              <Folder :size="15" /><span>{{ entry.name }}</span><ChevronRight :size="14" />
            </button>
          </li>
        </ul>
        <p v-else-if="state === 'loading'" class="folder-empty">Loading…</p>

        <div v-if="creating" class="folder-create">
          <input v-model="newFolderName" class="sink-control" placeholder="New folder name" @keyup.enter="addFolder" />
          <BaseButton variant="secondary" @click="addFolder">Create</BaseButton>
          <button type="button" class="table-action" @click="creating = false">Cancel</button>
        </div>
        <button v-else-if="!roots" type="button" class="table-action" @click="creating = true">
          <FolderPlus :size="14" /> New folder
        </button>
      </div>

      <footer>
        <BaseButton variant="secondary" @click="$emit('close')">Cancel</BaseButton>
        <!-- A path that isn't a directory can't be confirmed: picking it would
             store a destination the runtime is guaranteed to fail to open. -->
        <BaseButton :disabled="state !== 'ready' || !!roots || !listing?.exists" @click="$emit('select', listing.path)">
          Use this folder
        </BaseButton>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.folder-picker {
  width: min(560px, 92vw);
}
.folder-crumbs {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.folder-crumb-path {
  overflow: hidden;
  color: var(--muted);
  font-size: 0.78rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.folder-list {
  max-height: 300px;
  margin: 0 0 var(--space-3);
  padding: 0;
  overflow-y: auto;
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  list-style: none;
}
.folder-list li + li {
  border-top: 1px solid var(--border-card);
}
.folder-list button {
  display: flex;
  width: 100%;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 0;
  background: transparent;
  font-size: var(--fs-sm);
  text-align: left;
  cursor: pointer;
}
.folder-list button:hover {
  background: var(--surface-sage);
}
.folder-list button span {
  flex: 1;
}
.folder-empty {
  padding: var(--space-3);
  color: var(--muted);
  font-size: 0.8rem;
}
.folder-create {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.folder-create .sink-control {
  flex: 1;
  min-height: 36px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--surface-sage);
  font-size: var(--fs-sm);
}
</style>
