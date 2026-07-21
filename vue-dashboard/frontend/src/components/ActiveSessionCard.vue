<script setup>
import { ArrowUpRight, ChevronDown, ChevronRight, GripVertical } from "@lucide/vue";
import BaseCard from "./BaseCard.vue";
import StatusBadge from "./StatusBadge.vue";

defineProps({
  session: { type: Object, required: true },
  devices: { type: Array, default: () => [] },
  expanded: Boolean,
});

const emit = defineEmits(["drag-start", "drag-end", "move", "open", "toggle"]);

function moveWithKeyboard(sessionId, event) {
  if (["ArrowLeft", "ArrowUp"].includes(event.key)) {
    event.preventDefault();
    emit("move", sessionId, -1);
  }
  if (["ArrowRight", "ArrowDown"].includes(event.key)) {
    event.preventDefault();
    emit("move", sessionId, 1);
  }
}
</script>

<template>
  <BaseCard class="active-session-card">
    <article class="session-card">
      <header class="session-card__head">
        <div>
          <h3>{{ session.name }}</h3>
          <p>{{ session.experiment }}</p>
        </div>
        <div class="session-card__controls">
          <button
            class="session-drag-handle"
            type="button"
            draggable="true"
            :aria-label="`Reorder ${session.name}. Use arrow keys or drag.`"
            @dragstart="$emit('drag-start', session.id, $event)"
            @dragend="$emit('drag-end')"
            @keydown="moveWithKeyboard(session.id, $event)"
          >
            <GripVertical :size="18" />
          </button>
          <button
            class="session-disclosure"
            type="button"
            :aria-expanded="expanded"
            :aria-controls="`session-streams-${session.id}`"
            :aria-label="`${expanded ? 'Collapse' : 'Expand'} streams for ${session.name}`"
            @click="$emit('toggle', session.id)"
          >
            <ChevronDown v-if="expanded" :size="20" />
            <ChevronRight v-else :size="20" />
          </button>
        </div>
      </header>

      <div class="badge-row">
        <StatusBadge :value="session.lifecycle" />
        <StatusBadge :value="session.health" />
      </div>

      <dl class="session-stats">
        <div><dt>Duration</dt><dd>{{ session.duration }}</dd></div>
        <div><dt>Streams / Sinks</dt><dd>{{ session.streamCount ?? session.deviceCount }} / {{ session.sinkCount }}</dd></div>
        <div><dt>Session Monitor</dt><dd><StatusBadge compact :value="session.watchdog" /></dd></div>
      </dl>

      <section
        v-show="expanded"
        :id="`session-streams-${session.id}`"
        class="session-devices"
        :aria-label="`Streams in ${session.name}`"
      >
        <div class="session-devices__heading">
          <strong>Streams</strong>
          <span>{{ devices.length }} stream{{ devices.length === 1 ? "" : "s" }}</span>
        </div>
        <ul v-if="devices.length">
          <li v-for="device in devices" :key="device.id">
            <div class="device-row__identity">
              <strong>{{ device.device }}</strong>
              <span>{{ device.type }}</span>
              <code>{{ device.hardwareId }}</code>
            </div>
            <div class="device-row__status">
              <StatusBadge compact :value="device.health" />
              <span>{{ device.rate }}</span>
              <span>{{ device.lastData }}</span>
              <span>{{ device.sinks.length }} sink{{ device.sinks.length === 1 ? "" : "s" }}</span>
            </div>
          </li>
        </ul>
        <p v-else class="session-devices__empty">No stream details are available.</p>
      </section>

      <footer class="session-card__footer">
        <button class="session-open-action" type="button" @click="$emit('open', session.id)">
          Open session <ArrowUpRight :size="15" />
        </button>
      </footer>
    </article>
  </BaseCard>
</template>
