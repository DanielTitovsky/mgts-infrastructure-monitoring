<script setup lang="ts">
definePageMeta({
  layout: "default"
})


const $router = useRouter()

onMounted(async () => {
  $router.push("/admin")
})
</script>

<template>
</template>

<style scoped lang="scss">
pre {
  padding: 15px;
  background: #f5f5f5;
  font-family: monospace;
  margin-bottom: 25px;
  border-radius: 8px;
  width: 100%;
  overflow-x: auto;
}
</style>
