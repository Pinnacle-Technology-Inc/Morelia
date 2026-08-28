<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import run1 from "../assets/running-animation/1.png";
import run2 from "../assets/running-animation/2.png";
import run3 from "../assets/running-animation/3.png";
import run4 from "../assets/running-animation/4.png";
import run5 from "../assets/running-animation/5.png";
import sleepingRat from "../assets/sleeping-rat.png";
import suspect1 from "../assets/suspect-animation/1.png";
import suspect2 from "../assets/suspect-animation/2.png";
import suspect4 from "../assets/suspect-animation/4.png";
import suspect5 from "../assets/suspect-animation/5.png";
import suspect6 from "../assets/suspect-animation/6.png";

const RUNNING_FRAMES = [run1, run2, run3, run4, run5];
const SUSPECT_FRAMES = [suspect1, suspect2, suspect4, suspect5, suspect6];
const IDLE_FRAMES = [sleepingRat];

// The three sprite sheets do NOT share a canvas, and the rat does not fill the
// same share of each. Measured from the alpha bounds of every frame actually
// used (suspect frame 3 is excluded above and is not counted):
//
//   set      canvas     aspect   ink height as % of canvas height
//   running  1254x528   2.375    85.0%
//   suspect  1254x750   1.672    90.7%
//   idle     1024x538   1.903    76.0%
//
// Drawing all three into one box makes the ANIMAL change size when the session
// changes state — a square box plus `object-fit: contain` shrinks whichever
// sheet is least like the box, and the sleeping rat loses a quarter of its
// height to transparent padding before it even starts.
//
// So each set declares two things: the `aspect` the browser should reserve, and
// a `scale` chosen so the INK lands at one height in every state. The scales are
// (1 / inkFraction) normalised against idle, the least dense sheet:
//   idle 1 · running 0.850/0.760 → 0.895 · suspect 0.907/0.760 → 0.838
// A box of height H therefore always contains a rat 0.76·H tall, whatever it is
// doing. Re-measure and update these if the art is ever re-exported.
const FRAME_SETS = {
  suspect: { frames: SUSPECT_FRAMES, aspect: "1254 / 750", scale: 0.838 },
  paused: { frames: IDLE_FRAMES, aspect: "1024 / 538", scale: 1 },
  default: { frames: RUNNING_FRAMES, aspect: "1254 / 528", scale: 0.895 },
};

/** Frame dwell in ms. Suspect / recovering are slower so the gait still reads. */
const INTERVAL_MS = {
  running: 90,
  recovering: 160,
  stopping: 160,
  suspect: 140,
};

const props = defineProps({
  /** Session-level motion: running | recovering | stopping | suspect | paused | stopped */
  state: {
    type: String,
    default: "paused",
    validator: (value) =>
      ["running", "recovering", "stopping", "suspect", "paused", "stopped"].includes(value),
  },
  // Sizes name a HEIGHT, not a box. Width follows from the state's aspect,
  // because a galloping rat is genuinely wider than a sitting one and forcing
  // both into one width is what made them look mis-scaled. (`fill` is gone: it
  // had no caller once the flow bar stopped rendering a rat, and "stretch to the
  // parent" cannot honour the per-state scaling above.)
  size: {
    type: String,
    default: "md",
    validator: (value) => ["sm", "md", "lg"].includes(value),
  },
  /** Accessible name; defaults from state when omitted. */
  label: { type: String, default: "" },
});

const frameIndex = ref(0);
const reducedMotion = ref(false);
let timer = null;
let motionQuery = null;

function onMotionPreferenceChange(event) {
  reducedMotion.value = event.matches;
  syncAnimation();
}

// One lookup for the sheet AND its geometry, so the frames a state plays can
// never drift from the aspect/scale used to draw them.
const frameSet = computed(() => FRAME_SETS[props.state] ?? FRAME_SETS.default);
const frames = computed(() => frameSet.value.frames);

// Reserved before the image loads, so a state change never reflows the card.
const frameStyle = computed(() => ({
  aspectRatio: frameSet.value.aspect,
  height: `calc(100% * ${frameSet.value.scale})`,
}));

const isAnimating = computed(
  () =>
    !reducedMotion.value &&
    ["running", "recovering", "stopping", "suspect"].includes(props.state),
);

const src = computed(() => frames.value[frameIndex.value] ?? frames.value[0]);

const ariaLabel = computed(() => {
  if (props.label) return props.label;
  if (props.state === "running") return "Session streaming";
  if (props.state === "recovering") return "Session recovering";
  if (props.state === "stopping") return "Session stopping";
  if (props.state === "suspect") return "Session has a suspect stream";
  if (props.state === "stopped") return "Session stalled";
  return "Session idle";
});

function clearTimer() {
  if (timer != null) {
    clearInterval(timer);
    timer = null;
  }
}

function syncAnimation() {
  clearTimer();
  frameIndex.value = 0;
  if (!isAnimating.value) return;
  const interval = INTERVAL_MS[props.state] ?? INTERVAL_MS.running;
  const count = frames.value.length;
  timer = setInterval(() => {
    frameIndex.value = (frameIndex.value + 1) % count;
  }, interval);
}

onMounted(() => {
  if (typeof window.matchMedia === "function") {
    motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    reducedMotion.value = motionQuery.matches;
    if (typeof motionQuery.addEventListener === "function") {
      motionQuery.addEventListener("change", onMotionPreferenceChange);
    } else if (typeof motionQuery.addListener === "function") {
      motionQuery.addListener(onMotionPreferenceChange);
    }
  }
  syncAnimation();
});

onUnmounted(() => {
  clearTimer();
  if (!motionQuery) return;
  if (typeof motionQuery.removeEventListener === "function") {
    motionQuery.removeEventListener("change", onMotionPreferenceChange);
  } else if (typeof motionQuery.removeListener === "function") {
    motionQuery.removeListener(onMotionPreferenceChange);
  }
});

watch(() => props.state, syncAnimation);
</script>

<template>
  <span
    class="rat-run"
    :class="[`rat-run--${size}`, `rat-run--${state}`, { 'is-animating': isAnimating }]"
    role="img"
    :aria-label="ariaLabel"
  >
    <!-- No width/height attributes: they said 1254x1254, which no sheet is.
         The aspect comes from `frameStyle` instead, which knows the real one. -->
    <img class="rat-run__frame" :src="src" alt="" :style="frameStyle" draggable="false" />
  </span>
</template>

<style scoped>
/* The box is a fixed HEIGHT and a natural width. `overflow: hidden` is gone —
   nothing overflows now, and keeping it would crop the wider states. */
.rat-run {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  line-height: 0;
}

/* Height of the box; the rat inside is 0.76 of it in every state. */
.rat-run--sm {
  height: 26px;
}

.rat-run--md {
  height: 38px;
}

.rat-run--lg {
  height: 90px;
}

.rat-run__frame {
  display: block;
  /* Width is derived from the height and the state's aspect ratio (frameStyle).
     max-width keeps a narrow parent from overflowing rather than clipping. */
  width: auto;
  max-width: 100%;
  object-fit: contain;
  user-select: none;
  pointer-events: none;
}

.rat-run--stopped {
  opacity: 0.72;
  filter: grayscale(0.35);
}
</style>
