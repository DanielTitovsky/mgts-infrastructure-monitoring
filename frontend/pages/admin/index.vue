<script setup lang="ts">
import {useRequest} from "~/services/useRequest";

const $router = useRouter();

const login = ref()
const password = ref()

async function OnSubmitForm() {
  const request = await useRequest('/api/auth/login',{
    method:'POST',
    body: {
      username: login.value,
      password: password.value
    }
  })

  const cookieToken = useCookie('token');
  cookieToken.value = request.data.token;

  await $router.push("/admin/users");
}
</script>

<template>
<div class="container admin-page">
  <form class="form-auth" @submit.prevent="OnSubmitForm">
    <h1 class="form-auth__title">Вход в систему</h1>
    <input v-model="login" name="login" type="text" class="form-auth__input" placeholder="Имя пользователя" required>
    <input v-model="password" name="password" type="password" class="form-auth__input" placeholder="Пароль" required>
    <button class="form-auth__btn">Войти</button>
    <p class="form-auth__description">
      <span>Забыли пароль?</span><br>
      Обратитесь к администратору системы мониторинга.
    </p>
  </form>
</div>
</template>

<style scoped lang="scss">
.admin-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
