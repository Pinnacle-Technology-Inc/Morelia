<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import AppHeader from "./components/AppHeader.vue";
import PrimaryNav from "./components/PrimaryNav.vue";
import CatalogPage from "./pages/CatalogPage.vue";
import CreateTemplatePage from "./pages/CreateTemplatePage.vue";
import DevicesPage from "./pages/DevicesPage.vue";
import ExperimentsPage from "./pages/ExperimentsPage.vue";
import IncidentsPage from "./pages/IncidentsPage.vue";
import OperationsPage from "./pages/OperationsPage.vue";
import OverviewPage from "./pages/OverviewPage.vue";
import SessionDetailPage from "./pages/SessionDetailPage.vue";
import SessionsPage from "./pages/SessionsPage.vue";
import StartRunDialog from "./components/StartRunDialog.vue";
import SystemHealthPage from "./pages/SystemHealthPage.vue";
import TemplatesPage from "./pages/TemplatesPage.vue";
import { parseHash, toHash } from "./navigation-utils";
import { useSessionCatalog } from "./composables/useSessionCatalog";

const initialRoute = parseHash(window.location.hash);
const activeTab = ref(initialRoute.tab);
const selectedSessionId = ref(initialRoute.sessionId);
const selectedTemplateId = ref(initialRoute.templateId);
const templateView = ref(initialRoute.templateView);
// The catalog polls itself in the background, so Overview and Sessions pick up
// lifecycle changes made anywhere — this tab's wizard, the CLI, the runtime
// promoting a Starting session to Active — without a reload. The explicit
// refresh calls below remain: they collapse the wait after a *local* mutation
// from "up to one poll interval" to "immediately".
const {
  sessions: sessionCatalog,
  state: sessionCatalogState,
  error: sessionCatalogError,
  refresh: refreshSessionCatalog,
} = useSessionCatalog();
const selectedSession = computed(() =>
  sessionCatalog.value.find((session) => session.id === selectedSessionId.value),
);

function changeTab(tab) {
  activeTab.value = tab;
  selectedSessionId.value = null;
  selectedTemplateId.value = null;
  templateView.value = null;
  syncHash();
}

// A session the run dialog just created in "Start now" mode, handed to its
// detail page to issue the start command. One-shot and never in the URL: a
// reload, a back button, or any ordinary navigation to the same session must
// not re-command a run, so every other path through openSession() clears it.
const autoStartSessionId = ref(null);

function openSession(id) {
  autoStartSessionId.value = null;
  selectedSessionId.value = id;
  selectedTemplateId.value = null;
  templateView.value = null;
  syncHash();
}

// The dialog creates the Draft and hands the start over rather than running it
// itself, so the operator lands on the session as it comes up — the detail page
// already owns the lifecycle badge, the live event stream and the poll that
// carries Draft → Starting → Active.
function openCreatedSession(id, { autoStart = false } = {}) {
  refreshSessionCatalog({ silent: true });
  openSession(id);
  if (autoStart) autoStartSessionId.value = id;
}

function openTemplate(id, view = "detail") {
  activeTab.value = "templates";
  selectedSessionId.value = null;
  selectedTemplateId.value = id;
  templateView.value = view;
  syncHash();
}

// Refresh eagerly on any return path from a page that may have mutated a
// session, so the operator never lands on a list that predates their own
// change — the background poll would get there too, just a beat later.
function returnToSessions() {
  refreshSessionCatalog({ silent: true });
  changeTab("sessions");
}

// The single entry point for "make something new". A run is no longer created
// from nothing, so every former new-session affordance — the global button, the
// Sessions page, Overview's empty state — lands here.
function newTemplate() {
  activeTab.value = "templates";
  selectedSessionId.value = null;
  selectedTemplateId.value = null;
  templateView.value = "new";
  syncHash();
}

function syncHash() {
  const nextHash = toHash({
    tab: activeTab.value,
    sessionId: selectedSessionId.value,
    templateId: selectedTemplateId.value,
    templateView: templateView.value,
  });
  if (window.location.hash !== nextHash) window.history.pushState(null, "", nextHash);
}

function applyHash() {
  const route = parseHash(window.location.hash);
  activeTab.value = route.tab;
  selectedSessionId.value = route.sessionId;
  selectedTemplateId.value = route.templateId;
  templateView.value = route.templateView;
}

onMounted(() => {
  if (!window.location.hash) syncHash();
  window.addEventListener("hashchange", applyHash);
  window.addEventListener("popstate", applyHash);
});

onBeforeUnmount(() => {
  window.removeEventListener("hashchange", applyHash);
  window.removeEventListener("popstate", applyHash);
});
</script>

<template>
  <div class="app-shell">
    <AppHeader />
    <PrimaryNav :active="activeTab" @change="changeTab" @new-template="newTemplate" />
    <main class="app-main">
      <OverviewPage
        v-if="activeTab === 'overview' && !selectedSessionId && !templateView"
        :sessions="sessionCatalog"
        :catalog-state="sessionCatalogState"
        :load-error="sessionCatalogError"
        @open-session="openSession"
        @view-attention="changeTab('sessions')"
        @create-session="newTemplate"
      />
      <!-- On success or a 409 duplicate, the wizard hands back a template id
           and this opens that template's detail page directly. -->
      <CreateTemplatePage
        v-else-if="templateView === 'new'"
        @cancel="changeTab('templates')"
        @created="openTemplate($event, 'detail')"
        @open-existing-template="openTemplate($event, 'detail')"
      />

      <!-- `run` is not a page of its own: starting a session is a modal over
           the template detail it starts from, so the template stays on screen
           behind it and Cancel is a close rather than a navigation. The route
           survives, so a #run deep link and back/forward still work. -->
      <TemplatesPage
        v-else-if="templateView"
        :template-id="selectedTemplateId"
        :view="templateView === 'run' ? 'detail' : templateView"
        @open-template="openTemplate($event, 'detail')"
        @review-template="openTemplate($event, 'review')"
        @run-template="openTemplate($event, 'run')"
        @new-template="newTemplate"
        @back="changeTab('templates')"
      />
      <!-- Routed on the id, NOT on a catalog hit: a session created seconds ago
           by the wizard is not in `sessionCatalog` yet, and gating the route on
           list membership silently fell through to the (stale) list instead.
           `session` is passed only as a head-start when the row happens to be
           loaded; SessionDetailPage resolves itself from `sessionId`. -->
      <SessionDetailPage
        v-else-if="selectedSessionId"
        :key="selectedSessionId"
        :session="selectedSession ?? null"
        :session-id="selectedSessionId"
        :auto-start="autoStartSessionId === selectedSessionId"
        @back="returnToSessions"
        @start-another-run="openTemplate($event, 'run')"
        @state-changed="refreshSessionCatalog({ silent: true })"
      />
      <SessionsPage
        v-else-if="activeTab === 'sessions'"
        :sessions="sessionCatalog"
        :catalog-state="sessionCatalogState"
        :load-error="sessionCatalogError"
        @open-session="openSession"
        @new-session="newTemplate"
        @retry="refreshSessionCatalog"
      />
      <ExperimentsPage v-else-if="activeTab === 'experiments'" />
      <DevicesPage v-else-if="activeTab === 'devices'" />
      <TemplatesPage
        v-else-if="activeTab === 'templates'"
        @open-template="openTemplate($event, 'detail')"
        @review-template="openTemplate($event, 'review')"
        @run-template="openTemplate($event, 'run')"
        @new-template="newTemplate"
      />
      <IncidentsPage v-else-if="activeTab === 'incidents'" />
      <OperationsPage v-else-if="activeTab === 'operations'" />
      <SystemHealthPage v-else-if="activeTab === 'system-health'" />
    </main>

    <StartRunDialog
      v-if="templateView === 'run' && selectedTemplateId"
      :key="selectedTemplateId"
      :template-id="selectedTemplateId"
      @cancel="openTemplate(selectedTemplateId, 'detail')"
      @created="openCreatedSession"
      @template-stale="openTemplate($event, 'detail')"
    />
  </div>
</template>
