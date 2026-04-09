#!/usr/bin/env python3
"""
Fetch yesterday's top HN posts from Algolia API and update the RSS feed.
Maintains a rolling 90-day window of posts.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom
import urllib.request
import urllib.parse

# Configuration
ALGOLIA_API_URL = "https://hn.algolia.com/api/v1/search"
MIN_POINTS = 100  # Minimum points for a post to be included
POSTS_PER_DAY = 5  # Maximum posts to fetch per day
RETENTION_DAYS = 30  # Keep posts for 30 days
FEED_DATA_FILE = "docs/feed_data.json"
RSS_FILE = "docs/feed.xml"


def get_yesterday_timestamps():
    """Get Unix timestamps for yesterday (UTC)."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today - timedelta(days=1)
    yesterday_end = today - timedelta(seconds=1)
    return int(yesterday_start.timestamp()), int(yesterday_end.timestamp())


def fetch_hn_posts(start_ts, end_ts):
    """Fetch top posts from Algolia HN API for the given time range."""
    params = {
        "tags": "story",
        "numericFilters": f"created_at_i>={start_ts},created_at_i<={end_ts},points>={MIN_POINTS}",
        "hitsPerPage": POSTS_PER_DAY,
    }
    url = f"{ALGOLIA_API_URL}?{urllib.parse.urlencode(params)}"

    print(f"Fetching posts from: {url}")

    req = urllib.request.Request(url, headers={"User-Agent": "HN-Daily-Reader/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    posts = []
    for hit in data.get("hits", []):
        post = {
            "id": hit["objectID"],
            "title": hit.get("title", "Untitled"),
            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
            "points": hit.get("points", 0),
            "author": hit.get("author", "unknown"),
            "created_at": hit.get("created_at_i", 0),
            "num_comments": hit.get("num_comments", 0),
            "hn_url": f"https://news.ycombinator.com/item?id={hit['objectID']}",
        }
        posts.append(post)

    # Sort by points descending
    posts.sort(key=lambda x: x["points"], reverse=True)
    return posts


def load_feed_data(filepath):
    """Load existing feed data from JSON file."""
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"posts": [], "last_updated": None}


def save_feed_data(filepath, data):
    """Save feed data to JSON file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def prune_old_posts(posts, days=RETENTION_DAYS):
    """Remove posts older than the retention period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ts = int(cutoff.timestamp())
    return [p for p in posts if p["created_at"] >= cutoff_ts]


def generate_rss(posts, output_file):
    """Generate RSS 2.0 feed from posts."""
    rss = ET.Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")

    channel = ET.SubElement(rss, "channel")

    # Channel metadata
    ET.SubElement(channel, "title").text = "HN Daily Top Posts"
    ET.SubElement(channel, "link").text = "https://news.ycombinator.com"
    ET.SubElement(channel, "description").text = "Daily curated top posts from Hacker News (auto-generated, last 90 days)"
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    # Add atom:link for self-reference (RSS best practice)
    atom_link = ET.SubElement(channel, "{http://www.w3.org/2005/Atom}link")
    atom_link.set("href", "https://code.patilla.es/hn-daily-reader/feed.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    # Sort posts by created_at descending (newest first)
    sorted_posts = sorted(posts, key=lambda x: x["created_at"], reverse=True)

    for post in sorted_posts:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"[{post['points']} pts] {post['title']}"
        ET.SubElement(item, "link").text = post["url"]

        # Description with metadata
        description = f"""
<p><strong>{post['points']} points</strong> by {post['author']} | <strong>{post['num_comments']} comments</strong></p>
<p><a href="{post['hn_url']}">View on Hacker News</a></p>
        """.strip()
        ET.SubElement(item, "description").text = description

        # Use HN URL as guid for uniqueness
        guid = ET.SubElement(item, "guid")
        guid.text = post["hn_url"]
        guid.set("isPermaLink", "true")

        # Publication date
        pub_date = datetime.fromtimestamp(post["created_at"], tz=timezone.utc)
        ET.SubElement(item, "pubDate").text = pub_date.strftime("%a, %d %b %Y %H:%M:%S +0000")

    # Pretty print XML
    xml_str = ET.tostring(rss, encoding="unicode")
    pretty_xml = minidom.parseString(xml_str).toprettyxml(indent="  ")
    # Remove extra blank lines and fix declaration
    lines = [line for line in pretty_xml.split("\n") if line.strip()]
    lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    print("=" * 60)
    print("HN Daily Reader - Fetching yesterday's top posts")
    print("=" * 60)

    # Get yesterday's time range
    start_ts, end_ts = get_yesterday_timestamps()
    yesterday = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    print(f"Fetching posts from: {yesterday.strftime('%Y-%m-%d')}")

    # Fetch new posts
    new_posts = fetch_hn_posts(start_ts, end_ts)
    print(f"Found {len(new_posts)} posts with >= {MIN_POINTS} points")

    # Load existing feed data
    feed_data = load_feed_data(FEED_DATA_FILE)
    existing_ids = {p["id"] for p in feed_data["posts"]}
    print(f"Existing feed has {len(feed_data['posts'])} posts")

    # Add new posts (avoid duplicates)
    added = 0
    for post in new_posts:
        if post["id"] not in existing_ids:
            feed_data["posts"].append(post)
            added += 1
            print(f"  + [{post['points']} pts] {post['title'][:50]}...")

    print(f"Added {added} new posts")

    # Prune old posts
    original_count = len(feed_data["posts"])
    feed_data["posts"] = prune_old_posts(feed_data["posts"])
    pruned = original_count - len(feed_data["posts"])
    if pruned > 0:
        print(f"Pruned {pruned} posts older than {RETENTION_DAYS} days")

    # Update metadata
    feed_data["last_updated"] = datetime.now(timezone.utc).isoformat()

    # Save feed data
    save_feed_data(FEED_DATA_FILE, feed_data)
    print(f"Saved feed data to {FEED_DATA_FILE}")

    # Generate RSS
    generate_rss(feed_data["posts"], RSS_FILE)
    print(f"Generated RSS feed at {RSS_FILE}")

    print("=" * 60)
    print(f"Feed now contains {len(feed_data['posts'])} posts")
    print("Done!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
