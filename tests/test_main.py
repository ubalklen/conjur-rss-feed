import os
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import httpx
import pytest

from src.main import (
    Article,
    async_main,
    fetch_page,
    generate_combined_feed,
    generate_feed_for_tag,
    get_total_pages_from_html,
    load_tags_from_env,
    load_tags_from_file,
    main,
    parse_args,
    parse_articles_from_html,
    parse_pt_date,
    scrape_all_tags,
    scrape_tag,
)

SAMPLE_ARTICLE_HTML = """
<article class="lines">
    <a href="https://www.conjur.com.br/2026-fev-02/lei-afasta-itcmd/">
        <figure class="thumb">
            <img src="https://www.conjur.com.br/img.jpg" alt="alt text">
        </figure>
    </a>
    <div class="text">
        <span class="hide-mobile chapeu">Tudo pela arrecadação</span>
        <h2><a href="https://www.conjur.com.br/2026-fev-02/lei-afasta-itcmd/">
            Lei afasta interpretação do Fisco
        </a></h2>
        <a href="https://www.conjur.com.br/2026-fev-02/lei-afasta-itcmd/">
            <author>José Higídio - </author>
            <time>2 de fevereiro de 2026 às 07:33</time>
        </a>
    </div>
</article>
"""

SAMPLE_PAGE_HTML = f"""
<html><body>
<section class="inner-content">
{SAMPLE_ARTICLE_HTML}
<article class="lines">
    <div class="text">
        <span class="hide-mobile chapeu">Opinião</span>
        <h2><a href="https://www.conjur.com.br/2026-jan-26/reforma-itcmd/">
            A reforma e os novos paradigmas do ITCMD
        </a></h2>
        <a href="https://www.conjur.com.br/2026-jan-26/reforma-itcmd/">
            <author>Victor Nunes - </author>
            <time>26 de janeiro de 2026 às 15:18</time>
        </a>
    </div>
</article>
</section>
<nav class="pagination">
    <span class="page-numbers current">1</span>
    <a class="page-numbers" href="/tag/itcmd/page/2">2</a>
    <a class="page-numbers" href="/tag/itcmd/page/3">3</a>
    <span class="page-numbers dots">…</span>
    <a class="page-numbers" href="/tag/itcmd/page/5">5</a>
    <a class="next page-numbers" href="/tag/itcmd/page/2">&gt;&gt;</a>
</nav>
</body></html>
"""


class TestParsePtDate:
    def test_parse_valid_date(self):
        dt = parse_pt_date("2 de fevereiro de 2026 às 07:33")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 2
        assert dt.day == 2
        assert dt.hour == 7
        assert dt.minute == 33

    def test_parse_date_different_month(self):
        dt = parse_pt_date("15 de setembro de 2025 às 19:36")
        assert dt is not None
        assert dt.month == 9
        assert dt.day == 15

    def test_parse_invalid_date(self):
        assert parse_pt_date("invalid") is None

    def test_parse_unknown_month(self):
        assert parse_pt_date("1 de invalidmonth de 2025 às 10:00") is None


class TestLoadTagsFromFile:
    def test_load_tags_success(self):
        mock_content = "itcmd\nreforma-tributaria\nstf\n"
        with patch("builtins.open", mock_open(read_data=mock_content)):
            tags = load_tags_from_file("tags.txt")
            assert len(tags) == 3
            assert "itcmd" in tags

    def test_load_tags_with_comments(self):
        mock_content = "itcmd\n# this is a comment\nstf\n"
        with patch("builtins.open", mock_open(read_data=mock_content)):
            tags = load_tags_from_file("tags.txt")
            assert len(tags) == 2

    def test_load_tags_with_empty_lines(self):
        mock_content = "itcmd\n\n\nstf\n\n"
        with patch("builtins.open", mock_open(read_data=mock_content)):
            tags = load_tags_from_file("tags.txt")
            assert len(tags) == 2

    def test_load_tags_file_not_found(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            assert load_tags_from_file("nonexistent.txt") == []

    def test_load_tags_permission_error(self):
        with patch("builtins.open", side_effect=PermissionError):
            assert load_tags_from_file("forbidden.txt") == []


class TestLoadTagsFromEnv:
    def test_load_tags_success(self):
        with patch.dict(os.environ, {"CONJUR_TAGS": "itcmd,reforma-tributaria,stf"}):
            tags = load_tags_from_env("CONJUR_TAGS")
            assert len(tags) == 3

    def test_load_tags_with_spaces(self):
        with patch.dict(os.environ, {"CONJUR_TAGS": "itcmd, reforma-tributaria , stf"}):
            tags = load_tags_from_env("CONJUR_TAGS")
            assert len(tags) == 3
            assert "reforma-tributaria" in tags

    def test_load_tags_not_found(self):
        with patch.dict(os.environ, {}, clear=True):
            assert load_tags_from_env("NONEXISTENT") == []

    def test_load_tags_empty(self):
        with patch.dict(os.environ, {"CONJUR_TAGS": ""}):
            assert load_tags_from_env("CONJUR_TAGS") == []


class TestParseArticlesFromHtml:
    def test_parse_articles(self):
        articles = parse_articles_from_html(SAMPLE_PAGE_HTML)
        assert len(articles) == 2

    def test_first_article_fields(self):
        articles = parse_articles_from_html(SAMPLE_PAGE_HTML)
        art = articles[0]
        assert "Fisco" in art.title
        assert art.url == "https://www.conjur.com.br/2026-fev-02/lei-afasta-itcmd/"
        assert art.category == "Tudo pela arrecadação"
        assert "José Higídio" in art.authors
        assert art.published is not None
        assert art.published.year == 2026
        assert art.image_url == "https://www.conjur.com.br/img.jpg"

    def test_empty_html(self):
        assert parse_articles_from_html("<html><body></body></html>") == []

    def test_article_without_h2(self):
        html = '<article class="lines"><div class="text"></div></article>'
        assert parse_articles_from_html(html) == []

    def test_article_with_relative_url(self):
        html = """
        <article class="lines">
            <div class="text">
                <h2><a href="/2026/some-article/">Title</a></h2>
            </div>
        </article>
        """
        articles = parse_articles_from_html(html)
        assert len(articles) == 1
        assert articles[0].url.startswith("https://www.conjur.com.br")


class TestGetTotalPagesFromHtml:
    def test_with_pagination(self):
        assert get_total_pages_from_html(SAMPLE_PAGE_HTML) == 5

    def test_single_page(self):
        html = "<html><body>No pagination</body></html>"
        assert get_total_pages_from_html(html) == 1

    def test_no_navigation(self):
        html = '<html><body><nav class="menu">not pagination</nav></body></html>'
        assert get_total_pages_from_html(html) == 1


class TestFetchPage:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_response = MagicMock()
        mock_response.text = "<html>content</html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_response

        result = await fetch_page(mock_client, "https://example.com")
        assert result == "<html>content</html>"

    @pytest.mark.asyncio
    async def test_http_error(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_response
        )
        mock_client.get.return_value = mock_response

        assert await fetch_page(mock_client, "https://example.com/404") is None

    @pytest.mark.asyncio
    async def test_request_error(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.RequestError("Connection failed")

        assert await fetch_page(mock_client, "https://example.com") is None


class TestScrapeTag:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock()
        mock_response.text = SAMPLE_PAGE_HTML
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        articles = await scrape_tag(mock_client, "itcmd", max_pages=1)
        assert len(articles) == 2

    @pytest.mark.asyncio
    async def test_first_page_fails(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.RequestError("Connection failed")

        assert await scrape_tag(mock_client, "itcmd") == []

    @pytest.mark.asyncio
    async def test_removes_duplicates(self):
        html = """
        <html><body>
        <article class="lines">
            <div class="text">
                <h2><a href="https://www.conjur.com.br/dup/">Dup</a></h2>
            </div>
        </article>
        <article class="lines">
            <div class="text">
                <h2><a href="https://www.conjur.com.br/dup/">Dup again</a></h2>
            </div>
        </article>
        </body></html>
        """
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        articles = await scrape_tag(mock_client, "itcmd", max_pages=1)
        assert len(articles) == 1


class TestScrapeAllTags:
    @pytest.mark.asyncio
    async def test_scrape_all(self):
        html = SAMPLE_PAGE_HTML
        with patch("src.main.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.text = html
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = await scrape_all_tags(["itcmd", "stf"], max_pages=1)
            assert "itcmd" in result
            assert "stf" in result


class TestGenerateFeed:
    def test_generate_feed_for_tag(self, tmp_path):
        articles = [
            Article(
                title="Test Article 1",
                url="https://www.conjur.com.br/article-1",
                authors=["Author 1"],
                category="TRIBUTOS",
            ),
            Article(
                title="Test Article 2",
                url="https://www.conjur.com.br/article-2",
                authors=["Author 2", "Author 3"],
                category="STF",
            ),
        ]

        output_path = generate_feed_for_tag("itcmd", articles, str(tmp_path))
        assert os.path.exists(output_path)
        assert output_path.endswith("itcmd.xml")

        with open(output_path) as f:
            content = f.read()
            assert "Test Article 1" in content
            assert "Test Article 2" in content

    def test_generate_feed_empty_articles(self, tmp_path):
        output_path = generate_feed_for_tag("empty", [], str(tmp_path))
        assert os.path.exists(output_path)

    def test_generate_combined_feed(self, tmp_path):
        tag_articles = {
            "itcmd": [
                Article(
                    title="ITCMD Article",
                    url="https://www.conjur.com.br/itcmd-1",
                    authors=["Author"],
                    category="TRIBUTOS",
                ),
            ],
            "stf": [
                Article(
                    title="STF Article",
                    url="https://www.conjur.com.br/stf-1",
                    authors=["Author"],
                    category="STF",
                ),
            ],
        }

        output_path = generate_combined_feed(tag_articles, str(tmp_path))
        assert os.path.exists(output_path)
        assert output_path.endswith("feed.xml")

        with open(output_path) as f:
            content = f.read()
            assert "[ITCMD]" in content
            assert "[STF]" in content

    def test_combined_feed_removes_duplicates(self, tmp_path):
        tag_articles = {
            "itcmd": [
                Article(
                    title="Shared",
                    url="https://www.conjur.com.br/shared",
                    authors=["Author"],
                    category="TRIBUTOS",
                ),
            ],
            "stf": [
                Article(
                    title="Shared",
                    url="https://www.conjur.com.br/shared",
                    authors=["Author"],
                    category="STF",
                ),
            ],
        }

        output_path = generate_combined_feed(tag_articles, str(tmp_path))
        with open(output_path) as f:
            content = f.read()
            assert content.count("<item>") == 1


class TestParseArgs:
    def test_parse_args_tags(self):
        with patch("sys.argv", ["main.py", "--tags", "itcmd", "stf"]):
            args = parse_args()
            assert args.tags == ["itcmd", "stf"]

    def test_parse_args_tags_file(self):
        with patch("sys.argv", ["main.py", "--tags-file", "tags.txt"]):
            args = parse_args()
            assert args.tags_file == "tags.txt"

    def test_parse_args_tags_env(self):
        with patch("sys.argv", ["main.py", "--tags-env", "CONJUR_TAGS"]):
            args = parse_args()
            assert args.tags_env == "CONJUR_TAGS"

    def test_parse_args_debug(self):
        with patch("sys.argv", ["main.py", "--tags", "itcmd", "--debug"]):
            args = parse_args()
            assert args.debug is True

    def test_parse_args_max_pages(self):
        with patch("sys.argv", ["main.py", "--tags", "itcmd", "--max-pages", "5"]):
            args = parse_args()
            assert args.max_pages == 5

    def test_parse_args_output_dir(self):
        with patch("sys.argv", ["main.py", "--tags", "itcmd", "--output-dir", "/tmp/feeds"]):
            args = parse_args()
            assert args.output_dir == "/tmp/feeds"


class TestAsyncMain:
    @pytest.mark.asyncio
    async def test_async_main(self, tmp_path):
        html = SAMPLE_PAGE_HTML
        with patch("src.main.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.text = html
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = await async_main(["itcmd"], str(tmp_path), max_pages=1)
            assert "itcmd" in result
            assert os.path.exists(os.path.join(str(tmp_path), "itcmd.xml"))
            assert os.path.exists(os.path.join(str(tmp_path), "feed.xml"))


class TestMain:
    def test_main_with_tags(self, tmp_path):
        with (
            patch("sys.argv", ["main.py", "--tags", "itcmd", "--output-dir", str(tmp_path)]),
            patch("src.main.asyncio.run") as mock_run,
        ):
            main()
            mock_run.assert_called_once()

    def test_main_no_tags(self):
        with patch("sys.argv", ["main.py"]):
            main()
