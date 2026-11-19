<script setup lang="ts">
import {useRequest} from "~/services/useRequest";

const $router = useRouter();
async function logout() {
  await useRequest('/api/logout', {
    successMessage: 'Вы вышли из системы',
    errorTitle: 'Не удалось выйти из системы'
  })

  // Токен живёт в cookie на клиенте — удаляем его и при ошибке API,
  // чтобы пользователь всё равно не остался в админке.
  useCookie('token').value = null
  await $router.push('/admin')
}
</script>
<template>
  <div>
    <div class="admin-page">
      <header class="admin-header">
        <nuxt-link to="/admin/users" class="admin-header__title">
          Мониторинг инфраструктуры МГТС
        </nuxt-link>
        <a href="#" @click.prevent="logout" class="admin-header__leave-button">Выйти</a>
      </header>
      <div class="content">
        <nav class="nav-bar">
          <ul class="nav-bar__panel">
            <li class="nav-bar__item">
              <nuxt-link to="/admin/users" class="nav-bar__link">
                <span class="nav-bar__icon">
                  <icon name="icon-user"/>
                </span>
                <span class="name">Пользователи</span>
              </nuxt-link>
            </li>
            <li class="nav-bar__item">
              <nuxt-link to="/admin/objects" class="nav-bar__link">
                <span class="nav-bar__icon">
                  <icon name="icon-object"/>
                </span>
                <span class="name">Объекты</span>
              </nuxt-link>
            </li>
            <li class="nav-bar__item">
              <nuxt-link to="/admin/findings" class="nav-bar__link">
                <span class="nav-bar__icon">
                  <icon name="icon-defect"/>
                </span>
                <span class="name">Дефекты</span>
              </nuxt-link>
            </li>
            <li class="nav-bar__item">
              <nuxt-link to="/admin/statuses" class="nav-bar__link">
                <span class="nav-bar__icon">
                  <icon name="icon-status"/>
                </span>
                <span class="name">Статусы</span>
              </nuxt-link>
            </li>
            <li class="nav-bar__item">
              <nuxt-link to="/admin/map" class="nav-bar__link">
                <span class="nav-bar__icon">
                  <icon name="icon-map"/>
                </span>
                <span class="name">Карта</span>
              </nuxt-link>
            </li>
          </ul>
          <footer>
            <p class="copyright">© 2026 Мониторинг инфраструктуры МГТС
              <br> Все права защищены</p>
          </footer>
        </nav>
        <main class="main">
          <slot/>
        </main>
      </div>
    </div>
  </div>
</template>
