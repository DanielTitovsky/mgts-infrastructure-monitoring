<script setup lang="ts">
import {useFilters} from "~/composables/useFilters";
import {useRequest} from "~/services/useRequest";

const { dateFormat } = useFilters()

const request = await useRequest('/api/defects');

const findings = ref(request.data)
</script>

<template>
  <div class="all-table">
    <h1 class="title">Дефекты</h1>
    <table class="table">
      <thead>
      <tr class="table__thead-str">
        <th class="table__thead-item">ID</th>
        <th class="table__thead-item">Наблюдение</th>
        <th class="table__thead-item">Признак</th>
        <th class="table__thead-item">Уверенность</th>
        <th class="table__thead-item">Критичность</th>
        <th class="table__thead-item">Рекомендованное действие</th>
        <th class="table__thead-item">Дата создания</th>
        <th></th>
      </tr>
      </thead>
      <tbody>
      <tr v-for="item in findings" :key="`finding_${item.finding_id || item.id}`" class="table__tbody-str">
        <td class="table__item">
          {{ item?.finding_id || item?.id || '-' }}
        </td>
        <td class="table__item">
          {{ item?.detection_id || '-' }}
        </td>
        <td class="table__item">
          {{ item?.defect_type || '-' }}
        </td>
        <td class="table__item">
          {{ item?.defect_confidence ?? '-' }}
        </td>
        <td class="table__item">
          {{ item?.severity || '-' }}
        </td>
        <td class="table__item">
          {{ item?.recommended_action || '-' }}
        </td>
        <td class="table__item">
          {{ item?.created_at ? dateFormat(item.created_at) : '-' }}
        </td>
        <td>
          <nuxt-link :to="{ path: '/admin/findings/action', query: { id: item.finding_id || item.id } }">
            <icon name="icon-edit"/>
          </nuxt-link>
        </td>
      </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>

</style>
