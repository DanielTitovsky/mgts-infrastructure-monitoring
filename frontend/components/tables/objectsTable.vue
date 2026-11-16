<script setup lang="ts">
import {useRequest} from "~/services/useRequest";

const request = await useRequest('/api/infrastructure-objects');

const objects = ref(request.data)
</script>

<template>
  <div class="all-table">
    <h1 class="title">Объекты инфраструктуры</h1>
    <table class="table">
      <thead>
      <tr class="table__thead-str">
        <th class="table__thead-item">ID</th>
        <th class="table__thead-item">Тип</th>
        <th class="table__thead-item">Внешний идентификатор</th>
        <th class="table__thead-item">Место</th>
        <th class="table__thead-item">Координаты</th>
        <th class="table__thead-item">Статус</th>
        <th></th>
      </tr>
      </thead>
      <tbody>
      <tr v-for="item in objects" :key="`object_${item.id}`" class="table__tbody-str">
        <td class="table__item">
          {{ item?.id || '-' }}
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
        <td class="table__item">
          {{ item?.status_id || '-' }}
        </td>
        <td>
          <nuxt-link :to="{ path: '/admin/objects/action', query: { id: item.id } }">
            <icon name="icon-edit"/>
          </nuxt-link>
        </td>
      </tr>
      </tbody>
    </table>
    <nuxt-link to="/admin/objects/action" class="add-button">Добавить объект</nuxt-link>
  </div>
</template>

<style scoped>

</style>
