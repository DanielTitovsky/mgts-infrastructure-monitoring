<script setup lang="ts">
import { useRequest } from '~/services/useRequest'

const loading = ref(true)
const loadError = ref('')
const statuses = ref<Record<string, any>[]>([])

const request = await useRequest('/api/statuses')
loading.value = false

if (request.error) {
  loadError.value = request.error.description || 'Не удалось загрузить список статусов.'
} else if (Array.isArray(request.data)) {
  statuses.value = request.data
}
</script>

<template>
  <section class="page-panel">
    <div class="page-heading">
      <div>
        <p class="page-heading__eyebrow">СПРАВОЧНИК</p>
        <h2 class="page-heading__title">Статусы</h2>
      </div>
      <Button
        label="Добавить статус"
        icon="pi pi-plus"
        as="router-link"
        to="/admin/statuses/action"
        class="page-heading__action"
      />
    </div>

    <Message v-if="loadError" severity="error" :closable="false" class="table-message">{{ loadError }}</Message>
    <DataTable
      :value="statuses"
      data-key="id"
      :loading="loading"
      :paginator="statuses.length > 8"
      :rows="8"
      :rows-per-page-options="[8, 16, 32]"
      striped-rows
      scrollable
      table-style="min-width: 36rem"
      class="data-table"
    >
      <Column field="id" header="ID" sortable />
      <Column field="type" header="Тип" sortable>
        <template #body="{ data }">{{ data.type || '—' }}</template>
      </Column>
      <Column field="description" header="Описание">
        <template #body="{ data }">{{ data.description || '—' }}</template>
      </Column>
      <Column header="Действие" header-style="width: 5rem">
        <template #body="{ data }">
          <Button
            as="router-link"
            :to="{ path: '/admin/statuses/action', query: { id: data.id } }"
            icon="pi pi-pencil"
            text
            rounded
            severity="secondary"
            :aria-label="`Редактировать статус ${data.type || data.id}`"
          />
        </template>
      </Column>
      <template #empty>
        <div class="table-empty">
          <i class="pi pi-inbox" aria-hidden="true" />
          <span>{{ loadError ? 'Список временно недоступен' : 'Статусы не найдены' }}</span>
        </div>
      </template>
    </DataTable>
  </section>
</template>
