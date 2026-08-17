<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import pinnacleLogo from "../assets/pinnacle-technology-logo.png";
import { formatCentralTime } from "../datetime";

const now = ref(new Date());
let timer;

onMounted(() => {
  timer = window.setInterval(() => {
    now.value = new Date();
  }, 1000);
});

onBeforeUnmount(() => window.clearInterval(timer));

const timeLabel = computed(() =>
  formatCentralTime(now.value, { hour12: false }),
);
</script>

<template>
  <header class="app-header">
    <div class="header-intro">
     
      <div class="header-intro__copy">
        <span class="header-eyebrow">{{ timeLabel }}</span>
        <strong class="header-title">Acquisition control center</strong>
        <span class="header-description">
          Monitor active sessions, review recovery decisions, and confirm system readiness from one workspace.
        </span>
      </div>
    </div>

    <div class="header-actions">
      <img
        class="header-logo"
        :src="pinnacleLogo"
        alt="Pinnacle Technology"
      />
    </div>
  </header>
</template>
