<script setup>
import { FilePlus2, Pencil } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import { formatCentralTimestamp, timestampMs } from "../datetime";

defineProps({
  notes: { type: Array, default: () => [] },
  state: { type: String, default: "idle" },
  error: { type: String, default: "" },
});
defineEmits(["add", "edit"]);

function formatTimestamp(value) {
  return formatCentralTimestamp(value, { fallback: value ? String(value) : "Unavailable" });
}

function wasEdited(note) {
  if (!note.created_at || !note.updated_at) return false;
  const updatedAt = timestampMs(note.updated_at);
  const createdAt = timestampMs(note.created_at);
  return updatedAt !== null && createdAt !== null && updatedAt > createdAt;
}
</script>

<template>
  <section class="session-notes">
    <header class="session-notes__heading">
      <div>
        <h4>Notes</h4>
        <p v-if="state !== 'loading' && state !== 'unavailable' && !notes.length">
          No notes have been added.
        </p>
      </div>
      <BaseButton variant="secondary" size="small" @click="$emit('add')">
        <FilePlus2 :size="15" /> Add note
      </BaseButton>
    </header>

    <p v-if="state === 'loading'" class="session-notes__message">Loading notes…</p>
    <p v-else-if="state === 'unavailable'" class="session-notes__message session-notes__message--error" role="alert">
      {{ error || "Notes are unavailable." }}
    </p>
    <ol v-else-if="notes.length" class="session-notes__list">
      <li v-for="note in notes" :key="note.id" class="session-note">
        <div class="session-note__content">
          <p>{{ note.body }}</p>
          <small v-if="note.show_timestamp">
            {{ formatTimestamp(note.created_at) }}
            <span v-if="wasEdited(note)"> · Edited {{ formatTimestamp(note.updated_at) }}</span>
          </small>
        </div>
        <BaseButton
          variant="secondary"
          size="small"
          :aria-label="`Edit note ${note.id}`"
          @click="$emit('edit', note)"
        >
          <Pencil :size="14" /> Edit
        </BaseButton>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.session-notes {
  display: grid;
  gap: var(--space-3);
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border-card);
}

.session-notes__heading,
.session-note {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.session-notes__heading h4,
.session-notes__heading p,
.session-note p {
  margin: 0;
}

.session-notes__heading h4 {
  color: var(--text-heading);
  font: var(--fw-bold) 0.9rem/var(--lh-heading) var(--font-display);
}

.session-notes__heading p,
.session-note small,
.session-notes__message {
  color: var(--text-muted);
}

.session-notes__heading p,
.session-note small {
  font-size: var(--fs-xs);
}

.session-notes__list {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.session-note {
  padding: var(--space-3);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-sm);
  background: var(--surface-sage);
}

.session-note__content {
  display: grid;
  gap: var(--space-2);
  min-width: 0;
}

.session-note p {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.session-notes__message--error {
  color: var(--error);
}

@media (max-width: 560px) {
  .session-notes__heading,
  .session-note {
    display: grid;
  }
}
</style>
