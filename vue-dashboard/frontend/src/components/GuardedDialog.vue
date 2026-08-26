<script setup>
import { X } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";

defineProps({
  title: { type: String, required: true },
  description: String,
  cancelLabel: { type: String, default: "Cancel" },
  confirmLabel: { type: String, default: "Confirm" },
  confirmDisabled: Boolean,
  danger: Boolean,
});
defineEmits(["close", "confirm"]);
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="$emit('close')">
    <section class="dialog" role="dialog" aria-modal="true" :aria-label="title">
      <header>
        <div><h2>{{ title }}</h2><p v-if="description">{{ description }}</p></div>
        <button class="icon-button" type="button" aria-label="Close dialog" @click="$emit('close')"><X :size="19" /></button>
      </header>
      <div class="dialog__content"><slot /></div>
      <footer>
        <BaseButton variant="secondary" @click="$emit('close')">{{ cancelLabel }}</BaseButton>
        <BaseButton
          :variant="danger ? 'danger' : 'primary'"
          :disabled="confirmDisabled"
          @click="$emit('confirm')"
        >{{ confirmLabel }}</BaseButton>
      </footer>
    </section>
  </div>
</template>
