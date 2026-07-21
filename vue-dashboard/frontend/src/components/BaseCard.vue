<script setup>
defineProps({
  interactive: Boolean,
  tone: { type: String, default: "default" },
});

const emit = defineEmits(["activate"]);

function activate(event) {
  if (!event || event.type === "click" || event.key === "Enter" || event.key === " ") {
    event?.preventDefault();
    emit("activate");
  }
}
</script>

<template>
  <div
    class="card"
    :class="[`card--${tone}`, { 'card--interactive': interactive }]"
    :role="interactive ? 'button' : undefined"
    :tabindex="interactive ? 0 : undefined"
    @click="interactive && activate($event)"
    @keydown="interactive && activate($event)"
  >
    <slot />
  </div>
</template>

