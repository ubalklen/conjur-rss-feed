import argparse
import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://www.conjur.com.br"
TAG_URL_TEMPLATE = BASE_URL + "/tag/{tag}/"
OUTPUT_DIR = "public"
DEFAULT_MAX_PAGES = 3
REQUEST_TIMEOUT = 30
USER_AGENT = "ConjurRSSBot/1.0 (+https://github.com/conjur-rss-feed)"

MONTHS_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


@dataclass
class Article:
    title: str
    url: str
    authors: list[str]
    category: str
    published: datetime | None = None
    image_url: str | None = None


def parse_pt_date(text: str) -> datetime | None:
    match = re.search(
        r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})\s+às\s+(\d{2}):(\d{2})",
        text,
    )
    if not match:
        return None
    day, month_name, year, hour, minute = match.groups()
    month = MONTHS_PT.get(month_name.lower())
    if not month:
        return None
    return datetime(int(year), month, int(day), int(hour), int(minute), tzinfo=UTC)


def load_tags_from_file(filepath: str) -> list[str]:
    try:
        with open(filepath) as f:
            tags = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        logger.info(f"Loaded {len(tags)} tags from {filepath}")
        return tags
    except FileNotFoundError:
        logger.error(f"Tags file not found: {filepath}")
        return []
    except Exception as e:
        logger.error(f"Error loading tags from {filepath}: {e}")
        return []


def load_tags_from_env(env_var_name: str) -> list[str]:
    env_val = os.environ.get(env_var_name)
    if env_val:
        tags = [t.strip() for t in env_val.split(",") if t.strip()]
        logger.info(f"Loaded {len(tags)} tags from env var {env_var_name}")
        return tags
    logger.warning(f"Environment variable {env_var_name} not found or empty")
    return []


def parse_articles_from_html(html: str) -> list[Article]:
    soup = BeautifulSoup(html, "lxml")
    articles: list[Article] = []

    for article_el in soup.select("article.lines"):
        h2 = article_el.find("h2")
        if not h2:
            continue
        link = h2.find("a")
        if not link:
            continue

        title = link.get_text(strip=True)
        url = link.get("href", "")
        if not title or not url:
            continue
        if not url.startswith("http"):
            url = BASE_URL + url

        chapeu = article_el.select_one("span.chapeu")
        category = chapeu.get_text(strip=True) if chapeu else ""

        author_el = article_el.find("author")
        authors: list[str] = []
        if author_el:
            raw = author_el.get_text(strip=True).rstrip(" -").strip()
            if raw:
                authors = [a.strip() for a in raw.split(",") if a.strip()]

        time_el = article_el.find("time")
        published = None
        if time_el:
            published = parse_pt_date(time_el.get_text(strip=True))

        img = article_el.select_one("figure.thumb img")
        image_url = img.get("src") if img else None

        articles.append(
            Article(
                title=title,
                url=url,
                authors=authors,
                category=category,
                published=published,
                image_url=image_url,
            )
        )
        logger.debug(f"Parsed article: {title}")

    return articles


def get_total_pages_from_html(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    pagination = soup.select_one("nav.pagination")
    if not pagination:
        return 1
    page_links = pagination.select("a.page-numbers:not(.next)")
    max_page = 1
    for link in page_links:
        try:
            num = int(link.get_text(strip=True))
            if num > max_page:
                max_page = num
        except ValueError:
            continue
    return max_page


async def fetch_page(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        logger.debug(f"Fetching: {url}")
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching {url}: {e.response.status_code}")
        return None
    except httpx.RequestError as e:
        logger.error(f"Request error fetching {url}: {e}")
        return None


async def scrape_tag(
    client: httpx.AsyncClient, tag: str, max_pages: int = DEFAULT_MAX_PAGES
) -> list[Article]:
    base_url = TAG_URL_TEMPLATE.format(tag=tag)
    logger.info(f"Scraping tag: {tag}")

    first_page_html = await fetch_page(client, base_url)
    if not first_page_html:
        logger.warning(f"Failed to fetch first page for tag: {tag}")
        return []

    all_articles = parse_articles_from_html(first_page_html)
    total_pages = get_total_pages_from_html(first_page_html)
    pages_to_fetch = min(total_pages, max_pages)

    logger.info(f"Tag {tag}: found {total_pages} pages, will fetch {pages_to_fetch}")

    if pages_to_fetch > 1:
        tasks = [fetch_page(client, f"{base_url}page/{p}") for p in range(2, pages_to_fetch + 1)]
        results = await asyncio.gather(*tasks)

        for html in results:
            if html:
                all_articles.extend(parse_articles_from_html(html))

    seen_urls: set[str] = set()
    unique_articles: list[Article] = []
    for article in all_articles:
        if article.url not in seen_urls:
            seen_urls.add(article.url)
            unique_articles.append(article)

    logger.info(f"Tag {tag}: scraped {len(unique_articles)} unique articles")
    return unique_articles


async def scrape_all_tags(
    tags: list[str], max_pages: int = DEFAULT_MAX_PAGES
) -> dict[str, list[Article]]:
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        trust_env=False,
    ) as client:
        tasks = [scrape_tag(client, tag, max_pages) for tag in tags]
        results = await asyncio.gather(*tasks)
        return dict(zip(tags, results, strict=True))


def generate_feed_for_tag(tag: str, articles: list[Article], output_dir: str) -> str:
    fg = FeedGenerator()
    feed_url = f"{BASE_URL}/tag/{tag}/"

    fg.id(feed_url)
    fg.title(f"ConJur - {tag.upper().replace('-', ' ')}")
    fg.author({"name": "Consultor Jurídico"})
    fg.link(href=feed_url, rel="alternate")
    fg.link(href=f"{tag}.xml", rel="self")
    fg.subtitle(f"Últimas notícias sobre {tag.replace('-', ' ')} no Consultor Jurídico")
    fg.language("pt-BR")
    fg.lastBuildDate(datetime.now(UTC))

    for article in reversed(articles):
        fe = fg.add_entry()
        fe.id(article.url)
        fe.title(article.title)
        fe.link(href=article.url)

        if article.published:
            fe.published(article.published)
            fe.updated(article.published)

        description_parts = []
        if article.category:
            description_parts.append(f"[{article.category}]")
        if article.authors:
            description_parts.append(f"Por {', '.join(article.authors)}")
        fe.description(" - ".join(description_parts) if description_parts else article.title)

    output_path = os.path.join(output_dir, f"{tag}.xml")
    fg.rss_file(output_path)
    logger.info(f"Generated feed: {output_path} with {len(articles)} articles")
    return output_path


def generate_combined_feed(
    tag_articles: dict[str, list[Article]], output_dir: str, filename: str = "feed.xml"
) -> str:
    fg = FeedGenerator()
    fg.id(BASE_URL)
    fg.title("ConJur - Combined Feed")
    fg.author({"name": "Consultor Jurídico"})
    fg.link(href=BASE_URL, rel="alternate")
    fg.link(href=filename, rel="self")
    fg.subtitle("Últimas notícias de múltiplos temas no Consultor Jurídico")
    fg.language("pt-BR")
    fg.lastBuildDate(datetime.now(UTC))

    all_articles: list[tuple[str, Article]] = []
    for tag, articles in tag_articles.items():
        for article in articles:
            all_articles.append((tag, article))

    seen_urls: set[str] = set()
    unique_articles: list[tuple[str, Article]] = []
    for tag, article in all_articles:
        if article.url not in seen_urls:
            seen_urls.add(article.url)
            unique_articles.append((tag, article))

    for tag, article in reversed(unique_articles):
        fe = fg.add_entry()
        fe.id(article.url)
        fe.title(f"[{tag.upper()}] {article.title}")
        fe.link(href=article.url)

        if article.published:
            fe.published(article.published)
            fe.updated(article.published)

        description_parts = []
        if article.category:
            description_parts.append(f"[{article.category}]")
        if article.authors:
            description_parts.append(f"Por {', '.join(article.authors)}")
        fe.description(" - ".join(description_parts) if description_parts else article.title)

    output_path = os.path.join(output_dir, filename)
    fg.rss_file(output_path)
    logger.info(f"Generated combined feed: {output_path} with {len(unique_articles)} articles")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ConJur RSS Feed Generator")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--tags", nargs="+", help="List of tags to scrape")
    group.add_argument("--tags-file", help="Path to file with tags (one per line)")
    group.add_argument("--tags-env", help="Environment variable with comma-separated tags")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Output directory for feeds")
    parser.add_argument(
        "--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="Max pages to scrape per tag"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


async def async_main(tags: list[str], output_dir: str, max_pages: int) -> dict[str, list[Article]]:
    logger.info(f"Starting ConJur RSS feed generator with tags: {tags}")

    os.makedirs(output_dir, exist_ok=True)

    tag_articles = await scrape_all_tags(tags, max_pages)

    for tag, articles in tag_articles.items():
        if articles:
            generate_feed_for_tag(tag, articles, output_dir)
        else:
            logger.warning(f"No articles found for tag: {tag}")

    if any(tag_articles.values()):
        generate_combined_feed(tag_articles, output_dir)

    total_articles = sum(len(articles) for articles in tag_articles.values())
    logger.info(f"Done. Generated feeds for {len(tags)} tags, {total_articles} total articles")

    return tag_articles


def main():
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    tags: list[str] = []
    if args.tags:
        tags = args.tags
        logger.info(f"Using {len(tags)} tags from command line")
    elif args.tags_file:
        tags = load_tags_from_file(args.tags_file)
    elif args.tags_env:
        tags = load_tags_from_env(args.tags_env)

    if not tags:
        logger.error("No tags provided. Use --tags, --tags-file, or --tags-env")
        return

    asyncio.run(async_main(tags, args.output_dir, args.max_pages))


if __name__ == "__main__":
    main()
