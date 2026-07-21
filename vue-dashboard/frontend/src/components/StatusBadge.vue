<script setup>
import { computed } from "vue";
import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  Clock3,
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
});

const config = {
  Draft: { icon: FileText, tone: "neutral" },
  Scheduled: { icon: Clock3, tone: "blue" },
  Starting: { icon: LoaderCircle, tone: "amber" },
  Active: { icon: Play, tone: "green" },
  Ending: { icon: StopCircle, tone: "orange" },
  Completed: { icon: CheckCircle2, tone: "neutral" },
  Healthy: { icon: CheckCircle2, tone: "green" },
  Suspect: { icon: AlertTriangle, tone: "amber" },
  Unhealthy: { icon: XCircle, tone: "red" },
  Recovering: { icon: RefreshCw, tone: "amber" },
  "Needs action": { icon: AlertTriangle, tone: "orange" },
  Unknown: { icon: CircleHelp, tone: "neutral" },
  Current: { icon: Wifi, tone: "green" },
  Delayed: { icon: Wifi, tone: "amber" },
  Unreachable: { icon: WifiOff, tone: "red" },
  Stopped: { icon: Square, tone: "neutral" },
  Available: { icon: CheckCircle2, tone: "green" },
  "Not found": { icon: CircleHelp, tone: "neutral" },
  Free: { icon: CheckCircle2, tone: "green" },
  Claimed: { icon: LoaderCircle, tone: "amber" },
  Unconfigured: { icon: CircleHelp, tone: "neutral" },
  Queued: { icon: Clock3, tone: "blue" },
  Dispatched: { icon: RefreshCw, tone: "blue" },
  Running: { icon: Play, tone: "green" },
  Verifying: { icon: RefreshCw, tone: "amber" },
  Succeeded: { icon: CheckCircle2, tone: "green" },
  Recovered: { icon: CheckCircle2, tone: "green" },
  Failed: { icon: XCircle, tone: "red" },
  Uncertain: { icon: AlertTriangle, tone: "orange" },
  Attention: { icon: AlertTriangle, tone: "orange" },
};

const current = computed(() => config[props.value] ?? config.Unknown);
</script>

<template>
  <span class="status-badge" :class="[`status-badge--${current.tone}`, { 'status-badge--compact': compact }]">
    <component :is="current.icon" :size="14" aria-hidden="true" />
    {{ value }}
  </span>
</template>
