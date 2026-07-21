<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

const now = ref(new Date());
let timer;

onMounted(() => {
  timer = window.setInterval(() => {
    now.value = new Date();
  }, 1000);
});

onBeforeUnmount(() => window.clearInterval(timer));

const timeLabel = computed(() =>
  now.value.toLocaleTimeString("en-US", { hour12: false, timeZone: "America/Chicago" }),
);
</script>

<template>
  <header class="app-header">
    <div class="header-intro">
     
      <div class="header-intro__copy">
        <span class="header-eyebrow">Operational overview</span>
        <strong class="header-title">Acquisition control center</strong>
        <span class="header-description">
          Monitor active sessions, review recovery decisions, and confirm system readiness from one workspace.
        </span>
      </div>
    </div>

    <div class="header-actions">
      <span class="header-time">{{ timeLabel }} America/Chicago</span>
    </div>
  </header>
</template>
