<script setup>
import { Plus } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";

defineProps({
  eyebrow: String,
  title: { type: String, required: true },
  description: String,
  actionLabel: { type: String, default: "Create" },
  secondaryActionLabel: String,
  columns: { type: Array, required: true },
  items: { type: Array, required: true },
});
</script>

<template>
  <div class="page page--workspace">
    <PageHeader :eyebrow="eyebrow" :title="title" :description="description">
      <BaseButton><Plus :size="16" /> {{ actionLabel }}</BaseButton>
    </PageHeader>
    <BaseCard class="workspace-card">
      <div class="catalog-summary">
        <strong>{{ items.length }}</strong>
        <span>active records</span>
      </div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th v-for="column in columns" :key="column.key">{{ column.label }}</th><th /></tr></thead>
          <tbody>
            <tr v-for="item in items" :key="item.name">
              <td v-for="column in columns" :key="column.key">
                <strong v-if="column.key === 'name'">{{ item[column.key] }}</strong>
                <span v-else>{{ item[column.key] }}</span>
              </td>
              <td><div class="row-actions"><button type="button" class="table-action">Open</button><button v-if="secondaryActionLabel" type="button" class="table-action">{{ secondaryActionLabel }}</button></div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </BaseCard>
  </div>
</template>
