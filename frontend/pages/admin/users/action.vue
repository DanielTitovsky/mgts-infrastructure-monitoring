<script setup lang="ts">
import { useRoute } from '#vue-router'
import { useRequest } from '~/services/useRequest'

definePageMeta({ name: 'users-action', layout: 'admin' })

const router = useRouter()
const route = useRoute()
const id = computed(() => route.query?.id)
const isUpdateMode = computed(() => !!id.value)
const fields = ref<Record<string, any>>({})
const loading = ref(false)
const saving = ref(false)
const formError = ref('')

async function getData() {
  loading.value = true
  try {
    const response = await useRequest(`/api/users/${id.value}`)
    if (response.error) {
      await router.push('/admin/users')
      return
    }
    fields.value = response.data || {}
  } finally {
    loading.value = false
  }
}

async function sendData() {
  if (saving.value) return
  saving.value = true
  formError.value = ''

  try {
    const successMessage = isUpdateMode.value ? 'Пользователь сохранён' : 'Пользователь создан'
    const result = isUpdateMode.value
      ? await useRequest(`/api/users/${id.value}`, { method: 'PUT', body: fields.value, successMessage, errorTitle: 'Не удалось сохранить пользователя' })
      : await useRequest('/api/users', { method: 'POST', body: fields.value, successMessage, errorTitle: 'Не удалось сохранить пользователя' })

    if (result.error) {
      formError.value = result.error.description || 'Проверьте данные и попробуйте ещё раз.'
      return
    }

    await router.push('/admin/users')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  if (isUpdateMode.value) getData()
})
</script>

<template>
  <form class="page-panel entity-form" @submit.prevent="sendData">
    <div class="page-heading">
      <div>
        <p class="page-heading__eyebrow">УЧЁТНЫЕ ЗАПИСИ</p>
        <h2 class="page-heading__title">{{ isUpdateMode ? `Редактирование пользователя №${fields.id || id}` : 'Добавить пользователя' }}</h2>
      </div>
      <Button label="К списку" icon="pi pi-arrow-left" severity="secondary" outlined as="router-link" to="/admin/users" />
    </div>

    <Message v-if="loading" severity="info" :closable="false">Загрузка данных пользователя…</Message>
    <Message v-if="formError" severity="error" :closable="false">{{ formError }}</Message>

    <div class="entity-form__grid">
      <div class="form-field">
        <label for="user-username">Имя пользователя</label>
        <InputText id="user-username" v-model="fields.username" autocomplete="username" required class="form-control" />
      </div>
      <div class="form-field">
        <label for="user-email">E-mail</label>
        <InputText id="user-email" v-model="fields.email" type="email" autocomplete="email" required class="form-control" />
      </div>
      <div class="form-field">
        <label for="user-phone">Номер телефона</label>
        <InputText id="user-phone" v-model="fields.phone" type="tel" autocomplete="tel" class="form-control" />
      </div>
      <div class="form-field">
        <label for="user-role">Роль</label>
        <InputText id="user-role" v-model="fields.role" class="form-control" />
      </div>
      <div v-if="!isUpdateMode" class="form-field">
        <label for="user-password">Пароль</label>
        <InputText id="user-password" v-model="fields.password" type="password" autocomplete="new-password" required class="form-control" />
      </div>
    </div>

    <div class="entity-form__actions">
      <Button type="submit" :label="saving ? 'Сохранение…' : (isUpdateMode ? 'Сохранить изменения' : 'Создать пользователя')" icon="pi pi-check" :loading="saving" :disabled="loading" />
    </div>
  </form>
</template>
