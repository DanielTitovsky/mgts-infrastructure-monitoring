<script setup lang="ts">
definePageMeta({
  name: 'map',
  layout: 'admin'
})
</script>

<template>
  <div class="all-table">
    <h1 class="title">Карта</h1>
    <p class="map-placeholder">
      Раздел карты будет подключён после выбора провайдера подложки (Leaflet или Яндекс.Карты).
      На карте отображаются результаты с доступной локацией, а записи без координат остаются в таблице.
    </p>
  </div>
</template>

<style scoped>
.map-placeholder {
  color: #565656;
  font-size: 14px;
  max-width: 640px;
  line-height: 1.5;
}
</style>
