<script setup>
import {
  AlertTriangle,
  Cpu,
  FileText,
  FlaskConical,
  List,
  ListChecks,
  Monitor,
  Plus,
  Server,
} from "@lucide/vue";

defineProps({ active: { type: String, required: true } });
// A run always starts from a template now, so the global create action makes a
// template rather than a blank session.
defineEmits(["change", "new-template"]);

const items = [
  { id: "overview", label: "Overview", icon: Monitor },
  { id: "sessions", label: "Sessions", icon: List },
  { id: "experiments", label: "Experiments", icon: FlaskConical },
  { id: "devices", label: "Devices", icon: Cpu },
  { id: "templates", label: "Templates", icon: FileText },
  { id: "incidents", label: "Incidents & Gaps", icon: AlertTriangle, count: 1 },
  { id: "operations", label: "Operations", icon: ListChecks },
  { id: "system-health", label: "System Health", icon: Server },
];
</script>

<template>
  <nav class="primary-nav" aria-label="Primary navigation">
    <div class="primary-nav__items">
      <button
        v-for="item in items"
        :key="item.id"
        type="button"
        :class="{ active: active === item.id }"
        :aria-current="active === item.id ? 'page' : undefined"
        @click="$emit('change', item.id)"
      >
        <component :is="item.icon" :size="17" />
        {{ item.label }}
        <span v-if="item.count" class="nav-count">{{ item.count }}</span>
      </button>
    </div>
    <button
      class="nav-new"
      type="button"
      aria-label="Create new template"
      @click="$emit('new-template')"
    >
      <Plus :size="17" />
      <span>New Template</span>
    </button>
  </nav>
</template>
