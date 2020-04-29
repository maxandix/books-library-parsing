import requests
from requests.exceptions import ReadTimeout, ConnectionError
from urllib.parse import urljoin
from pathlib import Path
from os.path import join
from bs4 import BeautifulSoup
from pathvalidate import sanitize_filename
import json
import argparse
import logging
import time

BOOKS_DIR = 'books'
IMAGES_DIR = 'images'
logger = logging.getLogger(__name__)


class WrongContentType(Exception):
    pass


class PageWasRedirected(Exception):
    pass


def request_url(url):
    while True:
        try:
            response = requests.get(url, allow_redirects=False)
            response.raise_for_status()
            if response.is_redirect:
                raise PageWasRedirected()
            return response
        except ReadTimeout:
            logger.exception('Возник ReadTimeout.', exc_info=False)
        except ConnectionError:
            logger.exception('Возник ConnectionError. Проверте подключение.', exc_info=False)
            time.sleep(60)


def download_file(url, filename, content_type, folder=''):
    response = request_url(url)
    if content_type not in response.headers['Content-Type']:
        raise WrongContentType()
    file_path = join(folder, filename)
    with open(file_path, 'wb') as file:
        file.write(response.content)
    return file_path


def parse_book_page(book_id, page_url, args):
    response = request_url(page_url)
    soup = BeautifulSoup(response.text, 'lxml')

    content_title = soup.select_one('#content h1').text
    book_title, book_author = (item.strip() for item in content_title.split('::'))

    book_url = f'http://tululu.org/txt.php?id={book_id}'
    sanitized_filename = f'{book_id}. {sanitize_filename(book_title)}.txt'
    txt_path = None
    if not args.skip_txt:
        txt_path = download_file(book_url, sanitized_filename, 'text/plain', folder=join(args.dest_folder, BOOKS_DIR))

    image_url = urljoin(response.url, soup.select_one('#content .bookimage img')['src'])
    image_filename = image_url.split('/')[-1]
    if image_filename != 'nopic.gif':
        image_filename = f'{book_id}. {image_filename}'
    image_path = None
    if not args.skip_imgs:
        image_path = download_file(image_url, image_filename, 'image/', folder=join(args.dest_folder, IMAGES_DIR))

    comments = [comment.text for comment in soup.select('#content .texts .black')]
    genres = [genre.text for genre in soup.select('#content span.d_book a')]
    logger.warning(f'{page_url} Заголовок: {book_title}')

    return {
        'title': book_title,
        'author': book_author,
        'img_src': image_path,
        'book_path': txt_path,
        'comments': comments,
        'genres': genres,
    }


def create_parser():
    parser = argparse.ArgumentParser(description='Парсер онлайн-библиотеки tululu.org')
    parser.add_argument('--start_page', help='первая страница', type=int, default=1)
    parser.add_argument('--end_page', help='последняя страница (не включая)', type=int, default=702)
    parser.add_argument('--dest_folder', help='путь к каталогу с результатами парсинга: картинкам, книгами, JSON.', default='')
    parser.add_argument('--skip_imgs', help='не скачивать картинки', action='store_true')
    parser.add_argument('--skip_txt', help='не скачивать книги', action='store_true')
    parser.add_argument('--json_path', help='путь к *.json файлу с результатами', default='')
    return parser


def main():
    args = create_parser().parse_args()
    Path(join(args.dest_folder, BOOKS_DIR)).mkdir(parents=True, exist_ok=True)
    Path(join(args.dest_folder, IMAGES_DIR)).mkdir(parents=True, exist_ok=True)

    books_info = []
    for page_number in range(args.start_page, args.end_page):
        try:
            response = request_url(f'http://tululu.org/l55/{page_number}/')
        except PageWasRedirected:
            logger.exception(f'Страница {page_number} не существует', exc_info=False)

        soup = BeautifulSoup(response.text, 'lxml')
        for book_a in soup.select('#content .bookimage a'):
            book_id = [segment.strip('b') for segment in book_a['href'].split('/') if segment][-1]
            book_url = urljoin(response.url, book_a['href'])
            try:
                books_info.append(parse_book_page(book_id, book_url, args))
            except WrongContentType:
                logger.exception(f'Книга {book_url} не доступна для скачивания', exc_info=False)
            except PageWasRedirected:
                logger.exception(f'Книга {book_url} не существует', exc_info=False)

    json_path = args.json_path if args.json_path else args.dest_folder
    with open(join(json_path, 'books_info.json'), "w") as my_file:
        json.dump(books_info, my_file, ensure_ascii=False)


if __name__ == '__main__':
    main()
