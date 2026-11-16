<script setup lang="ts">
import {useRoute} from "#vue-router";
import {useRequest} from "~/services/useRequest";

definePageMeta({
  name: 'objects-action',
  layout: 'admin'
})

const $router = useRouter()
const $route = useRoute()

const id = computed(() => $route.query?.id)

const isUpdateMode = computed(() => !!id.value)

const fields = ref({})

async function getData() {
  const response = await useRequest(`/api/infrastructure-objects/${id.value}`)

  if (!!response.error) {
    await $router.push("/admin/objects");
    return;
  }
  fields.value = response.data;
}

async function sendData() {
  let result = null
  if (isUpdateMode.value) {
    result = await useRequest(`/api/infrastructure-objects/${id.value}`, {
      method:'PUT',
      body: fields.value
    });
  } else {
    result = await useRequest(`/api/infrastructure-objects`,{
      method:'POST',
      body: fields.value
    });
  }
  if (!!result.error) {
    console.log("Не удалось сохранить объект")
  } else {
    console.log("Объект сохранён")
    await $router.push("/admin/objects");
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
        isUpdateMode ? `Редактирование объекта ID ${fields.id}` : 'Добавить объект'
      }}</h1>
    <input class="action-table__input" type="text" placeholder="Тип объекта" v-model="fields.type" required/>
    <input class="action-table__input" type="text" placeholder="Внешний идентификатор" v-model="fields.external_id"/>
    <input class="action-table__input" type="text" placeholder="Место" v-model="fields.place"/>
    <input class="action-table__input" type="text" placeholder="Широта" v-model="fields.lat"/>
    <input class="action-table__input" type="text" placeholder="Долгота" v-model="fields.lon"/>
    <input class="action-table__input" type="text" placeholder="ID статуса" v-model="fields.status_id"/>
    <button type="submit" class="add-button">
      {{ isUpdateMode ? 'Сохранить' : 'Добавить' }}
    </button>
  </form>
</template>

<style scoped>

</style>
