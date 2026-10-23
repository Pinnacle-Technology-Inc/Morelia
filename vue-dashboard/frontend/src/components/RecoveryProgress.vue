<script setup>
defineProps({ status: { type: Object, required: true } });
</script>

<template>
  <section class="recovery-progress" :class="`recovery-progress--${status.tone}`" aria-label="Recovery progress">
    <div class="recovery-progress__step">
      <span class="recovery-progress__eyebrow">{{ status.heading }}</span>
      <strong>{{ status.title }}</strong>
      <p>{{ status.explanation }}</p>
      <small v-if="status.freshness">{{ status.freshness }}. All evidence below is from the last report.</small>
      <small v-if="status.startedAt">Recovery started at {{ status.startedAt }}</small>
    </div>
    <dl class="recovery-progress__facts">
      <div><dt>Attempt</dt><dd>{{ status.attempt }}</dd></div>
      <div><dt>Device presence</dt><dd>{{ status.presence }}</dd></div>
      <div><dt>PING</dt><dd>{{ status.ping }}</dd></div>
      <div><dt>Data proof</dt><dd>{{ status.data }}</dd></div>
      <div><dt>Recovery verified by</dt><dd>{{ status.verification }}</dd></div>
    </dl>
    <div v-if="status.lastError" class="recovery-progress__error">
      <strong>Latest reported error</strong>
      <p>{{ status.lastError }}</p>
    </div>
    <details v-if="status.history.length" class="recovery-progress__history" open>
      <summary>Recent reported steps ({{ status.history.length }})</summary>
      <ol>
        <li v-for="(step, index) in status.history" :key="index">
          <strong>{{ step.label }}</strong>
          <span>{{ step.at ?? "Time not reported" }}<template v-if="step.attempt != null"> · attempt {{ step.attempt }}</template></span>
        </li>
      </ol>
    </details>
    <p v-else class="recovery-progress__history-empty">Step history was not included in this report.</p>
  </section>
</template>

<style scoped>
.recovery-progress { --progress-tone: var(--warning); display: grid; gap: var(--space-4); min-width: 0; }
.recovery-progress--good { --progress-tone: var(--success); }
.recovery-progress--bad { --progress-tone: var(--error); }
.recovery-progress--muted { --progress-tone: var(--text-muted); }
.recovery-progress__step { display: grid; gap: var(--space-2); border-left: 3px solid var(--progress-tone); padding-left: var(--space-3); }
.recovery-progress__eyebrow, .recovery-progress__step small { color: var(--text-muted); font-size: var(--fs-sm); }
.recovery-progress__step > strong { font-size: var(--fs-lg); color: var(--text-heading); }
.recovery-progress p { margin: 0; overflow-wrap: anywhere; }
.recovery-progress__facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--space-3); margin: 0; }
.recovery-progress__facts dt { color: var(--text-muted); font-size: var(--fs-sm); }
.recovery-progress__facts dd { margin: var(--space-1) 0 0; overflow-wrap: anywhere; }
.recovery-progress__error { border-left: 3px solid var(--error); padding-left: var(--space-3); }
.recovery-progress__error strong { font-size: var(--fs-sm); }
.recovery-progress__history summary { cursor: pointer; font-size: var(--fs-sm); }
.recovery-progress__history ol { margin-bottom: 0; padding-left: var(--space-5); display: grid; gap: var(--space-2); }
.recovery-progress__history li > span { display: block; color: var(--text-muted); font-size: var(--fs-sm); }
.recovery-progress__history-empty { color: var(--text-muted); font-size: var(--fs-sm); }
</style>
