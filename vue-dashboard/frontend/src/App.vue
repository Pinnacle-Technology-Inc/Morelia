<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import AppHeader from "./components/AppHeader.vue";
import PrimaryNav from "./components/PrimaryNav.vue";
import CatalogPage from "./pages/CatalogPage.vue";
import CreateSessionPage from "./pages/CreateSessionPage.vue";
import DevicesPage from "./pages/DevicesPage.vue";
import IncidentsPage from "./pages/IncidentsPage.vue";
import OperationsPage from "./pages/OperationsPage.vue";
import OverviewPage from "./pages/OverviewPage.vue";
import SessionDetailPage from "./pages/SessionDetailPage.vue";
import SessionsPage from "./pages/SessionsPage.vue";
import SystemHealthPage from "./pages/SystemHealthPage.vue";
import TemplatesPage from "./pages/TemplatesPage.vue";
import { experiments, sessions } from "./data";
import { parseHash, toHash } from "./navigation-utils";
import { loadSessionCatalog } from "./session-api";

const initialRoute = parseHash(window.location.hash);
const activeTab = ref(initialRoute.tab);
const selectedSessionId = ref(initialRoute.sessionId);
const creating = ref(initialRoute.creating);
const sessionCatalog = ref(sessions);
const sessionCatalogState = ref("loading");
const sessionCatalogError = ref("");
const selectedSession = computed(() =>
  sessionCatalog.value.find((session) => session.id === selectedSessionId.value),
);

const catalogConfig = {
  experiments: {
    eyebrow: "Organizational workspace",
    title: "Experiments",
    description: "Group related sessions without affecting hardware execution.",
    actionLabel: "New Experiment",
    secondaryActionLabel: "Add Note",
    items: experiments,
    columns: [
      { key: "name", label: "Experiment" },
      { key: "description", label: "Description" },
      { key: "sessions", label: "Sessions" },
      { key: "active", label: "Active" },
      { key: "attention", label: "Needs Attention" },
    ],
  },
};

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

async function refreshSessionCatalog() {
  sessionCatalogState.value = "loading";
  sessionCatalogError.value = "";
  try {
    sessionCatalog.value = await loadSessionCatalog();
    sessionCatalogState.value = "live";
  } catch (error) {
    sessionCatalog.value = sessions;
    sessionCatalogState.value = "sample";
    sessionCatalogError.value = error instanceof Error ? error.message : "Could not load sessions.";
  }
}

onMounted(() => {
  refreshSessionCatalog();
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
        v-if="activeTab === 'overview' && !selectedSession && !creating"
        @open-session="openSession"
        @view-attention="changeTab('sessions')"
      />
      <CreateSessionPage v-else-if="creating" @cancel="changeTab('sessions')" />
      <SessionDetailPage v-else-if="selectedSession" :session="selectedSession" @back="changeTab('sessions')" />
      <SessionsPage
        v-else-if="activeTab === 'sessions'"
        :sessions="sessionCatalog"
        :catalog-state="sessionCatalogState"
        :load-error="sessionCatalogError"
        @open-session="openSession"
        @new-session="newSession"
        @retry="refreshSessionCatalog"
      />
      <CatalogPage v-else-if="catalogConfig[activeTab]" v-bind="catalogConfig[activeTab]" />
      <DevicesPage v-else-if="activeTab === 'devices'" />
      <TemplatesPage v-else-if="activeTab === 'templates'" />
      <IncidentsPage v-else-if="activeTab === 'incidents'" />
      <OperationsPage v-else-if="activeTab === 'operations'" />
      <SystemHealthPage v-else-if="activeTab === 'system-health'" />
    </main>
  </div>
</template>
