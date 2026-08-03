<script setup>
defineProps({
  tabs: { type: Array, required: true },
  active: { type: String, required: true },
  counts: { type: Object, default: () => ({}) },
  // Per-tab severity for the count badge, keyed by tab id: "good" | "warn" |
  // "bad". Lets the strip answer "which tab should I open" without duplicating
  // the flow bar's content. Omitted ids keep the default amber badge.
  tones: { type: Object, default: () => ({}) },
});
defineEmits(["change"]);
</script>

<template>
  <div class="tab-bar" role="tablist">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      type="button"
      role="tab"
      :class="{ active: active === tab.id }"
      :aria-selected="active === tab.id"
      @click="$emit('change', tab.id)"
    >
      {{ tab.label }}
      <!-- The count is inside the accessible name rather than a bare number, so
           a screen reader hears "Streams, 2 need attention" instead of "Streams 2". -->
      <span
        v-if="Object.hasOwn(counts, tab.id)"
        :class="tones[tab.id] ? `tab-count--${tones[tab.id]}` : null"
      >
        {{ counts[tab.id] }}
        <span v-if="tones[tab.id] && tones[tab.id] !== 'good'" class="visually-hidden">
          need attention
        </span>
      </span>
    </button>
  </div>
</template>
