<script setup lang="ts">
import {useRoute} from "#vue-router";
import {useRequest} from "~/services/useRequest";

definePageMeta({
  name: 'users-action',
  layout: 'admin'
})

const $router = useRouter()
const $route = useRoute()

const id = computed(() => $route.query?.id)

const isUpdateMode = computed(() => !!id.value)

const fields = ref({})

async function getData() {
  const response = await useRequest(`/api/users/${id.value}`)

  if (!!response.error) {
    await $router.push("/admin/users");
    return;
  }
  fields.value = response.data;
}

async function sendData() {
  let result = null
  if (isUpdateMode.value) {
    result = await useRequest(`/api/users/${id.value}`, {
      method:'PUT',
      body: fields.value
    });
  } else {
    result = await useRequest(`/api/users`,{
      method:'POST',
      body: fields.value
    });
  }
  if (!!result.error) {
    console.log("Не удалось сохранить пользователя")
  } else {
    console.log("Пользователь сохранён")
    await $router.push("/admin/users");
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
        isUpdateMode ? `Редактирование пользователя ID ${fields.id}` : 'Добавить пользователя'
      }}</h1>
    <input class="action-table__input" type="text" placeholder="Имя пользователя" v-model="fields.username" required/>
    <input class="action-table__input" type="email" placeholder="E-mail" v-model="fields.email" required/>
    <input class="action-table__input" type="text" placeholder="Номер телефона" v-model="fields.phone"/>
    <input class="action-table__input" type="text" placeholder="Роль" v-model="fields.role"/>
    <input v-if="!isUpdateMode" class="action-table__input" type="password" placeholder="Пароль" v-model="fields.password" required/>
    <button type="submit" class="add-button">
      {{ isUpdateMode ? 'Сохранить' : 'Добавить' }}
    </button>
  </form>
</template>

<style scoped>

</style>
