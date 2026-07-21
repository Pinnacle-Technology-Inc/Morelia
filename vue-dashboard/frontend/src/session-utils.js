export const sessionTabs = [
  { id: "needs-attention", label: "Needs Attention" },
  { id: "active", label: "Active" },
  { id: "scheduled", label: "Scheduled" },
  { id: "drafts", label: "Drafts" },
  { id: "completed", label: "Completed" },
  { id: "archived", label: "Archived" },
];

export function sessionMatchesTab(session, tab) {
  if (tab === "needs-attention") return session.health === "Needs action";
  if (tab === "active") return ["Active", "Starting", "Ending"].includes(session.lifecycle);
  if (tab === "scheduled") return session.lifecycle === "Scheduled";
  if (tab === "drafts") return session.lifecycle === "Draft";
  if (tab === "completed") return session.lifecycle === "Completed" && !session.archived;
  if (tab === "archived") return session.archived === true;
  return false;
}

export function filterSessions(sessions, tab, search = "") {
  const query = search.trim().toLowerCase();
  return sessions.filter((session) => {
    const matchesSearch =
      !query ||
      session.name.toLowerCase().includes(query) ||
      session.experiment?.toLowerCase().includes(query);
    return sessionMatchesTab(session, tab) && matchesSearch;
  });
}

export function countSessionsForTab(sessions, tab) {
  return sessions.filter((session) => sessionMatchesTab(session, tab)).length;
}

export function summarizeAttentionSessions(sessions, limit = 3) {
  const attentionSessions = sessions.filter((session) => sessionMatchesTab(session, "needs-attention"));
  const visible = attentionSessions.slice(0, limit);

  return {
    total: attentionSessions.length,
    visible,
    hidden: attentionSessions.length - visible.length,
  };
}
