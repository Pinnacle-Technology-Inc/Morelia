<script setup>
import { computed } from "vue";
import { AlertCircle, AlertTriangle, CheckCircle2 } from "@lucide/vue";

const props = defineProps({
  status: { type: String, default: "NEEDS_VALIDATION" },
  size: { type: Number, default: 19 },
});

const presentation = computed(() => ({
  VALID: { label: "Valid", tone: "valid", icon: CheckCircle2 },
  NEEDS_VALIDATION: { label: "Needs validation", tone: "warning", icon: AlertTriangle },
  INVALID: { label: "Invalid", tone: "invalid", icon: AlertCircle },
}[props.status] ?? { label: "Needs validation", tone: "warning", icon: AlertTriangle }));
</script>

<template>
  <span
    class="device-template-status"
    :class="`device-template-status--${presentation.tone}`"
    :aria-label="presentation.label"
    :title="presentation.label"
    role="img"
  >
    <component :is="presentation.icon" :size="size" aria-hidden="true" />
  </span>
</template>

<style scoped>
.device-template-status {
  display: inline-grid;
  place-items: center;
  vertical-align: middle;
}

.device-template-status--valid { color: var(--success); }
.device-template-status--warning { color: var(--warning); }
.device-template-status--invalid { color: var(--error); }
</style>
