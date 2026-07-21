<script setup>
defineProps({ title: { type: String, required: true } });
</script>

<template>
  <div class="section-title">
    <h2>{{ title }}</h2>
    <slot />
  </div>
</template>

