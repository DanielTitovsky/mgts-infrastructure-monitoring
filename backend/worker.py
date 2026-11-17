import logging
import time
from polars._utils import logging

def status_code(db, photo_record, ai_model):
    photo_id = photo_record['id']
    try:
        # Тут сделаем переменную загрузки из бд

        logging.info(f'Скачиваю фото {photo_id}')

        logging.info(f'Обработка фото ИИ:{photo_id} ')

        # Тут переменная будет обновления и выгрузка

    except Exception as e:
        logging.error(f'Ошибка в обработке фото {photo_id}')

def run_worker():
    db = DatabasseClient() # наша бдшка
    ai_model = 'ml/runs/detect/train/weights/1-version.pt'

    while True:
        # get_photo = фотки из бдшки
        if not get_photo:
            time.sleep(5) # если новых фоток нет то, чтобы мы не грузили сервак, воркер уходит в сон на 5 секунды(там определимся)
            continue

        for photo in get_photo: # этот цикл будет перебирать полученные фотки
            status_code(db, photo, ai_model)

if __name__ == '__worker__':

    run_worker()

