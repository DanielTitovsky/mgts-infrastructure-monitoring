<script setup lang="ts">
import { useFilters } from '~/composables/useFilters'
import { useRequest } from '~/services/useRequest'

const { dateFormat } = useFilters()
const loading = ref(true)
const loadError = ref('')
const users = ref<Record<string, any>[]>([])

const request = await useRequest('/api/users')
loading.value = false

if (request.error) {
  loadError.value = request.error.description || 'Не удалось загрузить список пользователей.'
} else if (Array.isArray(request.data)) {
  users.value = request.data
}
</script>

<template>
  <section class="page-panel">
    <div class="page-heading">
      <div>
        <p class="page-heading__eyebrow">УЧЁТНЫЕ ЗАПИСИ</p>
        <h2 class="page-heading__title">Пользователи</h2>
      </div>
      <Button
        label="Добавить пользователя"
        icon="pi pi-plus"
        as="router-link"
        to="/admin/users/action"
        class="page-heading__action"
      />
    </div>

    <Message v-if="loadError" severity="error" :closable="false" class="table-message">{{ loadError }}</Message>
    <DataTable
      :value="users"
      data-key="id"
      :loading="loading"
      :paginator="users.length > 8"
      :rows="8"
      :rows-per-page-options="[8, 16, 32]"
      striped-rows
      scrollable
      table-style="min-width: 68rem"
      class="data-table"
    >
      <Column field="id" header="ID" sortable />
      <Column field="username" header="Имя пользователя" sortable>
        <template #body="{ data }">{{ data.username || '—' }}</template>
      </Column>
      <Column field="email" header="E-mail" sortable>
        <template #body="{ data }">{{ data.email || '—' }}</template>
      </Column>
      <Column field="phone" header="Номер телефона">
        <template #body="{ data }">{{ data.phone || '—' }}</template>
      </Column>
      <Column field="role" header="Роль" sortable>
        <template #body="{ data }">{{ data.role || '—' }}</template>
      </Column>
      <Column field="created_at" header="Создан" sortable>
        <template #body="{ data }">{{ data.created_at ? dateFormat(data.created_at) : '—' }}</template>
      </Column>
      <Column field="updated_at" header="Обновлён" sortable>
        <template #body="{ data }">{{ data.updated_at ? dateFormat(data.updated_at) : '—' }}</template>
      </Column>
      <Column header="Действие" header-style="width: 5rem">
        <template #body="{ data }">
          <Button
            as="router-link"
            :to="{ path: '/admin/users/action', query: { id: data.id } }"
            icon="pi pi-pencil"
            text
            rounded
            severity="secondary"
            :aria-label="`Редактировать пользователя ${data.username || data.id}`"
          />
        </template>
      </Column>
      <template #empty>
        <div class="table-empty">
          <i class="pi pi-inbox" aria-hidden="true" />
          <span>{{ loadError ? 'Список временно недоступен' : 'Пользователи не найдены' }}</span>
        </div>
      </template>
    </DataTable>
  </section>
</template>
