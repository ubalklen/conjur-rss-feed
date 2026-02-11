import os
import xml.etree.ElementTree as ET

from src.main import Article, generate_combined_feed, generate_feed_for_tag


class TestFeedOrdering:
    def test_newest_first_in_tag_feed(self, tmp_path):
        articles = [
            Article(
                title="Article from Jan 15 (newest)",
                url="https://www.conjur.com.br/article-3",
                authors=["Author 3"],
                category="TRIBUTOS",
            ),
            Article(
                title="Article from Jan 10 (middle)",
                url="https://www.conjur.com.br/article-2",
                authors=["Author 2"],
                category="TRIBUTOS",
            ),
            Article(
                title="Article from Jan 5 (oldest)",
                url="https://www.conjur.com.br/article-1",
                authors=["Author 1"],
                category="TRIBUTOS",
            ),
        ]

        output_path = generate_feed_for_tag("test-tag", articles, str(tmp_path))
        assert os.path.exists(output_path)

        tree = ET.parse(output_path)
        root = tree.getroot()
        items = root.findall(".//item/title")
        titles = [item.text for item in items]

        assert len(titles) == 3
        assert titles[0] == "Article from Jan 15 (newest)"
        assert titles[1] == "Article from Jan 10 (middle)"
        assert titles[2] == "Article from Jan 5 (oldest)"

    def test_newest_first_in_combined_feed(self, tmp_path):
        tag_articles = {
            "tag1": [
                Article(
                    title="Tag1 newest",
                    url="https://www.conjur.com.br/tag1-2",
                    authors=["Author"],
                    category="TRIBUTOS",
                ),
                Article(
                    title="Tag1 oldest",
                    url="https://www.conjur.com.br/tag1-1",
                    authors=["Author"],
                    category="TRIBUTOS",
                ),
            ],
            "tag2": [
                Article(
                    title="Tag2 newest",
                    url="https://www.conjur.com.br/tag2-2",
                    authors=["Author"],
                    category="STF",
                ),
                Article(
                    title="Tag2 oldest",
                    url="https://www.conjur.com.br/tag2-1",
                    authors=["Author"],
                    category="STF",
                ),
            ],
        }

        output_path = generate_combined_feed(tag_articles, str(tmp_path))
        assert os.path.exists(output_path)

        tree = ET.parse(output_path)
        root = tree.getroot()
        items = root.findall(".//item/title")
        titles = [item.text for item in items]

        assert len(titles) == 4
        tag1_newest_idx = next(i for i, t in enumerate(titles) if "Tag1 newest" in t)
        tag1_oldest_idx = next(i for i, t in enumerate(titles) if "Tag1 oldest" in t)
        tag2_newest_idx = next(i for i, t in enumerate(titles) if "Tag2 newest" in t)
        tag2_oldest_idx = next(i for i, t in enumerate(titles) if "Tag2 oldest" in t)

        assert tag1_newest_idx < tag1_oldest_idx
        assert tag2_newest_idx < tag2_oldest_idx

    def test_single_article(self, tmp_path):
        articles = [
            Article(
                title="Single Article",
                url="https://www.conjur.com.br/single",
                authors=["Author"],
                category="TRIBUTOS",
            ),
        ]

        output_path = generate_feed_for_tag("test-tag", articles, str(tmp_path))
        tree = ET.parse(output_path)
        root = tree.getroot()
        items = root.findall(".//item/title")
        assert len(items) == 1
        assert items[0].text == "Single Article"
