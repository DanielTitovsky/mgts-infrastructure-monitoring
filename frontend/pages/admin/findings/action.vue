<script setup lang="ts">
import {useRoute} from "#vue-router";
import {useRequest} from "~/services/useRequest";

definePageMeta({
  name: 'findings-action',
  layout: 'admin'
})

const $router = useRouter()
const $route = useRoute()

const id = computed(() => $route.query?.id)

const isUpdateMode = computed(() => !!id.value)

const fields = ref({})

async function getData() {
  const response = await useRequest(`/api/defects/${id.value}`)

  if (!!response.error) {
    await $router.push("/admin/findings");
    return;
  }
  fields.value = response.data;
}

async function sendData() {
  const successMessage = isUpdateMode.value ? 'Дефект сохранён' : 'Дефект создан'
  const errorTitle = 'Не удалось сохранить дефект'

  const result = isUpdateMode.value
    ? await useRequest(`/api/defects/${id.value}`, {
      method: 'PUT',
      body: fields.value,
      successMessage,
      errorTitle
    })
    : await useRequest('/api/defects', {
      method: 'POST',
      body: fields.value,
      successMessage,
      errorTitle
    })

  if (!!result.error) return

  await $router.push("/admin/findings");
}

onMounted(() => {
  if (isUpdateMode.value) {
    getData()
  }
})
</script>

<template>
  <form class="action-table" @submit.prevent="sendData">
    <h1 class="action-table__title">{{
        isUpdateMode ? `Редактирование дефекта ID ${fields.id}` : 'Добавить дефект'
      }}</h1>
    <input class="action-table__input" type="text" placeholder="ID наблюдения" v-model="fields.detection_id" required/>
    <input class="action-table__input" type="text" placeholder="Признак" v-model="fields.defect_type" required/>
    <input class="action-table__input" type="text" placeholder="Уверенность" v-model="fields.defect_confidence"/>
    <input class="action-table__input" type="text" placeholder="Критичность" v-model="fields.severity"/>
    <input class="action-table__input" type="text" placeholder="Рекомендованное действие" v-model="fields.recommended_action"/>
    <button type="submit" class="add-button">
      {{ isUpdateMode ? 'Сохранить' : 'Добавить' }}
    </button>
  </form>
</template>

<style scoped>

</style>
