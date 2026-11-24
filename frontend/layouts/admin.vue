<script setup lang="ts">
import { useRequest } from '~/services/useRequest'

const route = useRoute()
const router = useRouter()
const menuOpen = ref(false)

const navigation = [
  { to: '/admin/users', label: 'Пользователи', icon: 'pi pi-users' },
  { to: '/admin/objects', label: 'Объекты', icon: 'pi pi-box' },
  { to: '/admin/findings', label: 'Дефекты', icon: 'pi pi-exclamation-triangle' },
  { to: '/admin/statuses', label: 'Статусы', icon: 'pi pi-tag' },
  { to: '/admin/map', label: 'Карта', icon: 'pi pi-map' },
]

const activeSection = computed(() => navigation.find(item =>
  route.path === item.to || route.path.startsWith(`${item.to}/`),
))
const pageTitle = computed(() => activeSection.value?.label || 'Мониторинг инфраструктуры')

async function logout() {
  await useRequest('/api/logout', {
    successMessage: 'Вы вышли из системы',
    errorTitle: 'Не удалось выйти из системы',
  })

  // The FastAPI token remains in the existing cookie contract. Clear it even
  // if logout failed so the user cannot remain in the protected workspace.
  useCookie('token').value = null
  menuOpen.value = false
  await router.push('/admin')
}
</script>

<template>
  <div class="admin-shell">
    <button
      v-if="menuOpen"
      class="sidebar-scrim"
      type="button"
      aria-label="Закрыть меню"
      @click="menuOpen = false"
    />

    <aside class="app-sidebar" :class="{ 'is-open': menuOpen }">
      <NuxtLink class="brand" to="/admin/objects" @click="menuOpen = false">
        <span class="brand-mark" aria-hidden="true">М</span>
        <span class="brand-copy">
          <strong>МГТС</strong>
          <small>Мониторинг инфраструктуры</small>
        </span>
      </NuxtLink>

      <div class="sidebar-caption">РАБОЧАЯ ОБЛАСТЬ</div>
      <nav class="side-navigation" aria-label="Основная навигация">
        <NuxtLink
          v-for="item in navigation"
          :key="item.to"
          :to="item.to"
          class="side-navigation__link"
          :class="{ 'is-active': activeSection?.to === item.to }"
          :aria-current="activeSection?.to === item.to ? 'page' : undefined"
          @click="menuOpen = false"
        >
          <i :class="item.icon" aria-hidden="true" />
          <span>{{ item.label }}</span>
          <i v-if="activeSection?.to === item.to" class="pi pi-angle-right side-navigation__current" aria-hidden="true" />
        </NuxtLink>
      </nav>

      <div class="sidebar-footer">
        <span class="sidebar-footer__mark" aria-hidden="true"><i class="pi pi-map-marker" /></span>
        <span>
          <strong>Городская инфраструктура</strong>
          <small>Наблюдения и статусы объектов</small>
        </span>
      </div>
    </aside>

    <div class="workspace">
      <header class="workspace-topbar">
        <Button
          class="mobile-menu-toggle"
          icon="pi pi-bars"
          text
          rounded
          aria-label="Открыть меню"
          :aria-expanded="menuOpen"
          @click="menuOpen = !menuOpen"
        />
        <div class="topbar-heading">
          <span class="topbar-heading__eyebrow">МГТС / МОНИТОРИНГ</span>
          <h1>{{ pageTitle }}</h1>
        </div>
        <Button
          label="Выйти"
          icon="pi pi-sign-out"
          severity="secondary"
          outlined
          class="logout-button"
          @click="logout"
        />
      </header>

      <main class="workspace-content">
        <slot />
      </main>
    </div>
  </div>
</template>
