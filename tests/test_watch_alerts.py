"""Which stories reach a reader, and how each is labelled. No mail is sent."""
import time

from lyra.watch import alerts, trust


def story(title, source="Reuters", ts=None, **kw):
    ts = ts or time.time()
    return {"title": title, "source": source, "ts": ts, "published": ts, "url": "https://example.com/" + source,
            "kind": "news", "people": [], "companies": [], "topics": [], "moves": [], **kw}


def test_topic_needs_a_whole_word():
    assert alerts.matched_topic(story("Nvidia supplier reports fire"), ["nvidia"]) == "nvidia"
    assert alerts.matched_topic(story("Tesla's rival"), ["Tes"]) is None


def test_big_news_needs_a_move_and_a_known_person():
    known = [{"name": "A", "popularity": {"score": 80}}]
    assert alerts.is_big(story("x", moves=["Deal"], people=known))
    assert not alerts.is_big(story("x", people=known))
    assert not alerts.is_big(story("x", moves=["Deal"], people=[{"name": "A", "popularity": {"score": 10}}]))


def test_x_posts_and_old_stories_are_never_sent():
    old = story("Nvidia old", ts=time.time()); old["published"] = old["ts"] - 3 * 86400
    assert alerts.select([story("Nvidia post", x=True), old], False, ["Nvidia"]) == []


def test_three_outlets_confirm():
    group = [story("Nvidia supplier fire halts plant", s) for s in ("Reuters", "BBC", "AP")]
    t = trust.assess(group[0], group)
    assert t["label"] == "confirmed" and t["sources"] == 3


def test_rumour_wording():
    assert trust.assess(story("Apple reportedly weighing deal"), [])["label"] == "rumour"


def test_email_escapes_headlines():
    _, _, body = alerts.render([(story("<script>x</script>"), "Big news")], "https://u", "https://s")
    assert "<script>" not in body
