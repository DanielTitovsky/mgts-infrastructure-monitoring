<script setup lang="ts">
definePageMeta({
  name: 'map',
  layout: 'admin',
})
</script>

<template>
  <section class="page-panel map-placeholder">
    <div class="page-heading">
      <div>
        <p class="page-heading__eyebrow">РАСПОЛОЖЕНИЕ</p>
        <h2 class="page-heading__title">Карта</h2>
      </div>
    </div>

    <div class="map-placeholder__body">
      <span class="map-placeholder__icon" aria-hidden="true"><i class="pi pi-map" /></span>
      <h3>Карта пока не подключена</h3>
      <p>
        Провайдер картографической подложки ещё не выбран. Записи с доступными координатами
        остаются в списках объектов и дефектов; здесь не отображаются вымышленные точки.
      </p>
      <Button label="Открыть список дефектов" icon="pi pi-arrow-right" icon-pos="right" as="router-link" to="/admin/findings" />
    </div>
  </section>
</template>
