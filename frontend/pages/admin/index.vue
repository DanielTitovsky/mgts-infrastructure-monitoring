<script setup lang="ts">
import { useNotifications } from '~/composables/useNotifications'
import { useRequest } from '~/services/useRequest'

definePageMeta({ layout: 'default' })

const router = useRouter()
const notifications = useNotifications()
const login = ref('')
const password = ref('')
const submitting = ref(false)
const formError = ref('')

async function onSubmit() {
  if (submitting.value) return

  submitting.value = true
  formError.value = ''

  try {
    const request = await useRequest('/api/auth/login', {
      method: 'POST',
      body: { username: login.value, password: password.value },
      successMessage: false,
      errorTitle: 'Не удалось войти',
    })

    if (request.error) {
      formError.value = request.error.description || request.error.message || 'Проверьте данные и попробуйте ещё раз.'
      return
    }

    const token = request.data?.token
    if (!token) {
      formError.value = 'Сервер не вернул токен доступа.'
      notifications.error(formError.value, 'Не удалось войти')
      return
    }

    // Keep the existing FastAPI token-cookie contract.
    useCookie('token').value = token
    notifications.success('Вы вошли в систему')
    await router.push('/admin/objects')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="login-shell">
    <Card class="login-card">
      <template #content>
        <div class="login-brand">
          <span class="brand-mark" aria-hidden="true">М</span>
          <span class="login-brand__name">МГТС</span>
        </div>
        <p class="login-eyebrow">ГОРОДСКАЯ СЕТЕВАЯ ИНФРАСТРУКТУРА</p>
        <h1>Вход в систему</h1>
        <p class="login-intro">Продолжите работу с объектами и результатами мониторинга.</p>

        <form class="login-form" @submit.prevent="onSubmit">
          <div class="form-field">
            <label for="login-username">Имя пользователя</label>
            <InputText
              id="login-username"
              v-model="login"
              name="username"
              autocomplete="username"
              placeholder="Введите имя пользователя"
              required
              class="form-control"
            />
          </div>
          <div class="form-field">
            <label for="login-password">Пароль</label>
            <InputText
              id="login-password"
              v-model="password"
              name="password"
              type="password"
              autocomplete="current-password"
              placeholder="Введите пароль"
              required
              class="form-control"
            />
          </div>

          <Message v-if="formError" severity="error" :closable="false">{{ formError }}</Message>
          <Button type="submit" label="Войти" icon="pi pi-arrow-right" icon-pos="right" :loading="submitting" />
        </form>

        <p class="login-help">
          <i class="pi pi-lock" aria-hidden="true" />
          Забыли пароль? Обратитесь к администратору системы мониторинга.
        </p>
      </template>
    </Card>
    <p class="login-footer">Система мониторинга городской инфраструктуры</p>
  </main>
</template>
