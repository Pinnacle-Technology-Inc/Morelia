<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import AppHeader from "./components/AppHeader.vue";
import PrimaryNav from "./components/PrimaryNav.vue";
import CatalogPage from "./pages/CatalogPage.vue";
import CreateSessionPage from "./pages/CreateSessionPage.vue";
import DevicesPage from "./pages/DevicesPage.vue";
import ExperimentsPage from "./pages/ExperimentsPage.vue";
import IncidentsPage from "./pages/IncidentsPage.vue";
import OperationsPage from "./pages/OperationsPage.vue";
import OverviewPage from "./pages/OverviewPage.vue";
import SessionDetailPage from "./pages/SessionDetailPage.vue";
import SessionsPage from "./pages/SessionsPage.vue";
import SystemHealthPage from "./pages/SystemHealthPage.vue";
import TemplatesPage from "./pages/TemplatesPage.vue";
import { parseHash, toHash } from "./navigation-utils";
import { useSessionCatalog } from "./composables/useSessionCatalog";

const initialRoute = parseHash(window.location.hash);
const activeTab = ref(initialRoute.tab);
const selectedSessionId = ref(initialRoute.sessionId);
const creating = ref(initialRoute.creating);
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
  creating.value = false;
  syncHash();
}

function openSession(id) {
  selectedSessionId.value = id;
  creating.value = false;
  syncHash();
}

// Refresh eagerly on any return path from a page that may have mutated a
// session, so the operator never lands on a list that predates their own
// change — the background poll would get there too, just a beat later.
function returnToSessions() {
  refreshSessionCatalog({ silent: true });
  changeTab("sessions");
}

function newSession() {
  activeTab.value = "sessions";
  selectedSessionId.value = null;
  creating.value = true;
  syncHash();
}

function syncHash() {
  const nextHash = toHash({
    tab: activeTab.value,
    sessionId: selectedSessionId.value,
    creating: creating.value,
  });
  if (window.location.hash !== nextHash) window.history.pushState(null, "", nextHash);
}

function applyHash() {
  const route = parseHash(window.location.hash);
  activeTab.value = route.tab;
  selectedSessionId.value = route.sessionId;
  creating.value = route.creating;
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
    <PrimaryNav :active="activeTab" @change="changeTab" @new-session="newSession" />
    <main class="app-main">
      <OverviewPage
        v-if="activeTab === 'overview' && !selectedSessionId && !creating"
        :sessions="sessionCatalog"
        :catalog-state="sessionCatalogState"
        :load-error="sessionCatalogError"
        @open-session="openSession"
        @view-attention="changeTab('sessions')"
        @create-session="newSession"
      />
      <!-- Both handlers refresh silently: these fire while the operator is
           looking at the wizard/detail page, and a foreground refresh would
           drop the list to its loading placeholder behind them. -->
      <CreateSessionPage
        v-else-if="creating"
        @cancel="changeTab('sessions')"
        @saved="refreshSessionCatalog({ silent: true })"
        @started="refreshSessionCatalog({ silent: true })"
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
        @back="returnToSessions"
        @state-changed="refreshSessionCatalog({ silent: true })"
      />
      <SessionsPage
        v-else-if="activeTab === 'sessions'"
        :sessions="sessionCatalog"
        :catalog-state="sessionCatalogState"
        :load-error="sessionCatalogError"
        @open-session="openSession"
        @new-session="newSession"
        @retry="refreshSessionCatalog"
      />
      <ExperimentsPage v-else-if="activeTab === 'experiments'" />
      <DevicesPage v-else-if="activeTab === 'devices'" />
      <TemplatesPage v-else-if="activeTab === 'templates'" />
      <IncidentsPage v-else-if="activeTab === 'incidents'" />
      <OperationsPage v-else-if="activeTab === 'operations'" />
      <SystemHealthPage v-else-if="activeTab === 'system-health'" />
    </main>
  </div>
</template>
