<script setup lang="ts">
import {useRequest} from "~/services/useRequest";

const PROCESSING_LABELS: Record<string, string> = {
  pending: 'Ожидает обработки',
  processing: 'Обрабатывается',
  done: 'Обработано',
  failed: 'Ошибка'
}

const [objectsResponse, statusesResponse] = await Promise.all([
  useRequest('/api/infrastructure-objects'),
  useRequest('/api/statuses')
])

const objects = ref(Array.isArray(objectsResponse.data) ? objectsResponse.data : [])
const statuses = ref(Array.isArray(statusesResponse.data) ? statusesResponse.data : [])

const statusesById = computed(() => {
  const map: Record<string, Record<string, any>> = {}

  for (const status of statuses.value) {
    map[String(status.id)] = status
  }

  return map
})

const hasProcessing = computed(() =>
  objects.value.some((item: Record<string, any>) => !!item.processing_status)
)

function statusLabel(item: Record<string, any>) {
  const status = statusesById.value[String(item?.status_id)]
  return status?.type || item?.status_id || '-'
}

function statusDescription(item: Record<string, any>) {
  const status = statusesById.value[String(item?.status_id)]
  return status?.description || ''
}

function processingLabel(item: Record<string, any>) {
  const status = item?.processing_status
  return status ? (PROCESSING_LABELS[status] || status) : '-'
}
</script>

<template>
  <div class="all-table">
    <h1 class="title">Объекты инфраструктуры</h1>
    <table class="table">
      <thead>
      <tr class="table__thead-str">
        <th class="table__thead-item">ID</th>
        <th class="table__thead-item">Фото</th>
        <th class="table__thead-item">Тип</th>
        <th class="table__thead-item">Внешний идентификатор</th>
        <th class="table__thead-item">Место</th>
        <th class="table__thead-item">Координаты</th>
        <th class="table__thead-item">Статус</th>
        <th v-if="hasProcessing" class="table__thead-item">Обработка</th>
        <th></th>
      </tr>
      </thead>
      <tbody>
      <tr v-for="item in objects" :key="`object_${item.id}`" class="table__tbody-str">
        <td class="table__item">
          {{ item?.id || '-' }}
        </td>
        <td class="table__item">
          <a v-if="item?.img_url" :href="item.img_url" target="_blank" rel="noopener" class="table__thumb-link">
            <img :src="item.img_url" alt="Фото объекта" class="table__thumb" loading="lazy"/>
          </a>
          <span v-else>—</span>
        </td>
        <td class="table__item">
          {{ item?.type || '-' }}
        </td>
        <td class="table__item">
          {{ item?.external_id || '-' }}
        </td>
        <td class="table__item">
          {{ item?.place || '-' }}
        </td>
        <td class="table__item">
          {{ (item?.lat != null && item?.lon != null) ? `${item.lat}, ${item.lon}` : '-' }}
        </td>
        <td class="table__item" :title="statusDescription(item)">
          {{ statusLabel(item) }}
        </td>
        <td v-if="hasProcessing" class="table__item" :title="item?.processing_error || ''">
          {{ processingLabel(item) }}
        </td>
        <td>
          <nuxt-link :to="{ path: '/admin/objects/action', query: { id: item.id } }">
            <icon name="icon-edit"/>
          </nuxt-link>
        </td>
      </tr>
      <tr v-if="!objects.length">
        <td :colspan="hasProcessing ? 9 : 8" class="table__empty">
          Объекты не найдены
        </td>
      </tr>
      </tbody>
    </table>
    <nuxt-link to="/admin/objects/action" class="add-button">Добавить объект</nuxt-link>
  </div>
</template>

<style scoped lang="scss">
.table {
  &__thumb-link {
    display: inline-flex;
  }

  &__thumb {
    display: block;
    width: 76px;
    height: 57px;
    object-fit: cover;
    border-radius: 4px;
    border: 1px solid #E3E3E3;
    background: #F7F7F9;
  }

  &__empty {
    padding: 20px 0;
    color: #B0B0B0;
    font-size: 14px;
    text-align: center;
  }
}
</style>
