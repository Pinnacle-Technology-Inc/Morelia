<script setup>
import {
  AlertTriangle,
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  Clock3,
} from "@lucide/vue";
import BaseCard from "./BaseCard.vue";
import SectionTitle from "./SectionTitle.vue";
import StatusBadge from "./StatusBadge.vue";

const props = defineProps({
  attention: { type: Object, required: true },
  scheduled: { type: Array, required: true },
  collapsed: Boolean,
  collapsedSections: { type: Array, default: () => [] },
});

const emit = defineEmits([
  "open-session",
  "update:collapsed",
  "update:collapsed-sections",
  "view-attention",
]);

function isSectionCollapsed(section) {
  return props.collapsedSections.includes(section);
}

function toggleSection(section) {
  emit(
    "update:collapsed-sections",
    isSectionCollapsed(section)
      ? props.collapsedSections.filter((item) => item !== section)
      : [...props.collapsedSections, section],
  );
}

function openSection(section) {
  emit("update:collapsed", false);
  emit(
    "update:collapsed-sections",
    props.collapsedSections.filter((item) => item !== section),
  );
}
</script>

<template>
  <aside
    id="overview-supporting-panels"
    class="overview-side"
    :class="{ 'overview-side--collapsed': collapsed }"
    aria-label="Overview supporting panels"
  >
    <div v-if="collapsed" class="overview-side-rail">
      <button
        type="button"
        :aria-label="`Open Attention Required, ${attention.total} items`"
        title="Open Attention Required"
        @click="openSection('attention')"
      >
        <AlertTriangle :size="18" />
        <span>{{ attention.total }}</span>
      </button>
      <button
        type="button"
        :aria-label="`Open Upcoming Scheduled, ${scheduled.length} items`"
        title="Open Upcoming Scheduled"
        @click="openSection('scheduled')"
      >
        <Clock3 :size="18" />
        <span>{{ scheduled.length }}</span>
      </button>
    </div>

    <template v-else>
      <section>
        <SectionTitle :title="`Attention Required (${attention.total})`">
          <div class="section-title-actions">
            <button
              v-if="attention.hidden"
              class="section-link"
              type="button"
              @click="$emit('view-attention')"
            >
              View all {{ attention.total }}
              <ArrowUpRight :size="14" />
            </button>
            <button
              class="section-collapse-button"
              type="button"
              :aria-expanded="!isSectionCollapsed('attention')"
              aria-controls="overview-attention-panel"
              :aria-label="`${isSectionCollapsed('attention') ? 'Expand' : 'Collapse'} Attention Required`"
              @click="toggleSection('attention')"
            >
              <ChevronRight v-if="isSectionCollapsed('attention')" :size="17" />
              <ChevronDown v-else :size="17" />
            </button>
          </div>
        </SectionTitle>
        <div
          v-show="!isSectionCollapsed('attention')"
          id="overview-attention-panel"
          class="overview-side__content"
        >
          <BaseCard
            v-for="session in attention.visible"
            :key="session.id"
            interactive
            tone="warning"
            @activate="$emit('open-session', session.id)"
          >
            <div class="attention-card attention-card--compact">
              <span class="attention-icon"><AlertTriangle :size="21" /></span>
              <div class="attention-content">
                <div class="title-row">
                  <h3>{{ session.name }}</h3>
                  <StatusBadge :value="session.lifecycle" />
                  <StatusBadge :value="session.health" />
                </div>
                <p>{{ session.attentionReason }}</p>
              </div>
              <div class="attention-action">
                <code>Since {{ session.attentionSince }}</code>
                <strong>Review recovery <ArrowUpRight :size="15" /></strong>
              </div>
            </div>
          </BaseCard>
        </div>
      </section>

      <section>
        <SectionTitle :title="`Upcoming Scheduled (${scheduled.length})`">
          <button
            class="section-collapse-button"
            type="button"
            :aria-expanded="!isSectionCollapsed('scheduled')"
            aria-controls="overview-scheduled-panel"
            :aria-label="`${isSectionCollapsed('scheduled') ? 'Expand' : 'Collapse'} Upcoming Scheduled`"
            @click="toggleSection('scheduled')"
          >
            <ChevronRight v-if="isSectionCollapsed('scheduled')" :size="17" />
            <ChevronDown v-else :size="17" />
          </button>
        </SectionTitle>
        <div
          v-show="!isSectionCollapsed('scheduled')"
          id="overview-scheduled-panel"
          class="overview-side__content"
        >
          <BaseCard
            v-for="session in scheduled"
            :key="session.id"
            interactive
            @activate="$emit('open-session', session.id)"
          >
            <div class="scheduled-card">
              <Clock3 :size="21" />
              <h3>{{ session.name }}</h3>
              <p>{{ session.experiment }}</p>
              <div>
                <span><small>Scheduled</small><code>Jun 20, 08:00</code></span>
                <StatusBadge :value="session.health" />
              </div>
            </div>
          </BaseCard>
        </div>
      </section>
    </template>
  </aside>
</template>
