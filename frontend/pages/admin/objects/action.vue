<script setup lang="ts">
import {useRoute} from "#vue-router";
import {useRequest} from "~/services/useRequest";

definePageMeta({
  name: 'objects-action',
  layout: 'admin'
})

const MAX_PHOTO_SIZE = 5 * 1024 * 1024
const ALLOWED_PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const ALLOWED_PHOTO_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']

const PROCESSING_LABELS: Record<string, string> = {
  pending: 'Ожидает обработки',
  processing: 'Обрабатывается',
  done: 'Обработано',
  failed: 'Ошибка обработки'
}

const $router = useRouter()
const $route = useRoute()

const id = computed(() => $route.query?.id)

const isUpdateMode = computed(() => !!id.value)

const fields = ref<Record<string, any>>({})
const statuses = ref<Record<string, any>[]>([])
const loading = ref(false)
const saving = ref(false)
const formError = ref('')

const photoInput = ref<HTMLInputElement | null>(null)
const photoFile = ref<File | null>(null)
const photoPreview = ref<string | null>(null)
const photoRemoved = ref(false)
// Прибавляется после загрузки нового фото, чтобы <img> не показал старую версию из кэша.
const photoVersion = ref(0)

const hasSavedPhoto = computed(() => !!fields.value?.img_url)

const photoUrl = computed(() => {
  const url = fields.value?.img_url

  if (!url) return null
  if (!photoVersion.value) return url

  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}v=${photoVersion.value}`
})

const previewUrl = computed(() => photoPreview.value || photoUrl.value)

const processedPhotoUrl = computed(() => fields.value?.processed_img_url || null)

const processingLabel = computed(() => {
  const status = fields.value?.processing_status
  return status ? (PROCESSING_LABELS[status] || status) : ''
})

const processingError = computed(() => fields.value?.processing_error || '')

function releasePreview() {
  if (photoPreview.value) {
    URL.revokeObjectURL(photoPreview.value)
    photoPreview.value = null
  }
}

function onPhotoSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null

  formError.value = ''

  if (!file) return

  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  const isAllowedType = ALLOWED_PHOTO_TYPES.includes(file.type)
    || ALLOWED_PHOTO_EXTENSIONS.includes(extension)

  if (!isAllowedType) {
    formError.value = 'Допустимы только изображения JPEG, PNG и WebP.'
    input.value = ''
    return
  }

  if (file.size > MAX_PHOTO_SIZE) {
    formError.value = 'Максимальный размер фото — 5 МБ.'
    input.value = ''
    return
  }

  releasePreview()
  photoFile.value = file
  photoPreview.value = URL.createObjectURL(file)
  photoRemoved.value = false
}

function markPhotoForRemoval() {
  releasePreview()
  photoFile.value = null
  photoRemoved.value = true

  if (photoInput.value) {
    photoInput.value.value = ''
  }
}

function cancelPhotoRemoval() {
  photoRemoved.value = false
}

async function getStatuses() {
  const response = await useRequest('/api/statuses')

  if (!response.error && Array.isArray(response.data)) {
    statuses.value = response.data
  }
}

async function getData() {
  loading.value = true

  try {
    const response = await useRequest(`/api/infrastructure-objects/${id.value}`)

    if (!!response.error) {
      await $router.push("/admin/objects");
      return;
    }

    fields.value = response.data || {}
  } finally {
    loading.value = false
  }
}

function buildPayload() {
  // В PUT отправляем только поля, которые принимает бэкенд.
  const source = fields.value || {}

  return {
    type: source.type,
    external_id: source.external_id,
    place: source.place,
    lat: source.lat,
    lon: source.lon,
    status_id: source.status_id,
  }
}

async function uploadPhoto(objectId: string | number) {
  if (!photoFile.value) return null

  const formData = new FormData()
  formData.append('file', photoFile.value)

  return useRequest(`/api/infrastructure-objects/${objectId}/photo`, {
    method: 'POST',
    body: formData,
  })
}

async function sendData() {
  if (saving.value) return

  saving.value = true
  formError.value = ''

  try {
    const payload = buildPayload()

    const result = isUpdateMode.value
      ? await useRequest(`/api/infrastructure-objects/${id.value}`, {
        method: 'PUT',
        body: payload
      })
      : await useRequest(`/api/infrastructure-objects`, {
        method: 'POST',
        body: payload
      })

    if (!!result.error) {
      formError.value = [result.error.title, result.error.description]
        .filter(Boolean)
        .join('. ')
      return
    }

    const saved = result.data || {}
    const savedId = saved.id || id.value

    if (!savedId) {
      formError.value = 'Объект сохранён, но сервер не вернул его ID.'
      return
    }

    if (photoFile.value) {
      const uploadResult = await uploadPhoto(savedId)

      if (!!uploadResult?.error) {
        // Объект уже сохранён — переводим форму в режим редактирования,
        // чтобы фото можно было прикрепить повторно.
        fields.value = {...saved, ...(uploadResult.data || {})}
        if (!isUpdateMode.value) {
          await $router.replace({path: '/admin/objects/action', query: {id: savedId}})
        }
        formError.value = `Объект сохранён, но фото загрузить не удалось: ${uploadResult.error.title}. ${uploadResult.error.description || ''}`.trim()
        return
      }

      photoFile.value = null
      releasePreview()
      photoRemoved.value = false
      photoVersion.value = Date.now()
      fields.value = {...saved, ...(uploadResult?.data || {})}
    } else if (photoRemoved.value && hasSavedPhoto.value) {
      const removeResult = await useRequest(`/api/infrastructure-objects/${savedId}/photo`, {
        method: 'DELETE',
      })

      if (!!removeResult.error) {
        if (!isUpdateMode.value) {
          await $router.replace({path: '/admin/objects/action', query: {id: savedId}})
        }
        formError.value = `Объект сохранён, но фото удалить не удалось: ${removeResult.error.title}. ${removeResult.error.description || ''}`.trim()
        return
      }

      photoRemoved.value = false
      fields.value = {...saved, ...(removeResult.data || {}), img_url: null, processed_img_url: null}
    }

    await $router.push("/admin/objects");
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  getStatuses()

  if (isUpdateMode.value) {
    getData()
  }
})

onBeforeUnmount(() => {
  releasePreview()
})
</script>

<template>
  <form class="action-table" @submit.prevent="sendData">
    <h1 class="action-table__title">{{
        isUpdateMode ? `Редактирование объекта ID ${fields.id || id}` : 'Добавить объект'
      }}</h1>

    <p v-if="loading" class="action-table__hint">Загрузка данных объекта…</p>

    <input class="action-table__input" type="text" placeholder="Тип объекта" v-model="fields.type" required/>
    <input class="action-table__input" type="text" placeholder="Внешний идентификатор" v-model="fields.external_id"/>
    <input class="action-table__input" type="text" placeholder="Место" v-model="fields.place"/>
    <input class="action-table__input" type="text" placeholder="Широта" v-model="fields.lat"/>
    <input class="action-table__input" type="text" placeholder="Долгота" v-model="fields.lon"/>

    <select v-if="statuses.length" class="action-table__input" v-model="fields.status_id">
      <option :value="null">Статус не выбран</option>
      <option v-for="status in statuses" :key="`status_${status.id}`" :value="status.id">
        {{ status.type }}{{ status.description ? ` — ${status.description}` : '' }}
      </option>
    </select>
    <input v-else class="action-table__input" type="text" placeholder="ID статуса" v-model="fields.status_id"/>

    <section class="action-table__photo">
      <h2 class="action-table__photo-title">Фото объекта</h2>
      <p class="action-table__hint">
        JPEG, PNG или WebP, не больше 5 МБ. Одно фото на объект — новое заменит предыдущее.
      </p>

      <div v-if="previewUrl" class="action-table__photo-preview">
        <img :src="previewUrl" alt="Фото объекта"/>
      </div>
      <p v-else class="action-table__photo-empty">Фото не загружено</p>

      <div class="action-table__photo-actions">
        <label class="action-table__input-file-label" for="object-photo">
          {{ previewUrl ? 'Выбрать другое фото' : 'Прикрепить фото' }}
        </label>
        <input
          id="object-photo"
          ref="photoInput"
          class="action-table__input-file"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          @change="onPhotoSelected"
        />

        <button
          v-if="previewUrl && !photoRemoved"
          type="button"
          class="action-table__remove-button"
          @click="markPhotoForRemoval"
        >
          Удалить фото
        </button>

        <button
          v-else-if="photoRemoved && hasSavedPhoto"
          type="button"
          class="action-table__remove-button"
          @click="cancelPhotoRemoval"
        >
          Отменить удаление
        </button>
      </div>

      <p v-if="photoFile" class="action-table__hint">Выбрано: {{ photoFile.name }}</p>
      <p v-if="photoRemoved && hasSavedPhoto" class="action-table__hint">
        Фото будет удалено после сохранения объекта.
      </p>

      <p v-if="processingLabel" class="action-table__hint">
        Статус обработки: {{ processingLabel }}
      </p>
      <p v-if="processingError" class="action-table__error">
        Ошибка обработки: {{ processingError }}
      </p>

      <div v-if="processedPhotoUrl" class="action-table__photo-processed">
        <span class="action-table__hint">Результат обработки ИИ</span>
        <a :href="processedPhotoUrl" target="_blank" rel="noopener">
          <img :src="processedPhotoUrl" alt="Результат обработки ИИ"/>
        </a>
      </div>
    </section>

    <p v-if="formError" class="action-table__error">{{ formError }}</p>

    <button type="submit" class="add-button" :disabled="saving || loading">
      {{ saving ? 'Сохранение…' : (isUpdateMode ? 'Сохранить' : 'Добавить') }}
    </button>
  </form>
</template>

<style scoped lang="scss">
.action-table {
  &__photo {
    width: 100%;
    border-top: 1px solid #E3E3E3;
    margin: 10px 0 20px;
    padding-top: 20px;
  }

  &__photo-title {
    color: #0D47A1;
    font-size: 16px;
    font-weight: 600;
    margin: 0 0 6px;
  }

  &__photo-preview,
  &__photo-processed {
    img {
      display: block;
      width: 100%;
      max-width: 320px;
      max-height: 240px;
      object-fit: contain;
      border-radius: 8px;
      border: 1px solid #E4E4E4;
      background: #F7F7F9;
    }
  }

  &__photo-processed {
    margin-top: 16px;

    a {
      display: inline-block;
      margin-top: 6px;
    }
  }

  &__photo-empty {
    color: #B0B0B0;
    font-size: 14px;
    margin: 0 0 14px;
  }

  &__photo-actions {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
  }

  &__remove-button {
    border: 1px solid #D32F2F;
    border-radius: 5px;
    background: transparent;
    color: #D32F2F;
    padding: 9px 15px;
    font-size: 14px;
    transition: all .25s ease;

    &:hover {
      background: #D32F2F;
      color: #FFF;
    }
  }

  &__hint {
    color: #7A7A7A;
    font-size: 13px;
    line-height: 1.4;
    margin: 0 0 10px;
  }

  &__error {
    width: 100%;
    color: #D32F2F;
    background: #FDECEC;
    border-radius: 5px;
    padding: 10px 12px;
    font-size: 14px;
    line-height: 1.4;
    margin: 10px 0 15px;
  }
}
.add-button:disabled {
  opacity: .6;
  cursor: default;
}
</style>
