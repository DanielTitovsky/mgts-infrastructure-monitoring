<script setup lang="ts">
import { isDemoModeEnabled } from '~/services/demoMode'

const runtimeConfig = useRuntimeConfig()
const demoMode = isDemoModeEnabled(runtimeConfig.public.demoMode)
</script>

<template>
  <div class="app-root">
    <div v-if="demoMode" class="demo-banner" role="status">
      <i class="pi pi-info-circle" aria-hidden="true" />
      <span>Демонстрация — синтетические данные, без реального ИИ. Запросы к backend отключены.</span>
    </div>
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </div>
</template>
