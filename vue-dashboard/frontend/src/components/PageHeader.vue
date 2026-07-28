<script setup>
defineProps({
  eyebrow: String,
  title: { type: String, required: true },
  description: String,
});
</script>

<template>
  <header class="page-header">
    <div>
      <!--<p v-if="eyebrow" class="eyebrow">{{ eyebrow }}</p>-->
      <h1>{{ title }}</h1>
      <p v-if="description">{{ description }}</p>
    </div>
    <div class="page-header__actions"><slot /></div>
  </header>
</template>

