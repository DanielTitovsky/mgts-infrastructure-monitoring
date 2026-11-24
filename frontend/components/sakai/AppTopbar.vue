<script setup lang="ts">
import { useSakaiLayout } from '~/composables/sakai/useSakaiLayout'
import { computed } from 'vue'
import { useRequest } from '~/services/useRequest'
import { findAdminSection } from './navigation'

const route = useRoute()
const router = useRouter()
const { layoutConfig, toggleMenu, toggleDarkMode } = useSakaiLayout()
const currentSection = computed(() => findAdminSection(route.path))

async function logout() {
  await useRequest('/api/logout', {
    successMessage: 'Вы вышли из системы',
    errorTitle: 'Не удалось выйти из системы',
  })

  // The FastAPI token remains in the existing cookie contract. Clear it even
  // if logout failed so the user cannot remain in the protected workspace.
  useCookie('token').value = null
  await router.push('/admin')
}
</script>

<template>
  <header class="layout-topbar">
    <div class="layout-topbar-logo-container">
      <button
        type="button"
        class="layout-menu-button layout-topbar-action"
        aria-label="Переключить меню"
        @click="toggleMenu"
      >
        <i class="pi pi-bars" aria-hidden="true" />
      </button>
      <NuxtLink class="layout-topbar-logo" to="/admin/objects">
        <i class="pi pi-building" aria-hidden="true" />
        <span>МГТС</span>
      </NuxtLink>
    </div>

    <span class="hidden md:inline text-muted-color font-semibold">
      {{ currentSection?.label || 'Мониторинг инфраструктуры' }}
    </span>

    <div class="layout-topbar-actions">
      <button
        type="button"
        class="layout-topbar-action"
        :aria-label="layoutConfig.darkTheme ? 'Включить светлую тему' : 'Включить тёмную тему'"
        @click="toggleDarkMode"
      >
        <i :class="['pi', layoutConfig.darkTheme ? 'pi-sun' : 'pi-moon']" aria-hidden="true" />
      </button>
      <Button
        label="Выйти"
        icon="pi pi-sign-out"
        severity="secondary"
        outlined
        @click="logout"
      />
    </div>
  </header>
</template>
