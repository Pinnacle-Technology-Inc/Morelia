<script setup>
import { AlertTriangle, X } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";

defineProps({
  message: { type: String, required: true },
  actionLabel: { type: String, default: "" },
});
defineEmits(["close", "action"]);
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="$emit('close')" @keydown.esc="$emit('close')">
    <section class="dialog command-error" role="alertdialog" aria-modal="true" aria-labelledby="command-error-title" aria-describedby="command-error-message">
      <header>
        <div>
          <h2 id="command-error-title"><AlertTriangle :size="20" /> Session command could not complete</h2>
          <p id="command-error-message">{{ message }}</p>
        </div>
        <button class="icon-button" type="button" aria-label="Dismiss error" autofocus @click="$emit('close')">
          <X :size="19" />
        </button>
      </header>
      <footer>
        <BaseButton variant="secondary" @click="$emit('close')">Dismiss</BaseButton>
        <BaseButton v-if="actionLabel" @click="$emit('action')">{{ actionLabel }}</BaseButton>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.command-error { width: min(560px, 100%); }
.command-error h2 { display: flex; align-items: center; gap: var(--space-2); }
</style>
