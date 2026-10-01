"""Plan usage from Claude Code's rate_limit_event: parsing, resets, and when to suggest saving."""
from maplehelper import usage
from maplehelper.i18n import I18n

EVENT = {"status": "allowed", "resetsAt": 2000, "rateLimitType": "five_hour",
         "unifiedWindows": {"five_hour": {"utilization": 0.7, "resetsAt": 2000},
                            "seven_day": {"utilization": 0.15, "resetsAt": 9000}}}


class FakeSettings(dict):
    def __getitem__(self, k):
        return self.get(k)


def test_parse_reads_both_windows():
    assert usage.parse(EVENT) == {"five_hour": {"used": 0.7, "resets": 2000},
                                  "seven_day": {"used": 0.15, "resets": 9000}}
    assert usage.parse(None) is None and usage.parse({"status": "allowed"}) is None


def test_levels_follow_the_five_hour_window():
    s = FakeSettings()
    usage.record(s, usage.parse(EVENT), now=1000)
    assert usage.level(s, now=1000) == "ok"
    s["usage"]["five_hour"]["used"] = 0.85
    assert usage.level(s, now=1000) == "high"
    s["usage"]["five_hour"]["used"] = 0.97
    assert usage.level(s, now=1000) == "critical"
    assert usage.level(s, now=2500) == "ok"          # the window reset since


def test_meter_lines():
    s = FakeSettings()
    assert usage.lines(s, I18n("en")) == [I18n("en")("usage_unknown")]
    usage.record(s, usage.parse(EVENT), now=1000)
    text = "\n".join(usage.lines(s, I18n("en"), now=1000))
    assert "70%" in text and "15%" in text


CODEX_SNAPSHOT = {"primary": {"usedPercent": 17, "windowDurationMins": 300, "resetsAt": 2000},
                  "secondary": {"usedPercent": 41, "windowDurationMins": 10080, "resetsAt": 9000}, "planType": "plus"}


def test_codex_usage_has_the_same_shape():
    assert usage.parse_codex(CODEX_SNAPSHOT) == {"five_hour": {"used": 0.17, "resets": 2000},
                                                 "seven_day": {"used": 0.41, "resets": 9000}}
    assert usage.parse_codex({"primary": None, "secondary": None}) is None and usage.parse_codex(None) is None


def test_usage_belongs_to_its_provider():
    s = FakeSettings()
    usage.record(s, usage.parse_codex(CODEX_SNAPSHOT), now=1000, provider="codex")
    assert usage.current(s, now=1000, provider="claude") == {}          # Claude's meter never shows ChatGPT's plan
    assert "17%" in "\n".join(usage.lines(s, I18n("en"), now=1000, provider="codex"))
    assert usage.lines(s, I18n("he"), now=1000, provider="claude") == [I18n("he")("usage_unknown")]


def test_codex_app_server_reply():
    from maplehelper.providers.codex import read_limits_reply
    lines = [b'{"id":1,"result":{}}\n', b'{"method":"remoteControl/status/changed","params":{}}\n',
             ('{"id":2,"result":{"rateLimits":%s}}\n' % __import__("json").dumps(CODEX_SNAPSHOT)).encode()]
    assert read_limits_reply(lines)["five_hour"]["used"] == 0.17
    signed_out = [b'{"error":{"code":-32600,"message":"codex account authentication required"},"id":2}\n']
    assert read_limits_reply(signed_out) is None
