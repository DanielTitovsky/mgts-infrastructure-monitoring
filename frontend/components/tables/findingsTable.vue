<script setup lang="ts">
import { useFilters } from '~/composables/useFilters'
import { useRequest } from '~/services/useRequest'

const { dateFormat } = useFilters()
const loading = ref(true)
const loadError = ref('')
const findings = ref<Record<string, any>[]>([])

const request = await useRequest('/api/defects')
loading.value = false

if (request.error) {
  loadError.value = request.error.description || 'Не удалось загрузить список дефектов.'
} else if (Array.isArray(request.data)) {
  findings.value = request.data
}
</script>

<template>
  <section class="page-panel">
    <div class="page-heading">
      <div>
        <p class="page-heading__eyebrow">РЕЗУЛЬТАТЫ ОБРАБОТКИ</p>
        <h2 class="page-heading__title">Дефекты</h2>
      </div>
      <span class="page-heading__count">{{ findings.length }} записей</span>
    </div>

    <Message v-if="loadError" severity="error" :closable="false" class="table-message">{{ loadError }}</Message>
    <DataTable
      :value="findings"
      data-key="finding_id"
      :loading="loading"
      :paginator="findings.length > 8"
      :rows="8"
      :rows-per-page-options="[8, 16, 32]"
      striped-rows
      scrollable
      table-style="min-width: 69rem"
      class="data-table"
    >
      <Column field="finding_id" header="ID" sortable>
        <template #body="{ data }">{{ data.finding_id || data.id || '—' }}</template>
      </Column>
      <Column field="detection_id" header="Наблюдение" sortable>
        <template #body="{ data }">{{ data.detection_id || '—' }}</template>
      </Column>
      <Column field="defect_type" header="Признак" sortable>
        <template #body="{ data }">{{ data.defect_type || '—' }}</template>
      </Column>
      <Column field="defect_confidence" header="Уверенность" sortable>
        <template #body="{ data }">{{ data.defect_confidence ?? '—' }}</template>
      </Column>
      <Column field="severity" header="Критичность" sortable>
        <template #body="{ data }">
          <Tag v-if="data.severity" :value="data.severity" :severity="data.severity === 'high' ? 'danger' : data.severity === 'medium' ? 'warn' : 'secondary'" />
          <span v-else class="muted-value">Не указана</span>
        </template>
      </Column>
      <Column field="recommended_action" header="Рекомендованное действие" sortable>
        <template #body="{ data }">{{ data.recommended_action || '—' }}</template>
      </Column>
      <Column field="created_at" header="Дата создания" sortable>
        <template #body="{ data }">{{ data.created_at ? dateFormat(data.created_at) : '—' }}</template>
      </Column>
      <Column header="Действие" header-style="width: 5rem">
        <template #body="{ data }">
          <Button
            as="router-link"
            :to="{ path: '/admin/findings/action', query: { id: data.finding_id || data.id } }"
            icon="pi pi-pencil"
            text
            rounded
            severity="secondary"
            :aria-label="`Редактировать дефект ${data.finding_id || data.id}`"
          />
        </template>
      </Column>
      <template #empty>
        <div class="table-empty">
          <i class="pi pi-inbox" aria-hidden="true" />
          <span>{{ loadError ? 'Список временно недоступен' : 'Дефекты не найдены' }}</span>
        </div>
      </template>
    </DataTable>
  </section>
</template>
