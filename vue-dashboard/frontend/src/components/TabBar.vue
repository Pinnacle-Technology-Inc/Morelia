<script setup>
defineProps({
  tabs: { type: Array, required: true },
  active: { type: String, required: true },
  counts: { type: Object, default: () => ({}) },
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
      <span v-if="Object.hasOwn(counts, tab.id)">{{ counts[tab.id] }}</span>
    </button>
  </div>
</template>
