<script setup>
defineProps({
  variant: { type: String, default: "primary" },
  size: { type: String, default: "medium" },
  disabled: Boolean,
  type: { type: String, default: "button" },
});
</script>

<template>
  <button
    class="button"
    :class="[`button--${variant}`, `button--${size}`]"
    :disabled="disabled"
    :type="type"
  >
    <slot />
  </button>
</template>
