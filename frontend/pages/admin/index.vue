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
  <main class="bg-surface-50 dark:bg-surface-950 flex items-center justify-center min-h-screen min-w-[100vw] overflow-hidden">
    <div class="flex flex-col items-center justify-center">
      <div style="border-radius: 56px; padding: 0.3rem; background: linear-gradient(180deg, var(--primary-color) 10%, rgba(33, 150, 243, 0) 30%)">
        <div class="w-full bg-surface-0 dark:bg-surface-900 py-12 px-8 sm:px-20" style="border-radius: 53px">
          <div class="text-center mb-8">
            <p class="text-primary text-xs font-semibold uppercase tracking-wide mb-2">Городская сетевая инфраструктура</p>
            <div class="text-surface-900 dark:text-surface-0 text-xl font-semibold mb-2">МГТС</div>
            <h1 class="text-surface-900 dark:text-surface-0 text-3xl font-medium mb-4">Вход в систему</h1>
            <span class="text-muted-color font-medium">Продолжите работу с объектами и результатами мониторинга.</span>
          </div>

          <form class="flex flex-col gap-6" @submit.prevent="onSubmit">
            <div class="flex flex-col gap-2">
              <label for="login-username" class="block text-surface-900 dark:text-surface-0 font-medium">Имя пользователя</label>
              <InputText
                id="login-username"
                v-model="login"
                name="username"
                autocomplete="username"
                placeholder="Введите имя пользователя"
                required
                class="w-full"
              />
            </div>
            <div class="flex flex-col gap-2">
              <label for="login-password" class="block text-surface-900 dark:text-surface-0 font-medium">Пароль</label>
              <InputText
                id="login-password"
                v-model="password"
                name="password"
                type="password"
                autocomplete="current-password"
                placeholder="Введите пароль"
                required
                class="w-full"
              />
            </div>

            <Message v-if="formError" severity="error" :closable="false">{{ formError }}</Message>
            <Button type="submit" label="Войти" :loading="submitting" class="w-full" />
          </form>

          <p class="text-muted-color text-sm mt-6">
            <i class="pi pi-lock mr-2" aria-hidden="true" />
            Забыли пароль? Обратитесь к администратору системы мониторинга.
          </p>
        </div>
      </div>
    </div>
  </main>
</template>
