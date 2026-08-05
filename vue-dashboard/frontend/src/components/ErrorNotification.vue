<script setup>
import { onBeforeUnmount, watch } from "vue";
import { AlertTriangle, X } from "@lucide/vue";

const props = defineProps({
  message: { type: String, required: true },
  duration: { type: Number, default: 30_000 },
});

const emit = defineEmits(["dismiss"]);

let dismissTimer;

function clearDismissTimer() {
  if (dismissTimer !== undefined) clearTimeout(dismissTimer);
  dismissTimer = undefined;
}

function scheduleDismiss(message) {
  clearDismissTimer();
  if (!message || props.duration <= 0) return;
  dismissTimer = setTimeout(() => emit("dismiss"), props.duration);
}

watch(
  [() => props.message, () => props.duration],
  ([message]) => scheduleDismiss(message),
  { immediate: true },
);

onBeforeUnmount(clearDismissTimer);
</script>

<template>
  <Teleport to="body">
    <Transition name="error-notification">
      <aside
        v-if="message"
        class="error-notification"
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
      >
        <AlertTriangle class="error-notification__icon" :size="20" aria-hidden="true" />
        <div class="error-notification__content">
          <strong>Error</strong>
          <p>{{ message }}</p>
          <div v-if="$slots.default" class="error-notification__actions">
            <slot />
          </div>
        </div>
        <button
          type="button"
          class="error-notification__close"
          aria-label="Dismiss error notification"
          @click="emit('dismiss')"
        >
          <X :size="18" aria-hidden="true" />
        </button>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.error-notification {
  position: fixed;
  bottom: var(--space-5);
  left: var(--space-5);
  z-index: 200;
  display: grid;
  width: min(28rem, calc(100vw - var(--space-5) - var(--space-5)));
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: start;
  gap: var(--space-3);
  padding: var(--space-4);
  color: var(--text-body);
  border: 1px solid #dfaaa6;
  border-left: var(--border-accent) solid var(--error);
  border-radius: var(--radius-md);
  background: var(--surface-card);
  box-shadow: var(--shadow-md);
}
.error-notification__icon {
  color: var(--error);
}
.error-notification__content {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
}
.error-notification__content strong {
  color: var(--error);
  font-family: var(--font-display);
  font-size: var(--fs-sm);
}
.error-notification__content p {
  overflow-wrap: anywhere;
  font-size: var(--fs-sm);
  line-height: var(--lh-snug);
}
.error-notification__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.error-notification__actions:empty {
  display: none;
  margin-top: 0;
}
.error-notification__actions :slotted(button) {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) 0;
  color: var(--primary);
  border: 0;
  background: transparent;
  font-family: var(--font-display);
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  cursor: pointer;
}
.error-notification__actions :slotted(button:hover) {
  text-decoration: underline;
  text-underline-offset: var(--space-1);
}
.error-notification__close {
  display: grid;
  width: var(--space-6);
  height: var(--space-6);
  place-items: center;
  padding: 0;
  color: var(--text-muted);
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  cursor: pointer;
}
.error-notification__close:hover {
  color: var(--text-heading);
  background: var(--surface-sage);
}
.error-notification-enter-active,
.error-notification-leave-active {
  transition: opacity var(--dur-base) var(--ease-standard), transform var(--dur-base) var(--ease-standard);
}
.error-notification-enter-from,
.error-notification-leave-to {
  opacity: 0;
  transform: translateY(var(--space-3));
}

@media (max-width: 600px) {
  .error-notification {
    right: var(--space-4);
    bottom: var(--space-4);
    left: var(--space-4);
    width: auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .error-notification-enter-active,
  .error-notification-leave-active {
    transition: none;
  }
}
</style>
