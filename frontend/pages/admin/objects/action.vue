<script setup lang="ts">
import {useRoute} from "#vue-router";
import {useRequest} from "~/services/useRequest";
import {useNotifications} from "~/composables/useNotifications";

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
const notifications = useNotifications()

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
// Оверлей на всю страницу показываем только во время перетаскивания файла.
const isDragging = ref(false)
const dragDepth = ref(0)
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

// Общая проверка файла — используется и для выбора через диалог, и для drag-and-drop.
function acceptPhotoFile(file: File) {
  formError.value = ''

  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  const isAllowedType = ALLOWED_PHOTO_TYPES.includes(file.type)
    || ALLOWED_PHOTO_EXTENSIONS.includes(extension)

  if (!isAllowedType) {
    formError.value = 'Допустимы только изображения JPEG, PNG и WebP.'
    notifications.error(formError.value, 'Неподдерживаемый файл')
    if (photoInput.value) photoInput.value.value = ''
    return
  }

  if (file.size > MAX_PHOTO_SIZE) {
    formError.value = 'Максимальный размер фото — 5 МБ.'
    notifications.error(formError.value, 'Слишком большой файл')
    if (photoInput.value) photoInput.value.value = ''
    return
  }

  releasePreview()
  photoFile.value = file
  photoPreview.value = URL.createObjectURL(file)
  photoRemoved.value = false
}

function onPhotoSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null

  if (!file) return

  acceptPhotoFile(file)
}

function openFileDialog() {
  photoInput.value?.click()
}

function hasDraggedFiles(event: DragEvent) {
  return !!event.dataTransfer?.types.includes('Files')
}

// Слушатели висят на window: файл можно бросить в любое место страницы.
// Счётчик нужен, чтобы оверлей не мигал при переходе между элементами.
function onWindowDragEnter(event: DragEvent) {
  if (!hasDraggedFiles(event)) return

  event.preventDefault()
  dragDepth.value += 1
  isDragging.value = true
}

function onWindowDragOver(event: DragEvent) {
  if (!hasDraggedFiles(event)) return

  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
  isDragging.value = true
}

function onWindowDragLeave(event: DragEvent) {
  if (!isDragging.value) return

  dragDepth.value = Math.max(0, dragDepth.value - 1)
  if (dragDepth.value === 0 || !event.relatedTarget) {
    dragDepth.value = 0
    isDragging.value = false
  }
}

function onWindowDrop(event: DragEvent) {
  event.preventDefault()
  dragDepth.value = 0
  isDragging.value = false

  const file = event.dataTransfer?.files?.[0]
  if (file) acceptPhotoFile(file)
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
    successMessage: 'Фото загружено',
    errorTitle: 'Не удалось загрузить фото',
  })
}

async function sendData() {
  if (saving.value) return

  saving.value = true
  formError.value = ''

  try {
    const payload = buildPayload()
    // Если вместе с объектом сохраняется фото, итоговый тост покажет
    // результат загрузки/удаления фото, чтобы не было двух «успехов» подряд.
    const saveSuccessMessage = (photoFile.value || photoRemoved.value)
      ? false
      : (isUpdateMode.value ? 'Объект сохранён' : 'Объект создан')

    const result = isUpdateMode.value
      ? await useRequest(`/api/infrastructure-objects/${id.value}`, {
        method: 'PUT',
        body: payload,
        successMessage: saveSuccessMessage,
        errorTitle: 'Не удалось сохранить объект',
      })
      : await useRequest(`/api/infrastructure-objects`, {
        method: 'POST',
        body: payload,
        successMessage: saveSuccessMessage,
        errorTitle: 'Не удалось создать объект',
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
        successMessage: 'Фото удалено',
        errorTitle: 'Не удалось удалить фото',
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

  window.addEventListener('dragenter', onWindowDragEnter)
  window.addEventListener('dragover', onWindowDragOver)
  window.addEventListener('dragleave', onWindowDragLeave)
  window.addEventListener('drop', onWindowDrop)
})

onBeforeUnmount(() => {
  releasePreview()

  window.removeEventListener('dragenter', onWindowDragEnter)
  window.removeEventListener('dragover', onWindowDragOver)
  window.removeEventListener('dragleave', onWindowDragLeave)
  window.removeEventListener('drop', onWindowDrop)
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
        Файл можно перетащить в любое место страницы.
      </p>

      <div v-if="previewUrl" class="action-table__photo-content">
        <img class="action-table__photo-image" :src="previewUrl" alt="Фото объекта"/>
        <div class="action-table__photo-actions">
          <button type="button" class="action-table__photo-button" @click="openFileDialog">
            Выбрать другое фото
          </button>
          <button
            v-if="!photoRemoved"
            type="button"
            class="action-table__photo-button"
            @click="markPhotoForRemoval"
          >
            Удалить фото
          </button>
          <button
            v-else-if="hasSavedPhoto"
            type="button"
            class="action-table__photo-button"
            @click="cancelPhotoRemoval"
          >
            Отменить удаление
          </button>
        </div>
      </div>

      <div v-else class="action-table__photo-actions">
        <span class="action-table__photo-empty">Фото не загружено</span>
        <button type="button" class="action-table__photo-button" @click="openFileDialog">
          Прикрепить фото
        </button>
      </div>

      <input
        id="object-photo"
        ref="photoInput"
        class="action-table__input-file"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        @change="onPhotoSelected"
      />

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

  <Teleport to="body">
    <div v-if="isDragging" class="photo-drop-overlay">
      <span class="photo-drop-overlay__plus">+</span>
      <span class="photo-drop-overlay__text">Отпустите файл, чтобы прикрепить фото</span>
    </div>
  </Teleport>
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

  &__photo-content,
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

  &__photo-content {
    display: inline-flex;
    flex-direction: column;
    align-items: flex-start;
    max-width: 320px;
  }

  &__photo-actions {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 10px;
  }

  // Единый стиль для «Выбрать другое фото», «Удалить фото» и «Прикрепить фото».
  &__photo-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 8px 12px;
    border: 1px solid rgba(255, 255, 255, .8);
    border-radius: 5px;
    background: linear-gradient(26deg, #0D47A1, #3e669a);
    color: #FFF;
    font-family: inherit;
    font-size: 13px;
    font-weight: 600;
    line-height: 1.2;
    white-space: nowrap;
    cursor: pointer;
    transition: opacity .2s ease;

    &:hover {
      opacity: .85;
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
    display: block;
    color: #7A7A7A;
    font-size: 14px;
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

// Полупрозрачный синий оверлей появляется только во время перетаскивания файла
// над любой точкой страницы. pointer-events: none — чтобы drop доходил до window.
.photo-drop-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  background: rgba(13, 71, 161, .55);
  color: #FFF;
  pointer-events: none;

  &__plus {
    font-size: 140px;
    font-weight: 200;
    line-height: 1;
  }

  &__text {
    font-size: 18px;
    font-weight: 600;
  }
}
</style>
