import json
import re
import subprocess
from datetime import datetime
import os
from openai import OpenAI
import piexif
import argparse
from urllib.parse import quote

valid_extensions = ('.jpg', '.jpeg')

api_key = 'ВАШ_КЛЮЧ'

your_site = 'ВАШ_САЙТ'
photo_dir = 'C:\\ПУТЬ\\К\\ФОТО'
tasks_path = "batch_tasks.jsonl"
results_path = "batch_tasks_output.jsonl"
job_id_path = "batch_job_id.txt"

description_length = 200
keywords_count = 50
prompt = f"Please create a description no more than {description_length} characters long for this image in stock style " \
         f"and a list of {keywords_count} popular single-word keywords, separated with commas. " \
         f"Tailor the description to a specific niche and target audience. "\
         f"Your keywords are to enhance searchability within that niche." \
         f"If there are architectural decoration elements in the image, be sure to include them. " \
         f"If there are inscriptions in a language other than English in the photo, include their translation in the description. " \
         f"Be sure to separate the description from the list of keywords with a newline character. " \
         f"Don't write anything except a description and a list of keywords. " \
         f"If there are any plants in the picture, identify their names and weave them into the description and the keywords list. " \
         f"Ensure no word is repeated. Be sure to include in both the description and in the keywords list the next words: "

batch_output_map = {}


def extract_date_taken(image_path):
    exif_dict = piexif.load(image_path)
    date_taken_str = exif_dict['Exif'].get(piexif.ExifIFD.DateTimeOriginal)

    if date_taken_str:
        try:
            date_taken = datetime.strptime(date_taken_str.decode('utf-8'), '%Y:%m:%d %H:%M:%S')
            return date_taken.year, date_taken.month, date_taken.day
        except ValueError:
            return None, None, None
    return None, None, None


def add_metadata(image_path: str, title, category, tags, month, day, year, country, city):
    if category == "editorial" and country and city and day and month and year:
        title = f"{city}, {country} - {month}.{day}.{year}: " + title

    try:
        # ExifTool для работы с метаданными IPTC
        commands = [
            'C:\\Program Files\\exiftool\\exiftool.exe',
            '-overwrite_original',
            f'-Headline={title}'
        ]
        if tags:
            for tag in tags:
                clean_tag = tag.replace('.', '').replace('\n', '').replace('\r', '')
                commands.append(f'-Keywords={clean_tag}')

        commands.append(image_path)
        subprocess.run(commands, check=True)

    except subprocess.CalledProcessError as e:
        print(f"Ошибка при выполнении ExifTool для файла {image_path}: {e}")
    except Exception as e:
        print(f"Непредвиденная ошибка при обработке файла {image_path}: {e}")


def make_tag_list(tags):
    if tags.endswith('.'):
        tags = tags[:-1]
    tags_list = tags.split(',')
    tags_list = [tag.strip() for tag in tags_list]
    return tags_list


def process_directory(root_path):
    global batch_output_map

    if not batch_output_map:
        print("Сначала загрузите результаты пакетной обработки!")
        return

    for root, dirs, files in os.walk(root_path):
        path_parts = root.split(os.sep)
        # Если у нас есть три уровня директорий и мы находимся в последней из них
        if len(path_parts) >= 3 and (path_parts[-1] == 'editorial' or path_parts[-1] == 'commercial'):
            country = path_parts[-3]  # третий с конца элемент в списке
            city = path_parts[-2]  # предпоследний элемент в списке
            category = path_parts[-1]  # последний элемент в списке

            print(f"Анализ папки {root}")
            for file in files:
                if file.lower().endswith(valid_extensions):
                    relative_file_path = os.path.join(os.path.relpath(root, root_path), file)
                    relative_file_path = relative_file_path.replace(os.sep, '/')
                    relative_file_path = f"photo/{relative_file_path}"
                    relative_file_path = quote(relative_file_path)

                    if not relative_file_path in batch_output_map:
                        print(f"Для {relative_file_path} не нашлось метаданных!!!")
                        continue

                    file_path = os.path.join(root, file)
                    year, month, day = extract_date_taken(file_path)

                    response = batch_output_map[relative_file_path].split("\n\n")
                    if len(response) < 2:
                        print("В ответе меньше 2 разделов!")
                    else:
                        default_title, tags = response[:2] # иногда нейросеть ставит лишние переносы строк после списка ключевых слов
                        add_metadata(file_path, default_title, category, make_tag_list(tags), month, day, year, country,
                                 city)
        else:
            print(f"{root} не commercial и не editorial, пропускаю его :-(")


def generate_tasks():
    with open(tasks_path, 'w') as file:
        task_index = 0
        for root, dirs, files in os.walk(photo_dir):
            path_parts = root.split(os.sep)
            # Если у нас есть три уровня директорий и мы находимся в последней из них
            if len(path_parts) >= 3 and path_parts[-1] in {'editorial', 'commercial'}:
                for filename in files:
                    if not filename.lower().endswith(valid_extensions):
                        continue
                    file_path = os.path.relpath(os.path.join(root, filename), photo_dir).replace('\\', '/')
                    image_url = f"{your_site}photo/{file_path}"
                    image_url = quote(image_url, safe=':/')

                    path_parts = re.split(r'[\\/]', file_path)
                    country, city = path_parts[0], path_parts[1] if len(path_parts) > 1 else (None, None)

                    new_prompt = f"{prompt} {country}, {city}" if country and city else prompt

                    task = {
                        "custom_id": f"task-{task_index}",
                        "method": "POST",
                        "url": "/v1/chat/completions",
                        "body": {
                            "model": "gpt-4o-mini",
                            "messages": [
                                {
                                    "role": "system",
                                    "content": new_prompt
                                },
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": image_url
                                            }
                                        },
                                    ],
                                }
                            ]
                        }
                    }

                    file.write(json.dumps(task) + '\n')
                    print(f"Добавили задание: {image_url}")
                    task_index += 1


def send_batch():
    client = OpenAI(
        api_key=api_key
    )

    batch_file = client.files.create(
        file=open(tasks_path, "rb"),
        purpose="batch"
    )
    batch_job = client.batches.create(
        input_file_id=batch_file.id,
        endpoint="/v1/chat/completions",
        completion_window="24h"
    )
    print(f"Создали пакетное задание с ID {batch_job.id}")

    with open(job_id_path, 'w') as f:
        f.write(batch_job.id)

    return batch_job.id


def try_get_results():
    client = OpenAI(
        api_key=api_key
    )

    with open(job_id_path, 'r') as f:
        batch_job_id = f.read().strip()

    batch_job = client.batches.retrieve(batch_job_id)
    print(f"Статус пакетного задания: {batch_job.status}")
    if batch_job.status == 'completed':
        result = client.files.content(batch_job.output_file_id).content
        with open(results_path, 'wb') as file:
            file.write(result)
        print(f"Результаты сохранены в файл {results_path}")
    else:
        print(batch_job)


def load_jsonl(filepath):
    with open(filepath, 'r', encoding='utf-8') as file:
        return [json.loads(line) for line in file]


def load_batch_output(tasks_file, outputs_file):
    global batch_output_map

    tasks_data = load_jsonl(tasks_file)
    outputs_data = load_jsonl(outputs_file)

    batch_output_map = {}

    tasks_index = {task['custom_id']: task for task in tasks_data}

    for output in outputs_data:
        custom_id = output.get('custom_id')
        if custom_id in tasks_index:
            task = tasks_index[custom_id]
            try:
                image_url = task['body']['messages'][1]['content'][0]['image_url']['url']
                image_url = image_url.replace(your_site, '', 1)
                content = output['response']['body']['choices'][0]['message']['content']
                batch_output_map[image_url] = content
            except (IndexError, KeyError, TypeError) as e:
                print(f'Ошибка обработки задачи {custom_id}: {e}')


# когда нейросеть отработала
def process_output():
    load_batch_output(tasks_path, results_path)
    process_directory(photo_dir)


if __name__ == '__main__':
    choices = {
        'generate_tasks': generate_tasks,
        'send_batch': send_batch,
        'try_get_results': try_get_results,
        'process_output': process_output
    }
    parser = argparse.ArgumentParser(description="Обработка шагов.")
    parser.add_argument('-s', '--step', choices=choices.keys(),
                        required=True, help="Выберите шаг для обработки")

    args = parser.parse_args()

    step_function = choices.get(args.step)
    if step_function:
        step_function()
    else:
        print(f"Неизвестный шаг. Введите одно из значений {', '.join(choices.keys())}")
