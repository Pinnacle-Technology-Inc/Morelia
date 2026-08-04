<script setup>
import { computed } from "vue";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  CircleDashed,
  CircleHelp,
  CopySlash,
  PencilOff,
  FileQuestionMark,
  ListRestart,
  Clock3,
  EyeOff,
  FileText,
  LoaderCircle,
  Play,
  RefreshCw,
  Square,
  StopCircle,
  Wifi,
  WifiOff,
  XCircle,
} from "@lucide/vue";

const props = defineProps({
  value: { type: String, required: true },
  compact: Boolean,
  // Names the AXIS this badge reports on, for the places where the bare value is
  // ambiguous against a neighbouring badge. A watchdog badge reading "Running"
  // next to a lifecycle badge reading "Active" looks like a second, disagreeing
  // lifecycle; "Monitor Running" does not.
  label: { type: String, default: null },
});

const config = {
  Draft: { icon: FileText, tone: "neutral" },
  Stored: { icon: CheckCircle2, tone: "green" },
  Scheduled: { icon: Clock3, tone: "blue" },
  Starting: { icon: LoaderCircle, tone: "amber" },
  Active: { icon: Play, tone: "green" },
  Ending: { icon: StopCircle, tone: "orange" },
  Completed: { icon: CheckCircle2, tone: "green" },
  Healthy: { icon: CheckCircle2, tone: "green" },
  Suspect: { icon: AlertTriangle, tone: "amber" },
  Unhealthy: { icon: XCircle, tone: "red" },
  // Per-sink health (SinkHealth in runtime_child/driver.py). `Degraded` had no
  // entry, so a degrading sink rendered with the neutral Unknown styling.
  Degraded: { icon: AlertTriangle, tone: "amber" },
  // A sink the runtime has not complained about. Distinct from `Healthy`: the
  // runtime only reports sinks that ERROR, so we know there is no failure, not
  // that the write path has been positively verified. See summarizeSinks().
  "No errors": { icon: CheckCircle2, tone: "green" },
  Recovering: { icon: RefreshCw, tone: "amber" },
  "Needs action": { icon: AlertTriangle, tone: "orange" },
  Unknown: { icon: CircleHelp, tone: "neutral" },
  // Session-health resting/visibility states (see session-utils.SessionHealth).
  // `Not running` is neutral on purpose — a Draft session is not broken, it just
  // has nothing to measure. `Not reporting` is amber because a session we are
  // supposed to be watching has gone dark, which is not the same as fine.
  "Not running": { icon: CircleDashed, tone: "neutral" },
  "Not reporting": { icon: EyeOff, tone: "amber" },
  "Not streaming": { icon: Square, tone: "orange" },
  Current: { icon: Wifi, tone: "green" },
  Delayed: { icon: Wifi, tone: "amber" },
  Unreachable: { icon: WifiOff, tone: "red" },
  Stopped: { icon: Square, tone: "amber" },
  Available: { icon: CheckCircle2, tone: "green" },
  "Not found": { icon: CircleHelp, tone: "neutral" },
  Free: { icon: CheckCircle2, tone: "green" },
  Claimed: { icon: LoaderCircle, tone: "amber" },
  Unconfigured: { icon: CircleHelp, tone: "neutral" },
  Exact: { icon: CheckCircle2, tone: "green" },
  Generic: { icon: CheckCircle2, tone: "blue" },
  Ready: { icon: CheckCircle2, tone: "green" },
  "Needs sink": { icon: AlertTriangle, tone: "amber" },
  Queued: { icon: Clock3, tone: "blue" },
  Dispatched: { icon: RefreshCw, tone: "blue" },
  Running: { icon: Play, tone: "green" },
  Verifying: { icon: RefreshCw, tone: "amber" },
  Succeeded: { icon: CheckCircle2, tone: "green" },
  Recovered: { icon: CheckCircle2, tone: "green" },
  Failed: { icon: XCircle, tone: "red" },
  Uncertain: { icon: AlertTriangle, tone: "orange" },
  Attention: { icon: AlertTriangle, tone: "orange" },
  ACTIVE: { icon: CheckCircle2, tone: "green" },
  DISCOVERED: { icon: FileText, tone: "blue" },
  PENDING: { icon: CircleDashed, tone: "amber" },
  DUPLICATE: { icon: CopySlash, tone: "blue" },
  AMBIGUOUS_RENAME: { icon: FileQuestionMark, tone: "neutral" },
  CHANGED: { icon: ListRestart, tone: "neutral" },
  REPLACED: { icon: PencilOff, tone: "neutral" },
  ARCHIVED: { icon: Archive, tone: "neutral" },
  INVALID: { icon: AlertTriangle, tone: "amber" },
};

const current = computed(() => config[props.value] ?? config.Unknown);
</script>

<template>
  <span class="status-badge" :class="[`status-badge--${current.tone}`, { 'status-badge--compact': compact }]">
    <component :is="current.icon" :size="14" aria-hidden="true" />
    <span v-if="label" class="status-badge__label">{{ label }}</span>
    {{ value }}
  </span>
</template>

<style scoped>
.status-badge__label {
  opacity: 0.7;
  font-weight: 400;
}
</style>
