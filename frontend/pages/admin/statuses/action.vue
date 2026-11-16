<script setup lang="ts">
import {useRoute} from "#vue-router";
import {useRequest} from "~/services/useRequest";

definePageMeta({
  name: 'statuses-action',
  layout: 'admin'
})

const $router = useRouter()
const $route = useRoute()

const id = computed(() => $route.query?.id)

const isUpdateMode = computed(() => !!id.value)

const fields = ref({})

async function getData() {
  const response = await useRequest(`/api/statuses/${id.value}`)

  if (!!response.error) {
    await $router.push("/admin/statuses");
    return;
  }
  fields.value = response.data;
}

async function sendData() {
  let result = null
  if (isUpdateMode.value) {
    result = await useRequest(`/api/statuses/${id.value}`, {
      method:'PUT',
      body: fields.value
    });
  } else {
    result = await useRequest(`/api/statuses`,{
      method:'POST',
      body: fields.value
    });
  }
  if (!!result.error) {
    console.log("Не удалось сохранить статус")
  } else {
    console.log("Статус сохранён")
    await $router.push("/admin/statuses");
  }
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
        isUpdateMode ? `Редактирование статуса ID ${fields.id}` : 'Добавить статус'
      }}</h1>
    <input class="action-table__input" type="text" placeholder="Тип" v-model="fields.type" required/>
    <textarea class="action-table__input" placeholder="Описание" v-model="fields.description"/>
    <button type="submit" class="add-button">
      {{ isUpdateMode ? 'Сохранить' : 'Добавить' }}
    </button>
  </form>
</template>

<style scoped>

</style>
