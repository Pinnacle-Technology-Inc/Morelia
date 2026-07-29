<script setup>
import { ref, useId, watch } from "vue";
import { ChevronDown, ChevronRight } from "@lucide/vue";

// A titled, collapsible body for one table. Written for the record tabs on the
// session detail page, where several wide tables have to share one tab without
// turning it into a scroll wall.
//
// Built as a disclosure button + `v-show` rather than <details>/<summary>,
// matching ActiveSessionCard: <summary> is a flex container whose marker and
// baseline behaviour differ across browsers, and the header here has to carry a
// count pill and a hint line beside the title.
const props = defineProps({
  title: { type: String, required: true },
  // Row count for the header pill. `null` renders no pill, for a section whose
  // size is not what you scan for.
  count: { type: Number, default: null },
  // Severity of the count pill: "neutral" | "warn" | "bad". Neutral is the right
  // default for a permanent record — a gap log with 40 entries is history, not
  // 40 problems.
  tone: { type: String, default: "neutral" },
  // One line saying what the section holds, readable WHILE COLLAPSED so an
  // operator can decide not to open it.
  hint: { type: String, default: "" },
  defaultOpen: { type: Boolean, default: false },
});

// Open state is owned here so the page does not carry a ref per section. The
// watch means a section that BECOMES worth opening (its caller flips
// `default-open` when the first actionable row lands) opens itself, instead of
// hiding new work behind a header the operator already collapsed.
const open = ref(props.defaultOpen);
watch(
  () => props.defaultOpen,
  (value) => {
    open.value = value;
  },
);

const bodyId = useId();
</script>

<template>
  <section class="collapsible">
    <button
      class="collapsible__head"
      type="button"
      :aria-expanded="open"
      :aria-controls="bodyId"
      @click="open = !open"
    >
      <ChevronDown v-if="open" class="collapsible__chevron" :size="16" />
      <ChevronRight v-else class="collapsible__chevron" :size="16" />
      <h3>{{ title }}</h3>
      <span v-if="count !== null" :class="`collapsible__count collapsible__count--${tone}`">
        {{ count }}
      </span>
      <small v-if="hint" class="collapsible__hint">{{ hint }}</small>
    </button>
    <div v-show="open" :id="bodyId" class="collapsible__body">
      <slot />
    </div>
  </section>
</template>
