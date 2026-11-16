<script setup lang="ts">
import {useFilters} from "~/composables/useFilters";
import {useRequest} from "~/services/useRequest";

const { dateFormat } = useFilters()

const request = await useRequest('/api/users');

const users = ref(request.data)
</script>

<template>
  <div class="all-table">
    <h1 class="title">Пользователи</h1>
    <table class="table">
      <thead>
      <tr class="table__thead-str">
        <th class="table__thead-item">ID</th>
        <th class="table__thead-item">Имя пользователя</th>
        <th class="table__thead-item">E-mail</th>
        <th class="table__thead-item">Номер телефона</th>
        <th class="table__thead-item">Роль</th>
        <th class="table__thead-item">Дата создания</th>
        <th class="table__thead-item">Дата обновления</th>
        <th></th>
      </tr>
      </thead>
      <tbody>
      <tr v-for="item in users" :key="`user_${item.id}`" class="table__tbody-str">
        <td class="table__item">
          {{ item?.id || '-' }}
        </td>
        <td class="table__item">
          {{ item?.username || '-' }}
        </td>
        <td class="table__item">
          {{ item?.email || '-' }}
        </td>
        <td class="table__item">
          {{ item?.phone || '-' }}
        </td>
        <td class="table__item">
          {{ item?.role || '-' }}
        </td>
        <td class="table__item">
          {{ dateFormat(item?.created_at || '-') }}
        </td>
        <td class="table__item">
          {{ dateFormat(item?.updated_at || '-') }}
        </td>
        <td>
          <nuxt-link :to="{ path: '/admin/users/action', query: { id: item.id } }">
            <icon name="icon-edit"/>
          </nuxt-link>
        </td>
      </tr>
      </tbody>
    </table>
    <nuxt-link to="/admin/users/action" class="add-button">Добавить пользователя</nuxt-link>
  </div>
</template>

<style scoped>

</style>
