<script setup lang="ts">
import {useRequest} from "~/services/useRequest";

const request = await useRequest('/api/statuses');

const statuses = ref(request.data)
</script>

<template>
  <div class="all-table">
    <h1 class="title">Статусы</h1>
    <table class="table">
      <thead>
      <tr class="table__thead-str">
        <th class="table__thead-item">ID</th>
        <th class="table__thead-item">Тип</th>
        <th class="table__thead-item">Описание</th>
        <th></th>
      </tr>
      </thead>
      <tbody>
      <tr v-for="item in statuses" :key="`status_${item.id}`" class="table__tbody-str">
        <td class="table__item">
          {{ item?.id || '-' }}
        </td>
        <td class="table__item">
          {{ item?.type || '-' }}
        </td>
        <td class="table__item">
          {{ item?.description || '-' }}
        </td>
        <td>
          <nuxt-link :to="{ path: '/admin/statuses/action', query: { id: item.id } }">
            <icon name="icon-edit"/>
          </nuxt-link>
        </td>
      </tr>
      </tbody>
    </table>
    <nuxt-link to="/admin/statuses/action" class="add-button">Добавить статус</nuxt-link>
  </div>
</template>

<style scoped>

</style>
