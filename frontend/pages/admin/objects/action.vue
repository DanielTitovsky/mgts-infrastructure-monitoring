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
  awaiting_processing: 'Ожидает обработки',
  awating_processing: 'Ожидает обработки',
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
const statusOptions = computed(() => [
  { label: 'Статус не выбран', value: null },
  ...statuses.value.map(status => ({
    label: `${status.type}${status.description ? ` — ${status.description}` : ''}`,
    value: status.id,
  })),
])
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
// Прибавляется после загрузки нового фото, чтобы превью не показало старую версию из кэша.
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
  <form class="page-panel entity-form object-form" @submit.prevent="sendData">
    <div class="page-heading">
      <div>
        <p class="page-heading__eyebrow">РЕЕСТР ИНФРАСТРУКТУРЫ</p>
        <h2 class="page-heading__title">{{ isUpdateMode ? `Объект №${fields.id || id}` : 'Добавить объект' }}</h2>
      </div>
      <Button label="К списку" icon="pi pi-arrow-left" severity="secondary" outlined as="router-link" to="/admin/objects" />
    </div>

    <Message v-if="loading" severity="info" :closable="false">Загрузка данных объекта…</Message>
    <Message v-if="formError" severity="error" :closable="false">{{ formError }}</Message>

    <div class="entity-form__grid">
      <div class="form-field">
        <label for="object-type">Тип объекта</label>
        <InputText id="object-type" v-model="fields.type" required class="form-control" />
      </div>
      <div class="form-field">
        <label for="object-external-id">Внешний идентификатор</label>
        <InputText id="object-external-id" v-model="fields.external_id" class="form-control" />
      </div>
      <div class="form-field entity-form__wide">
        <label for="object-place">Место</label>
        <InputText id="object-place" v-model="fields.place" class="form-control" />
      </div>
      <div class="form-field">
        <label for="object-lat">Широта</label>
        <InputText id="object-lat" v-model="fields.lat" inputmode="decimal" class="form-control" />
      </div>
      <div class="form-field">
        <label for="object-lon">Долгота</label>
        <InputText id="object-lon" v-model="fields.lon" inputmode="decimal" class="form-control" />
      </div>
      <div class="form-field entity-form__wide">
        <label for="object-status">Статус</label>
        <Select
          v-if="statuses.length"
          input-id="object-status"
          v-model="fields.status_id"
          :options="statusOptions"
          option-label="label"
          option-value="value"
          placeholder="Выберите статус"
          class="form-control"
        />
        <InputText v-else id="object-status" v-model="fields.status_id" placeholder="ID статуса" class="form-control" />
      </div>
    </div>

    <section class="photo-section" aria-labelledby="object-photo-heading">
      <div class="photo-section__heading">
        <div>
          <p class="page-heading__eyebrow">ИЗОБРАЖЕНИЕ</p>
          <h3 id="object-photo-heading">Фото объекта</h3>
        </div>
        <Tag v-if="processingLabel" :value="processingLabel" :severity="fields.processing_status === 'failed' ? 'danger' : fields.processing_status === 'done' ? 'success' : 'warn'" />
      </div>
      <p class="photo-section__hint">
        JPEG, PNG или WebP, не больше 5 МБ. Одно фото на объект — новое заменит предыдущее.
        Файл можно перетащить в любое место страницы.
      </p>

      <div class="photo-workspace">
        <div v-if="previewUrl" class="photo-preview">
          <Image :src="previewUrl" alt="Фото объекта" image-class="photo-preview__image" preview />
          <div class="photo-preview__meta">
            <span>{{ photoFile ? 'Предпросмотр выбранного файла' : 'Текущее фото объекта' }}</span>
            <Tag v-if="photoRemoved" value="Будет удалено после сохранения" severity="warn" />
          </div>
        </div>
        <div v-else class="photo-empty">
          <span class="photo-empty__icon" aria-hidden="true"><i class="pi pi-image" /></span>
          <strong>Фото не загружено</strong>
          <span>Добавьте изображение, чтобы оно было связано с объектом.</span>
        </div>

        <div class="photo-controls">
          <Button
            :label="previewUrl ? 'Выбрать другое фото' : 'Прикрепить фото'"
            :icon="previewUrl ? 'pi pi-refresh' : 'pi pi-upload'"
            type="button"
            outlined
            @click="openFileDialog"
          />
          <Button
            v-if="previewUrl && !photoRemoved"
            label="Удалить фото"
            icon="pi pi-trash"
            type="button"
            severity="danger"
            text
            @click="markPhotoForRemoval"
          />
          <Button
            v-else-if="photoRemoved && hasSavedPhoto"
            label="Отменить удаление"
            icon="pi pi-undo"
            type="button"
            severity="secondary"
            text
            @click="cancelPhotoRemoval"
          />
          <input
            id="object-photo"
            ref="photoInput"
            class="visually-hidden-file-input"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            aria-label="Выберите фото объекта"
            @change="onPhotoSelected"
          />
          <span v-if="photoFile" class="photo-controls__filename">Выбрано: {{ photoFile.name }}</span>
        </div>
      </div>

      <Message v-if="processingError" severity="error" :closable="false" class="photo-processing-error">
        Ошибка обработки: {{ processingError }}
      </Message>

      <div v-if="processedPhotoUrl" class="processed-photo">
        <div>
          <p class="page-heading__eyebrow">РЕЗУЛЬТАТ ОБРАБОТКИ</p>
          <h4>Аннотированное изображение</h4>
        </div>
        <a :href="processedPhotoUrl" target="_blank" rel="noopener noreferrer" aria-label="Открыть аннотированное изображение">
          <Image :src="processedPhotoUrl" alt="Аннотированное изображение объекта" image-class="processed-photo__image" preview />
        </a>
      </div>
    </section>

    <div class="entity-form__actions">
      <Button type="submit" :label="saving ? 'Сохранение…' : (isUpdateMode ? 'Сохранить изменения' : 'Создать объект')" icon="pi pi-check" :loading="saving" :disabled="loading" />
    </div>
  </form>

  <Teleport to="body">
    <div v-if="isDragging" class="photo-drop-overlay" role="status">
      <span class="photo-drop-overlay__icon" aria-hidden="true"><i class="pi pi-cloud-upload" /></span>
      <span>Отпустите изображение, чтобы прикрепить фото</span>
    </div>
  </Teleport>
</template>

<style scoped lang="scss">
.object-form {
  max-width: 1100px;
}

.photo-section {
  width: 100%;
  margin-top: 32px;
  padding-top: 28px;
  border-top: 1px solid var(--line-color);
}

.photo-section__heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;

  h3 {
    margin-top: 6px;
    color: var(--text-strong);
    font-size: 1.05rem;
    font-weight: 650;
  }
}

.photo-section__hint {
  max-width: 760px;
  margin: 10px 0 22px;
  color: var(--text-muted);
  font-size: .875rem;
  line-height: 1.6;
}

.photo-workspace {
  display: grid;
  grid-template-columns: minmax(220px, 360px) minmax(220px, 1fr);
  align-items: start;
  gap: 24px;
}

.photo-preview,
.photo-empty {
  min-height: 220px;
  border: 1px solid var(--line-color);
  border-radius: 14px;
  background: var(--surface-soft);
  overflow: hidden;
}

.photo-preview {
  padding: 10px;
}

.photo-preview__image,
.processed-photo__image {
  display: block;
  width: 100%;
  max-height: 290px;
  object-fit: contain;
  border-radius: 8px;
}

.photo-preview__meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 12px 2px 2px;
  color: var(--text-muted);
  font-size: .8rem;
}

.photo-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  text-align: center;
  color: var(--text-muted);
  font-size: .84rem;
  line-height: 1.5;

  strong {
    color: var(--text-strong);
    font-size: .95rem;
  }
}

.photo-empty__icon,
.photo-drop-overlay__icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 14px;
  color: var(--primary-color);
  background: var(--primary-soft);
  font-size: 1.25rem;
}

.photo-controls {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}

.photo-controls__filename {
  color: var(--text-muted);
  font-size: .82rem;
  overflow-wrap: anywhere;
}

.photo-processing-error {
  margin-top: 18px;
}

.processed-photo {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) minmax(220px, 360px);
  align-items: start;
  gap: 24px;
  margin-top: 26px;
  padding-top: 24px;
  border-top: 1px solid var(--line-color);

  h4 {
    margin-top: 5px;
    color: var(--text-strong);
    font-size: .98rem;
  }
}

.processed-photo__image {
  max-height: 280px;
  border: 1px solid var(--line-color);
  background: var(--surface-soft);
}

.visually-hidden-file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  clip: rect(0, 0, 0, 0);
  overflow: hidden;
}

.photo-drop-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--text-strong);
  background: rgb(255 255 255 / 92%);
  border: 2px dashed var(--primary-color);
  pointer-events: none;
  font-size: 1.1rem;
  font-weight: 650;
}

@media (max-width: 680px) {
  .photo-workspace,
  .processed-photo {
    grid-template-columns: 1fr;
  }
}
</style>
