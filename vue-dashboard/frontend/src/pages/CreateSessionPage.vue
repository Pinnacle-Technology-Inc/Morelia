<script setup>
import { computed, ref } from "vue";
import { AlertTriangle, Check, ChevronRight, Plus, Trash2 } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { devices, sessionTemplates } from "../data";

defineEmits(["cancel"]);

const step = ref(0);
const startFrom = ref("Blank session");
const recoveryPolicy = ref("Recommend");
const steps = ["Details", "Streams", "Sinks & Outputs", "Schedule", "Recovery", "Review"];
const progress = computed(() => `${Math.round(((step.value + 1) / steps.length) * 100)}%`);
const availableDevices = computed(() => devices.filter((device) => device.status === "free"));
const configuredDevices = computed(() => devices.filter((device) => device.status !== "unconfigured"));

function deviceLabel(value) {
  return { available: "Available", not_found: "Not found", free: "Free", claimed: "Claimed" }[value] ?? value;
}
</script>

<template>
  <div class="page page--workspace">
    <PageHeader
      eyebrow="Guided configuration"
      title="Create Session"
      description="Choose streams, outputs, scheduling, and guarded recovery behavior."
    />
    <BaseCard class="wizard">
      <ol class="wizard-steps">
        <li v-for="(label, index) in steps" :key="label" :class="{ active: index === step, complete: index < step }">
          <button type="button" @click="step = index">
            <span><Check v-if="index < step" :size="13" /><template v-else>{{ index + 1 }}</template></span>
            {{ label }}
          </button>
          <ChevronRight v-if="index < steps.length - 1" :size="15" />
        </li>
      </ol>
      <div class="wizard-progress"><i :style="{ width: progress }" /></div>

      <section class="wizard-content">
        <div v-if="step === 0" class="form-grid">
          <label class="field field--wide"><span>Session Name *</span><input placeholder="e.g. Cortical Array Session 08" /></label>
          <label class="field field--wide"><span>Description</span><input placeholder="Optional description" /></label>
          <label class="field"><span>Experiment</span><select><option>None</option><option>Motor Learning Study</option><option>Sleep Stage Analysis</option></select></label>
          <label class="field"><span>Start From</span><select v-model="startFrom"><option>Blank session</option><option>Session template</option></select></label>
          <label v-if="startFrom === 'Session template'" class="field field--wide"><span>Session Template</span><select><option value="">Choose a session template</option><option v-for="template in sessionTemplates" :key="template.name">{{ template.name }}</option></select></label>
          <label class="field field--wide"><span>Notes</span><textarea placeholder="Optional session notes" /></label>
        </div>

        <div v-else-if="step === 1" class="wizard-selection">
          <h3>Choose streams</h3>
          <p>Choose free configured devices for this session. Device setup is managed in Devices.</p>
          <p v-if="startFrom === 'Session template'">Devices required by this template are configured automatically when possible.</p>
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr><th>Device</th><th>Type</th><th>Hardware ID</th><th>Port</th><th>Availability</th><th>Status</th><th>Config Source</th><th /></tr></thead>
              <tbody>
                <tr v-for="device in configuredDevices" :key="device.hardwareId">
                  <td><strong>{{ device.name }}</strong></td>
                  <td>{{ device.type }}</td>
                  <td><code>{{ device.hardwareId }}</code></td>
                  <td><code>{{ device.port }}</code></td>
                  <td><StatusBadge compact :value="deviceLabel(device.availability)" /></td>
                  <td><StatusBadge compact :value="deviceLabel(device.status)" /></td>
                  <td>{{ device.configSource }}</td>
                  <td><button type="button" class="table-action">{{ device.status === "free" ? "Add Stream" : "View device" }}</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="form-notice"><AlertTriangle :size="18" /> Only free configured devices can be added to a session.</div>
          <p v-for="device in configuredDevices.filter(item => item.status === 'claimed')" :key="`${device.hardwareId}-claim`" class="validation-copy">This device is already claimed by {{ device.owningSession }}.</p>
        </div>

        <div v-else-if="step === 2" class="wizard-selection">
          <h3>Configure sinks and outputs</h3>
          <p>Each sink belongs to one stream and must pass write and duplicate-path validation.</p>
          <div class="output-preview">
            <strong>M32-007 / Raw LFP</strong>
            <code>/data/cortical/session_M32007_rawlfp_20260619.bin</code>
            <span>Writable - 4.2 GB free - Output validation pending</span>
          </div>
          <div class="wizard-actions">
            <BaseButton variant="secondary"><Plus :size="16" /> Add Sink</BaseButton>
            <BaseButton variant="secondary"><Trash2 :size="16" /> Remove Sink</BaseButton>
            <BaseButton>Validate Outputs</BaseButton>
          </div>
        </div>

        <div v-else-if="step === 3" class="form-grid">
          <label class="field"><span>Start Mode</span><select><option>Manual</option><option>One-time</option><option>Daily</option></select></label>
          <label class="field"><span>Timezone</span><select><option>America/Chicago</option></select></label>
          <label class="field"><span>Start Date</span><input type="date" /></label>
          <label class="field"><span>Start Time</span><input type="time" /></label>
        </div>

        <div v-else-if="step === 4" class="form-grid">
          <label class="field"><span>Recovery Policy</span><select v-model="recoveryPolicy"><option>Recommend</option><option>Automate</option></select></label>
          <div class="form-notice field--wide"><AlertTriangle :size="18" /> Changed policies default to Recommend. Automation requires an explicit choice.</div>
          <BaseCard class="field--wide detail-panel">
            <dl class="detail-list">
              <div><dt>Recommend</dt><dd>Report software-fixable faults and wait for operator approval.</dd></div>
              <div><dt>Automate</dt><dd>Run software-fixable recovery when preconditions allow it.</dd></div>
            </dl>
          </BaseCard>
        </div>

        <div v-else class="review-state">
          <div class="form-notice"><AlertTriangle :size="18" /> Complete stream and sink selection before starting.</div>
          <dl class="detail-list">
            <div><dt>Session details</dt><dd>Cortical Array Session 08</dd></div>
            <div><dt>Streams</dt><dd>{{ availableDevices.length }} available devices</dd></div>
            <div><dt>Sinks &amp; outputs</dt><dd>Selection required</dd></div>
            <div><dt>Schedule</dt><dd>Manual</dd></div>
            <div><dt>Recovery policy</dt><dd>{{ recoveryPolicy }}</dd></div>
          </dl>
        </div>
      </section>

      <footer class="wizard-footer">
        <BaseButton variant="secondary" @click="step === 0 ? $emit('cancel') : step--">{{ step === 0 ? "Cancel" : "Back" }}</BaseButton>
        <div>
          <BaseButton variant="secondary">Save as Draft</BaseButton>
          <BaseButton v-if="step < steps.length - 1" @click="step++">Next: {{ steps[step + 1] }}</BaseButton>
          <BaseButton v-else>Start Now</BaseButton>
        </div>
      </footer>
    </BaseCard>
  </div>
</template>
