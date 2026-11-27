#!/usr/bin/env python3
"""Saves House and Senate roll call votes as permanent JSON files, works out
per-member statistics, and gradually collects each member's sponsored and
cosponsored legislation.

Run it on a schedule. Every run only adds what is new.

Layout (all under OUT_DIR, default "data"):
  congresses.json                          which Congresses/chambers exist
  house/119/index.json                     list of votes (newest first)
  house/119/votes/2-327.json               one file per vote (session-roll)
  house/119/matrix.json                    every member's vote on every roll call
  senate/119/...                           same for the Senate
  members/directory.json                   every member + per-Congress stats
  members/cache-119.json                   bioguide ID -> district/name/state
  legislation/B001323.json                 a member's sponsored/cosponsored bills

Environment variables:
  CONGRESS_API_KEY   (required)
  CONGRESSES         e.g. "118,119". Default: the current Congress, plus the previous one until 21 days after the new Congress begins.
  MAX_NEW            max new votes saved per chamber and Congress per run (default 400)
  TITLE_BUDGET       Max API requests for bill/amendment titles per run.
  LEG_BUDGET         max API requests spent on bills per run (default 1200)
  LEG_REFRESH_DAYS   re-fetch a member's bills after this many days (default 5)
  OUT_DIR            default "data"

To rebuild the member statistics from scratch, delete
data/*/*/matrix.json and data/members/directory.json and run again.
"""
import datetime
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API = "https://api.congress.gov/v3"
SENATE_BASE = "https://www.senate.gov/legislative/LIS/roll_call_votes"
OUT = os.environ.get("OUT_DIR", "data")
ATLARGE = {"AK", "DE", "ND", "SD", "VT", "WY"}
YES = {"yea", "aye", "yes", "guilty"}
NO = {"nay", "no", "not guilty"}
BIOGUIDE = re.compile(r"^[A-Z]\d{6}$")
STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL",
    "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA",
    "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "Puerto Rico": "PR", "Guam": "GU", "American Samoa": "AS", "Northern Mariana Islands": "MP",
    "Virgin Islands": "VI", "U.S. Virgin Islands": "VI",
}
REQS = 0
MEMBERS = {}
T0 = time.time()
STEP = {"n": 0, "of": 0}
SUMMARY = []


LAW_RE = re.compile(r"Became (Public|Private) Law No: ?([0-9]+-[0-9]+)", re.I)


def log(*a):
    print(*a, flush=True)


def elapsed():
    sec = int(time.time() - T0)
    return "%d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def step(title):
    """Announce the start of one of the run's tasks, with elapsed time and requests used so far."""
    STEP["n"] += 1
    log("")
    log("===== Step %d of %d: %s  [elapsed %s, %d API requests so far] =====" % (STEP["n"], STEP["of"], title, elapsed(), REQS))


def note(msg):
    """Log a result line and remember it for the summary at the end of the run."""
    log(msg)
    SUMMARY.append(msg)


# ---------------------------------------------------------------- HTTP
def get(path, **params):
    """One Congress.gov API request (JSON). Returns None on 404."""
    global REQS
    q = {"format": "json", "limit": 250, "api_key": os.environ["CONGRESS_API_KEY"]}
    q.update(params)
    url = API + path + "?" + urllib.parse.urlencode(q)
    for attempt in range(4):
        try:
            REQS += 1
            req = urllib.request.Request(url, headers={"User-Agent": "vote-archive"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429 or e.code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except Exception:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("Request failed: " + path)


def fetch_bytes(url):
    """Plain download (used for senate.gov). Returns None if the page does not exist."""
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vote-archive"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            if e.code == 429 or e.code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            return None
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None


def find_list(j, preferred):
    if not j:
        return []
    if isinstance(j.get(preferred), list):
        return j[preferred]
    for v in j.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


def paged(path, finder, keyfn, max_pages=20, single=False, quiet=False):
    """Fetch every page. Stops when a page is short, repeats itself, or adds nothing new.
    single=True makes just one request (the House vote-members endpoint returns everyone at once)."""
    items, seen, offset, first = [], set(), 0, None
    for _ in range(max_pages):
        if not quiet:
            log("  GET", path, "offset", offset)
        j = get(path, offset=offset)
        if first is None:
            first = j
        page = finder(j) if j else []
        new = [x for x in page if keyfn(x) not in seen]
        seen.update(keyfn(x) for x in new)
        items += new
        if single or len(page) < 250 or not new:
            break
        offset += 250
    return items, first


# ---------------------------------------------------------------- files
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def web(path):
    return path.replace(os.sep, "/")


def cdir(chamber, cg):
    return os.path.join(OUT, chamber, str(cg))


def vote_path(chamber, cg, session, roll):
    return os.path.join(cdir(chamber, cg), "votes", "%d-%d.json" % (session, roll))


def load_index(chamber, cg):
    return load_json(os.path.join(cdir(chamber, cg), "index.json"), [])


def save_index(chamber, cg, index):
    index.sort(key=lambda e: (e.get("date") or "", e["session"], e["roll"]), reverse=True)
    save_json(os.path.join(cdir(chamber, cg), "index.json"), index)


def current_congress(today=None):
    today = today or datetime.date.today()
    c = (today.year - 1789) // 2 + 1
    if today.year % 2 == 1 and (today.month, today.day) < (1, 3):
        c -= 1
    return c


def years_of(cg):
    start = 1789 + 2 * (cg - 1)
    return "%d–%d" % (start, start + 2)


# ---------------------------------------------------------------- tallies
def vkind(v):
    v = (v or "").strip().lower()
    if v in YES:
        return "Y"
    if v in NO:
        return "N"
    if v == "present":
        return "P"
    if v == "not voting":
        return "M"
    return None


def tally(rows):
    """Per-party YES/NO counts plus Present / Not Voting, for the list-page bars."""
    t = {"dY": 0, "dN": 0, "rY": 0, "rN": 0, "iY": 0, "iN": 0, "present": 0, "notVoting": 0}
    for m in rows:
        k = vkind(m.get("vote"))
        p = (m.get("party") or "").upper()
        p = p.lower() if p in ("D", "R") else "i"
        if k in ("Y", "N"):
            t[p + k] += 1
        elif k == "P":
            t["present"] += 1
        elif k == "M":
            t["notVoting"] += 1
    return t


def nname(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


# ---------------------------------------------------------------- members cache
def fetch_members(cg):
    log("Fetching member list for Congress", cg)
    items, _ = paged("/member/congress/" + str(cg), lambda j: find_list(j, "members"),
                     lambda m: m.get("bioguideId"), max_pages=10)
    out = {}
    for m in items:
        mid = m.get("bioguideId")
        if not mid:
            continue
        terms = m.get("terms") or {}
        tl = terms.get("item") if isinstance(terms, dict) else terms
        chamber = ""
        if isinstance(tl, list) and tl and isinstance(tl[-1], dict):
            chamber = tl[-1].get("chamber", "") or ""
        st = m.get("state", "") or ""
        out[mid] = [m.get("district"), m.get("name", "") or "", STATES.get(st, st), chamber]
    return out


def get_members(cg, force=False):
    if cg in MEMBERS and not force:
        return MEMBERS[cg]
    path = os.path.join(OUT, "members", "cache-%d.json" % cg)
    cached = None if force else load_json(path, None)
    if not cached or cached.get("v") != 2:
        cached = {"v": 2, "members": fetch_members(cg)}
        save_json(path, cached)
    MEMBERS[cg] = cached["members"]
    return MEMBERS[cg]


def district_of(members, bio, state):
    info = members.get(bio)
    d = info[0] if info else None
    if d in (None, 0, "0", "") and state in ATLARGE:
        return 1
    return d


def senator_id(members, state, first, last):
    """Senate XML has no Bioguide ID, so match on state + name against the member list."""
    L = nname(last)
    c = [i for i, v in members.items()
         if v[2] == state and nname((v[1] or "").split(",")[0]) == L]
    if len(c) > 1:
        s = [i for i in c if (members[i][3] or "").lower().startswith("sen")]
        c = s or c
    if len(c) > 1:
        f = nname(first)
        s = [i for i in c
             if nname(((members[i][1] or "").split(",")[-1].strip().split(" ") or [""])[0]) == f]
        c = s or c
    return c[0] if len(c) == 1 else "SEN-%s-%s" % (state, nname(last))


# ---------------------------------------------------------------- legacy migration
def migrate_legacy():
    """Moves votes saved by the first version (data/index.json, data/votes/*) into data/house/<congress>/."""
    old_idx = os.path.join(OUT, "index.json")
    if not os.path.exists(old_idx):
        return
    entries = load_json(old_idx, [])
    log("Migrating", len(entries), "saved votes to the new folder layout")
    by = {}
    for e in entries:
        cg = e["congress"]
        old_file = os.path.join(OUT, "votes", "%d-%d-%d.json" % (cg, e["session"], e["roll"]))
        d = load_json(old_file, None)
        if not d:
            continue
        d["chamber"] = "house"
        p = vote_path("house", cg, e["session"], e["roll"])
        save_json(p, d)
        e2 = dict(e)
        e2["chamber"] = "house"
        e2["file"] = web(p)
        if "dY" not in e2:
            e2.update(tally(d["members"]))
        by.setdefault(cg, []).append(e2)
        try:
            os.remove(old_file)
        except OSError:
            pass
    for cg, lst in by.items():
        have = {(x["session"], x["roll"]) for x in load_index("house", cg)}
        idx = load_index("house", cg) + [x for x in lst if (x["session"], x["roll"]) not in have]
        save_index("house", cg, idx)
    for stale in [old_idx] + [os.path.join(OUT, f) for f in os.listdir(OUT)
                              if re.match(r"members-\d+\.json$", f)]:
        try:
            os.remove(stale)
        except OSError:
            pass
    try:
        os.rmdir(os.path.join(OUT, "votes"))
    except OSError:
        pass


# ---------------------------------------------------------------- House
def process_house(cg, max_new):
    members = get_members(cg)
    index = load_index("house", cg)
    have = {(e["session"], e["roll"]) for e in index}
    refreshed = False
    added = 0
    for ss in (1, 2):
        log("House", cg, "session", ss, "- listing votes")
        votes, _ = paged("/house-vote/%d/%d" % (cg, ss), lambda j: find_list(j, "houseRollCallVotes"),
                         lambda x: x.get("rollCallNumber"))
        log("  found", len(votes), "votes")
        for v in sorted(votes, key=lambda x: x.get("rollCallNumber") or 0):
            roll = v.get("rollCallNumber")
            if roll is None or (ss, roll) in have:
                continue
            if added >= max_new:
                break
            log("Vote", ss, roll)
            detail, first = paged("/house-vote/%d/%d/%d/members" % (cg, ss, roll),
                                  lambda j: ((j or {}).get("houseRollCallVoteMemberVotes") or {}).get("results", []),
                                  lambda m: m["bioguideID"], single=True)
            if not detail:
                continue  # not published yet; try again next run
            R = (first or {}).get("houseRollCallVoteMemberVotes", {})
            if any(m["bioguideID"] not in members for m in detail) and not refreshed:
                members = get_members(cg, force=True)
                refreshed = True
            rows = []
            for m in detail:
                rows.append({"id": m["bioguideID"], "first": m.get("firstName", ""),
                             "last": m.get("lastName", ""), "party": m.get("voteParty", ""),
                             "state": m["voteState"],
                             "district": district_of(members, m["bioguideID"], m["voteState"]),
                             "vote": m.get("voteCast", "")})
            bill = ((R.get("legislationType") or "") + " " + str(R.get("legislationNumber") or "")).strip()
            meta = {"chamber": "house", "congress": cg, "session": ss, "roll": roll,
                    "date": R.get("startDate") or v.get("startDate"),
                    "question": R.get("voteQuestion") or v.get("voteQuestion"),
                    "result": R.get("result") or v.get("result"),
                    "bill": bill, "billUrl": R.get("legislationUrl"),
                    "amendment": ((R.get("amendmentType") or "") + " " + str(R.get("amendmentNumber") or "")).strip(),
                    "amendmentAuthor": R.get("amendmentAuthor")}
            p = vote_path("house", cg, ss, roll)
            save_json(p, dict(meta, members=rows))
            yes = sum(vkind(r["vote"]) == "Y" for r in rows)
            no = sum(vkind(r["vote"]) == "N" for r in rows)
            index.append(dict(meta, yes=yes, no=no, **tally(rows), file=web(p)))
            have.add((ss, roll))
            added += 1
            log("saved", web(p))
    for e in index:  # fill in party counts for votes saved by an older version
        if "dY" not in e:
            d = load_json(e.get("file", ""), None)
            if d:
                e.update(tally(d["members"]))
    if index:
        save_index("house", cg, index)
    note("House %d: added %d new vote(s); %d total" % (cg, added, len(index)))


# ---------------------------------------------------------------- Senate
def norm_bill(s):
    """'H.R. 5371' -> 'HR 5371', 'S.J.Res. 132' -> 'SJRES 132', 'S.Amdt. 12' -> 'SAMDT 12'."""
    s = (s or "").strip()
    m = re.match(r"^([A-Za-z.\s]+?)\s*(\d[\w\-]*)$", s)
    if not m:
        return s
    return re.sub(r"[.\s]", "", m.group(1)).upper() + " " + m.group(2)


def parse_senate_date(s):
    s = re.sub(r"\s+", " ", (s or "").strip())
    for fmt in ("%B %d, %Y, %I:%M %p", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(s, fmt).isoformat()
        except ValueError:
            pass
    return s


def senate_root(raw):
    """Parse a senate.gov roll call page. senate.gov sometimes answers with an HTML 'not available' page
    instead of a 404, and a few vote files contain stray characters; reject the first and repair the second."""
    head = raw.lstrip()[:200].lower()
    if not (head.startswith(b"<?xml") or b"<roll_call_vote" in head):
        raise ValueError("senate.gov returned a page that is not vote data (the vote is probably not available)")
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        pass
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)", "&amp;", text)
    text = re.sub(r"^<\?xml[^>]*\?>", "", text.lstrip())
    return ET.fromstring(text)


def parse_senate(raw, cg, ss):
    root = senate_root(raw)

    def t(path, node=None):
        el = (node if node is not None else root).find(path)
        return (el.text or "").strip() if el is not None and el.text else ""

    roll = int(t("vote_number"))
    dtype, dnum, dname = t("document/document_type"), t("document/document_number"), t("document/document_name")
    if dtype == "PN" and dnum:
        bill = "PN" + dnum
    elif dname:
        bill = norm_bill(dname)
    elif dtype and dnum:
        bill = norm_bill(dtype + " " + dnum)
    else:
        bill = ""
    amend = norm_bill(t("amendment/amendment_number")) if t("amendment/amendment_number") else ""
    rows = []
    for m in root.findall("members/member"):
        rows.append({"first": t("first_name", m), "last": t("last_name", m),
                     "party": t("party", m), "state": t("state", m),
                     "vote": t("vote_cast", m), "district": None})
    tie = ""
    if t("tie_breaker/by_whom"):
        tie = (t("tie_breaker/by_whom") + ": " + t("tie_breaker/tie_breaker_vote")).strip(": ")
    meta = {"chamber": "senate", "congress": cg, "session": ss, "roll": roll,
            "date": parse_senate_date(t("vote_date")),
            "question": t("question") or t("vote_question_text"),
            "title": t("vote_title"), "result": t("vote_result"),
            "bill": bill, "billUrl": None, "amendment": amend, "amendmentAuthor": None,
            "majority": t("majority_requirement"), "tieBreaker": tie}
    return meta, rows


def process_senate(cg, max_new):
    members = get_members(cg)
    index = load_index("senate", cg)
    refreshed = False
    added = 0
    for ss in (1, 2):
        have = {e["roll"] for e in index if e["session"] == ss}
        top = max(have) if have else 0
        missing = [n for n in range(1, top + 1) if n not in have]
        log("Senate", cg, "session", ss, "- checking for new votes after", top)

        def numbers():
            for n in missing:
                yield n
            n = top
            while True:
                n += 1
                yield n

        misses = 0  # consecutive unavailable votes past the last known one
        for n in numbers():
            if added >= max_new:
                break
            url = "%s/vote%d%d/vote_%d_%d_%05d.xml" % (SENATE_BASE, cg, ss, cg, ss, n)
            raw = fetch_bytes(url)
            bad = None
            if raw is None:
                bad = "not found"
            else:
                try:
                    meta, rows = parse_senate(raw, cg, ss)
                    if not rows:
                        bad = "no member votes listed yet"
                except Exception as ex:
                    bad = "could not read (%s)" % ex
            if bad:
                if n <= top:
                    continue  # a gap that is still not available; it is retried on later runs
                misses += 1
                if raw is not None:
                    log("  Senate vote %d: %s" % (n, bad))
                if misses >= 3:
                    break  # three in a row past the last vote: we have reached the end
                continue
            misses = 0
            if any(r["state"] not in {v[2] for v in members.values()} for r in rows) and not refreshed:
                members = get_members(cg, force=True)
                refreshed = True
            for r in rows:
                r["id"] = senator_id(members, r["state"], r["first"], r["last"])
            p = vote_path("senate", cg, ss, meta["roll"])
            save_json(p, dict(meta, members=rows))
            yes = sum(vkind(r["vote"]) == "Y" for r in rows)
            no = sum(vkind(r["vote"]) == "N" for r in rows)
            index.append(dict(meta, yes=yes, no=no, **tally(rows), file=web(p)))
            added += 1
            log("saved", web(p))
    if index:
        save_index("senate", cg, index)
    note("Senate %d: added %d new vote(s); %d total" % (cg, added, len(index)))


# ---------------------------------------------------------------- member statistics
def vote_codes(rows):
    """One character per member for this roll call.
    y/n   voted Yea/Nay with the majority of their own party
    Y/N   voted Yea/Nay against the majority of their own party
    a/b   Yea/Nay, but there is no party majority to compare with (tie, or independent)
    p     Present      m   Not Voting      -   not on the roll"""
    cnt = {"D": [0, 0], "R": [0, 0]}
    for m in rows:
        p = (m.get("party") or "").upper()
        k = vkind(m.get("vote"))
        if p in cnt and k in ("Y", "N"):
            cnt[p][0 if k == "Y" else 1] += 1
    maj = {p: ("Y" if c[0] > c[1] else "N" if c[1] > c[0] else None) for p, c in cnt.items()}
    out = {}
    for m in rows:
        p = (m.get("party") or "").upper()
        k = vkind(m.get("vote"))
        if k in ("Y", "N"):
            mj = maj.get(p)
            if mj:
                out[m["id"]] = k.lower() if k == mj else k
            else:
                out[m["id"]] = "a" if k == "Y" else "b"
        elif k == "P":
            out[m["id"]] = "p"
        elif k == "M":
            out[m["id"]] = "m"
        else:
            out[m["id"]] = "-"
    return out


def stats_of(s):
    return {"eligible": len(s) - s.count("-"), "missed": s.count("m"), "present": s.count("p"),
            "against": s.count("Y") + s.count("N"),
            "partyVotes": sum(s.count(c) for c in "yYnN")}


def maverick_of(s, votes, byroll, party):
    """Maverick score: on every roll call where the member voted against the majority of their own party,
    add (party members with the majority) minus (party members against). Independents have no party majority."""
    if party not in ("D", "R"):
        return 0
    a, b = ("dY", "dN") if party == "D" else ("rY", "rN")
    total = 0
    for i, ch in enumerate(s):
        if ch in "YN" and i < len(votes):
            v = byroll.get((votes[i][0], votes[i][1]))
            if v:
                total += abs(v.get(a, 0) - v.get(b, 0))
    return total


def touch_directory(dirmap, chamber, cg, rows):
    for m in rows:
        e = dirmap.setdefault(m["id"], {"id": m["id"], "c": {}})
        e["first"], e["last"] = m.get("first", ""), m.get("last", "")
        e["party"], e["state"], e["district"], e["chamber"] = m.get("party", ""), m.get("state", ""), m.get("district"), chamber
        c = e["c"].setdefault(str(cg), {})
        c.update({"chamber": chamber, "party": m.get("party", ""), "state": m.get("state", ""),
                  "district": m.get("district")})


def update_matrix(chamber, cg, dirmap):
    index = load_index(chamber, cg)
    if not index:
        return
    mpath = os.path.join(cdir(chamber, cg), "matrix.json")
    mx = load_json(mpath, {"votes": [], "members": {}})
    done = {(v[0], v[1]) for v in mx["votes"]}
    new = sorted((e for e in index if (e["session"], e["roll"]) not in done),
                 key=lambda e: (e["session"], e["roll"]))
    for e in new:
        d = load_json(vote_path(chamber, cg, e["session"], e["roll"]), None)
        if not d:
            continue
        rows = d["members"]
        codes = vote_codes(rows)
        n = len(mx["votes"])
        for mid in codes:
            mx["members"].setdefault(mid, "-" * n)
        for mid in mx["members"]:
            mx["members"][mid] += codes.get(mid, "-")
        mx["votes"].append([e["session"], e["roll"]])
        touch_directory(dirmap, chamber, cg, rows)
    if new:
        save_json(mpath, mx)
    byroll = {(e["session"], e["roll"]): e for e in index}
    for mid, s in mx["members"].items():
        e = dirmap.get(mid)
        if e is not None:
            slot = e["c"].setdefault(str(cg), {"chamber": chamber})
            st = stats_of(s)
            st["maverick"] = maverick_of(s, mx["votes"], byroll, slot.get("party") or e.get("party"))
            slot.update(st)
    note("%s %d: statistics (missed votes, party-line votes, Maverick scores) cover %d votes and %d members" % (chamber.title(), cg, len(mx["votes"]), len(mx["members"])))


def write_congresses():
    found = {}
    for ch in ("house", "senate"):
        d = os.path.join(OUT, ch)
        if os.path.isdir(d):
            for name in os.listdir(d):
                if name.isdigit() and os.path.exists(os.path.join(d, name, "index.json")):
                    found.setdefault(int(name), []).append(ch)
    lst = [{"congress": c, "years": years_of(c), "chambers": [x for x in ("house", "senate") if x in chs]}
           for c, chs in sorted(found.items(), reverse=True)]
    if lst:
        save_json(os.path.join(OUT, "congresses.json"), {"latest": lst[0]["congress"], "congresses": lst})


# ---------------------------------------------------------------- sponsored / cosponsored legislation

def tracked_congresses(cgs):
    """Congresses worth keeping bill data for: those being updated this run plus every Congress already on the site."""
    keep = set(cgs)
    j = load_json(os.path.join(OUT, "congresses.json"), None) or {}
    for x in j.get("congresses", []):
        try:
            keep.add(int(x["congress"]))
        except (KeyError, ValueError, TypeError):
            pass
    return sorted(keep)


FINAL_DAYS = 14


def congress_end(cg):
    """The Congress ends at noon on January 3 of the year after its second session."""
    return datetime.date(1789 + 2 * cg, 1, 3)


def slot_asof(old, cg):
    """The date this member's data for Congress cg was last read, or None if it never was."""
    if not old:
        return None
    slot = (old.get("congresses") or {}).get(str(cg))
    a = slot.get("asof") if slot else None
    if not a and (slot or cg in (old.get("tracked") or [])):
        a = old.get("updated")  # files saved by older versions of this script
    try:
        return datetime.date.fromisoformat(a) if a else None
    except (TypeError, ValueError):
        return None


def slot_final(asof, cg):
    """Data read at least FINAL_DAYS after a Congress ended can no longer change, so it is never read again."""
    return asof is not None and (asof - congress_end(cg)).days >= FINAL_DAYS


def legislation_due(e, old, keep, today, refresh_days, force):
    """None when this member needs nothing, else (rank, oldest date): rank 0 = a Congress never read,
    1 = a Congress being forced, 2 = a Congress still open to change and read more than refresh_days ago."""
    rank, oldest = None, today
    for cg in keep:
        if str(cg) not in e["c"]:
            continue
        a = slot_asof(old, cg)
        if a is None:
            r, a = 0, datetime.date.min
        elif cg in force and a < today:
            r = 1
        elif not slot_final(a, cg) and (today - a).days >= refresh_days:
            r = 2
        else:
            continue
        rank = r if rank is None else min(rank, r)
        oldest = min(oldest, a)
    return None if rank is None else (rank, oldest)


def update_legislation(dirmap, keep, budget, refresh_days, force=()):
    """One pair of requests per member returns their whole history, so a member is only read when one of their
    Congresses has never been read, is being forced (a manual backfill run), or is still open to change and stale."""
    if budget <= 0:
        return
    today = datetime.date.today()
    force = set(force)
    ids = [e for e in dirmap.values() if BIOGUIDE.match(e["id"]) and any(str(c) in e["c"] for c in keep)]
    due = []
    for e in ids:
        old = load_json(os.path.join(OUT, "legislation", e["id"] + ".json"), None)
        d = legislation_due(e, old, keep, today, refresh_days, force)
        if d:
            due.append((d, e))
    due.sort(key=lambda t: (t[0], t[1]["id"]))
    todo = [e for _, e in due]
    by = {0: 0, 1: 0, 2: 0}
    for d, _ in due:
        by[d[0]] += 1
    log("Legislation: %d member(s) in the Congresses kept; %d need requests (%d never read for some Congress, %d forced, %d refreshes of Congresses still open)."
        % (len(ids), len(todo), by[0], by[1], by[2]))
    log("  Congresses whose data was read at least %d days after they ended are final and are skipped%s."
        % (FINAL_DAYS, " (forcing: " + ", ".join(map(str, sorted(force))) + ")" if force else ""))
    log("  Each member needs requests for sponsored and cosponsored bills; this run may use up to %d requests, so at most %d member(s) can be done (each needs at least 2 requests)." % (budget, min(len(todo), budget // 2)))
    start = REQS
    done = 0
    tot = {"sponsored": 0, "cosponsored": 0}
    for e in todo:
        if REQS - start >= budget:
            log("  Legislation: request budget reached (%d); the remaining %d member(s) will be done on later runs." % (budget, len(todo) - done))
            break
        f = os.path.join(OUT, "legislation", e["id"] + ".json")
        prev = load_json(f, None) or {}
        mine = [cg for cg in keep if str(cg) in e["c"]]
        data = {"updated": today.isoformat(),
                "tracked": sorted(set(prev.get("tracked") or []) | set(mine)),
                "congresses": dict(prev.get("congresses") or {})}
        for cg in mine:
            data["congresses"][str(cg)] = {"sponsored": [], "cosponsored": [], "asof": today.isoformat()}
        try:
            for kind, k in (("sponsored", "sponsoredLegislation"), ("cosponsored", "cosponsoredLegislation")):
                items, _ = paged("/member/%s/%s-legislation" % (e["id"], kind),
                                 lambda j, k=k: find_list(j, k),
                                 lambda x: (x.get("congress"), x.get("type"), x.get("number")),
                                 max_pages=40, quiet=True)
                tot[kind] += len(items)
                for x in items:
                    cg = x.get("congress")
                    if cg in mine:
                        slot = data["congresses"][str(cg)]
                        item = {"type": x.get("type"), "number": str(x.get("number")),
                                "title": (x.get("title") or "")[:300],
                                "date": x.get("introducedDate")}
                        la = x.get("latestAction") or {}
                        lm = LAW_RE.search(la.get("text") or "")
                        if lm:
                            item["law"] = lm.group(2)
                            item["lawDate"] = la.get("actionDate")
                        slot[kind].append(item)
        except Exception as ex:
            log("  legislation failed for", e["id"], ex)
            continue
        for slot in data["congresses"].values():
            for kind in ("sponsored", "cosponsored"):
                slot[kind].sort(key=lambda x: x.get("date") or "", reverse=True)
        save_json(f, data)
        done += 1
        if done % 10 == 0 or done == len(todo):
            log("  Legislation progress: %d of %d member(s) refreshed | %d sponsored and %d cosponsored bills read | %d of %d requests used | elapsed %s"
                % (done, len(todo), tot["sponsored"], tot["cosponsored"], REQS - start, budget, elapsed()))
    note("Legislation: read sponsored and cosponsored bills for %d member(s) using %d requests (%d sponsored and %d cosponsored bills read); %d still waiting"
         % (done, REQS - start, tot["sponsored"], tot["cosponsored"], len(todo) - done))


def apply_counts(dirmap, cgs):
    """Copy sponsored / cosponsored totals from each member's legislation file into the directory."""
    n = 0
    for e in dirmap.values():
        d = load_json(os.path.join(OUT, "legislation", e["id"] + ".json"), None)
        if not d:
            continue
        for cg in cgs:
            c = e["c"].get(str(cg))
            slot = d.get("congresses", {}).get(str(cg))
            if c is None:
                continue
            c["sponsored"] = len(slot["sponsored"]) if slot else 0
            c["cosponsored"] = len(slot["cosponsored"]) if slot else 0
            n += 1
    log("Legislation counts saved for %d member/Congress pair(s)." % n)
# ---------------------------------------------------------------- CRS bill summaries (bulk)
SUMCHUNK = 250


def plain_text(html_text, limit=3000):
    """CRS summaries come as HTML; keep paragraphs and list items as plain text lines."""
    t = re.sub(r"(?i)</(p|li|div|h\d)>|<br\s*/?>", "\n", html_text or "")
    t = re.sub(r"(?s)<[^>]+>", "", t)
    t = html.unescape(t)
    t = "\n".join(re.sub(r"[ \t ]+", " ", ln).strip() for ln in t.split("\n"))
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return t


def snippet(text, limit=150):
    """The first sentence or so of a summary, for the bill lists."""
    t = re.sub(r"\s+", " ", text or "").strip()
    t = re.sub(r"^(This (bill|joint resolution|resolution|concurrent resolution)|The bill)\s+", "", t)
    t = t[:1].upper() + t[1:]
    if len(t) <= limit:
        return t
    cut = t[:limit]
    m = re.search(r"^(.{40,}?[.;])\s", t[:limit + 60])
    if m and len(m.group(1)) <= limit + 40:
        return m.group(1)
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"


def update_summaries(cgs, budget):
    """data/summaries/{cg}/{TYPE}-{k}.json (250 bill numbers per file): {number: {t, d, a, u}} holding the newest CRS
    summary of each bill. The bulk /summaries/{congress} endpoint returns 250 summaries per request, so a whole Congress
    takes a few dozen requests. It only returns recent items unless fromDateTime is given, so each Congress remembers
    how far it has read (meta.json 'through') and carries on from there."""
    if budget <= 0:
        return
    start_reqs = REQS
    for cg in sorted(cgs, reverse=True):
        base = os.path.join(OUT, "summaries", str(cg))
        meta = load_json(os.path.join(base, "meta.json"), {})
        through = meta.get("through")
        today = datetime.date.today()
        if through and (today - congress_end(cg)).days >= FINAL_DAYS and meta.get("final"):
            continue
        frm = through or datetime.date(1789 + 2 * (cg - 1), 1, 1).isoformat() + "T00:00:00Z"
        to = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        offset, got, chunks, last, finished = 0, 0, {}, through, False
        while REQS - start_reqs < budget:
            try:
                j = get("/summaries/%d" % cg, fromDateTime=frm, toDateTime=to, sort="updateDate asc", offset=offset)
            except Exception as ex:
                log("  summaries for Congress %d failed: %s" % (cg, ex))
                break
            page = find_list(j, "summaries")
            for x in page:
                b = x.get("bill") or {}
                ty, n = (b.get("type") or "").upper(), str(b.get("number") or "")
                if not ty or not n.isdigit():
                    continue
                key = (ty, (int(n) - 1) // SUMCHUNK)
                if key not in chunks:
                    chunks[key] = load_json(os.path.join(base, "%s-%d.json" % key), {})
                row = {"t": plain_text(x.get("text")), "d": x.get("actionDate") or "", "a": x.get("actionDesc") or "",
                       "u": x.get("updateDate") or ""}
                if row["t"]:
                    old = chunks[key].get(n)
                    if not old or (row["u"] or "") >= (old.get("u") or ""):
                        chunks[key][n] = row
                        got += 1
                if x.get("updateDate"):
                    last = x["updateDate"]
            if len(page) < 250:
                finished = True
                break
            offset += 250
        for (ty, k), rows in chunks.items():
            save_json(os.path.join(base, "%s-%d.json" % (ty, k)), rows)
        if last:
            meta = {"through": last, "updated": today.isoformat(), "complete": finished}
            meta["final"] = bool(finished and (today - congress_end(cg)).days >= FINAL_DAYS)
            save_json(os.path.join(base, "meta.json"), meta)
        note("Summaries: Congress %d, %d summary(ies) saved%s" % (cg, got, "" if finished else " (more on the next run)"))
        if REQS - start_reqs >= budget:
            log("  Summaries: request budget reached (%d); the rest will be read on later runs." % budget)
            break


def summary_snippets(cg, rows):
    """Add the first-sentence snippet 'm' to bill-list rows from the saved summaries."""
    cache = {}
    for r in rows:
        key = (r["y"], (r["n"] - 1) // SUMCHUNK)
        if key not in cache:
            cache[key] = load_json(os.path.join(OUT, "summaries", str(cg), "%s-%d.json" % key), {})
        s = cache[key].get(str(r["n"]))
        if s and s.get("t"):
            r["m"] = snippet(s["t"])


# ---------------------------------------------------------------- bill lists (built from members' sponsored/cosponsored files)
BILLTITLES = {}
CHUNK = 2000


def pcode_of(p):
    p = (p or "").upper()
    return p if p in ("D", "R") else "I"


def build_bills(dirmap, cgs):
    """data/billlist/{cg}/: every bill any tracked member sponsored, with cosponsor counts by party.
    recent.json (newest 400), {TYPE}-{k}.json chunks of 2000 bill numbers, and meta.json."""
    for cg in cgs:
        bills, cos, cosids = {}, {}, {}
        for e in dirmap.values():
            c = e["c"].get(str(cg))
            if c is None:
                continue
            d = load_json(os.path.join(OUT, "legislation", e["id"] + ".json"), None)
            slot = ((d or {}).get("congresses") or {}).get(str(cg))
            if not slot:
                continue
            p = pcode_of(c.get("party") or e.get("party"))
            for x in slot.get("sponsored", []):
                if not x.get("type") or not str(x.get("number") or "").isdigit():
                    continue
                key = x["type"] + " " + str(x["number"])
                r = {"y": x["type"], "n": int(x["number"]), "t": x.get("title") or "", "d": x.get("date") or "", "s": e["id"], "sp": p}
                if x.get("law"):
                    r["l"] = x["law"]
                    r["ld"] = x.get("lawDate") or ""
                bills[key] = r
            for x in slot.get("cosponsored", []):
                key = (x.get("type") or "") + " " + str(x.get("number"))
                cc = cos.setdefault(key, [0, 0, 0])
                cc[{"D": 0, "R": 1}.get(p, 2)] += 1
                cosids.setdefault(key, []).append([e["id"], x.get("date") or ""])
        for key, cc in cos.items():
            r = bills.get(key)
            if r:
                for i, nm in enumerate(("cd", "cr", "ci")):
                    if cc[i]:
                        r[nm] = cc[i]
        BILLTITLES[cg] = {k: r["t"] for k, r in bills.items() if r["t"]}
        base = os.path.join(OUT, "billlist", str(cg))
        groups = {}
        for r in bills.values():
            groups.setdefault((r["y"], (r["n"] - 1) // CHUNK), []).append(r)
        chunks = {}
        summary_snippets(cg, bills.values())
        for (ty, k), rows in groups.items():
            rows.sort(key=lambda r: r["n"])
            save_json(os.path.join(base, "%s-%d.json" % (ty, k)), rows)
            cmap = {str(r["n"]): cosids[r["y"] + " " + str(r["n"])] for r in rows if (r["y"] + " " + str(r["n"])) in cosids}
            if cmap:
                save_json(os.path.join(base, "cos-%s-%d.json" % (ty, k)), cmap)
            chunks.setdefault(ty, []).append(k)
        recent = sorted(bills.values(), key=lambda r: (r["d"], r["n"]), reverse=True)[:400]
        save_json(os.path.join(base, "recent.json"), recent)
        expected = None
        j = get("/bill/%d" % cg, limit=1)
        if j:
            expected = (j.get("pagination") or {}).get("count")
        save_json(os.path.join(base, "meta.json"), {
            "updated": datetime.date.today().isoformat(), "total": len(bills), "expected": expected,
            "chunks": {k: sorted(v) for k, v in chunks.items()}, "chunk": CHUNK})
        note("Bill list: Congress %d has %d bill(s) collected%s" % (cg, len(bills), " of %s" % expected if expected else ""))



# ---------------------------------------------------------------- bill and amendment titles
def split_bill(key):
    m = re.match(r"^([A-Za-z]+)\s+(\d[\w\-]*)$", (key or "").strip())
    return (m.group(1).lower(), m.group(2)) if m else (None, None)


def update_titles(cgs, budget):
    """data/bills/{cg}.json: title of every bill and the purpose of every amendment that a saved roll call refers to.
    Newest votes first; only items not already cached are requested (up to `budget` requests)."""
    if budget <= 0:
        note("Titles skipped (TITLE_BUDGET is 0)")
        return
    left = budget
    for cg in cgs:
        path = os.path.join(OUT, "bills", "%d.json" % cg)
        cache = load_json(path, {"bills": {}, "amendments": {}})
        cache.setdefault("bills", {})
        cache.setdefault("amendments", {})
        for k, t in (BILLTITLES.get(cg) or {}).items():
            if k not in cache["bills"] or not cache["bills"][k].get("t"):
                cache["bills"][k] = {"t": t[:400]}
        want_b, want_a = [], []
        for ch in ("house", "senate"):
            idx = load_json(os.path.join(OUT, ch, str(cg), "index.json"), [])
            for v in sorted(idx, key=lambda x: (x.get("date") or ""), reverse=True):
                b, a = (v.get("bill") or "").strip(), (v.get("amendment") or "").strip()
                if b and b not in cache["bills"] and b not in want_b:
                    want_b.append(b)
                if a and a not in cache["amendments"] and a not in want_a:
                    want_a.append(a)
        got = 0
        for key in want_a:
            if left <= 0:
                break
            t, n = split_bill(key)
            if not t:
                cache["amendments"][key] = {}
                continue
            left -= 1
            j = get("/amendment/%d/%s/%s" % (cg, t, n))
            am = (j or {}).get("amendment") or {}
            ab = am.get("amendedBill") or {}
            if j is None:
                cache["amendments"][key] = {}
            else:
                cache["amendments"][key] = {"p": (am.get("purpose") or am.get("description") or "")[:400],
                                            "to": ((ab.get("type") or "") + " " + str(ab.get("number") or "")).strip(),
                                            "tt": (ab.get("title") or "")[:300]}
            got += 1
        for key in want_b:
            if left <= 0:
                break
            t, n = split_bill(key)
            if not t:
                cache["bills"][key] = {}
                continue
            left -= 1
            j = get("/bill/%d/%s/%s" % (cg, t, n))
            if j is None:
                cache["bills"][key] = {}
            else:
                cache["bills"][key] = {"t": ((j.get("bill") or {}).get("title") or "")[:400]}
            got += 1
        save_json(path, cache)
        remaining = len([k for k in want_b if k not in cache["bills"]]) + len([k for k in want_a if k not in cache["amendments"]])
        note("Titles: Congress %d, %d looked up this run, %d still to look up" % (cg, got, remaining))



# ---------------------------------------------------------------- member contact details
LEGISLATORS = "https://unitedstates.github.io/congress-legislators/"


def update_contacts():
    """data/members/contact.json: official website, phone, contact form, office and social accounts of each sitting member,
    from the public congress-legislators project (two small files, so two requests in total)."""
    path = os.path.join(OUT, "members", "contact.json")
    old = load_json(path, {})
    if old.get("updated") == datetime.date.today().isoformat() and old.get("members"):
        log("Contact details were already saved today (%d members)." % len(old["members"]))
        return
    raw = fetch_bytes(LEGISLATORS + "legislators-current.json")
    if not raw:
        note("Contact details: could not download the current legislators file; keeping what was saved")
        return
    try:
        people = json.loads(raw.decode("utf-8"))
    except Exception as ex:
        note("Contact details: the legislators file could not be read (%s); keeping what was saved" % ex)
        return
    social = {}
    raw2 = fetch_bytes(LEGISLATORS + "legislators-social-media.json")
    if raw2:
        try:
            for s in json.loads(raw2.decode("utf-8")):
                b = (s.get("id") or {}).get("bioguide")
                if b:
                    social[b] = s.get("social") or {}
        except Exception as ex:
            log("  social media file could not be read:", ex)
    out = {}
    for p in people:
        b = (p.get("id") or {}).get("bioguide")
        terms = p.get("terms") or []
        if not b or not terms:
            continue
        t = terms[-1]
        row = {}
        for k, v in (("w", t.get("url")), ("p", t.get("phone")), ("f", t.get("contact_form")),
                     ("a", t.get("address")), ("o", t.get("office")), ("r", t.get("rss_url"))):
            if v:
                row[k] = str(v).strip()
        sc = social.get(b) or {}
        x = {k: str(sc[k]).strip() for k in ("twitter", "facebook", "youtube", "instagram") if sc.get(k)}
        if x:
            row["x"] = x
        if row:
            out[b] = row
    if out:
        save_json(path, {"updated": datetime.date.today().isoformat(), "members": out})
    note("Contact details: saved official website, phone and contact information for %d sitting member(s)" % len(out))


# ---------------------------------------------------------------- bills signed into law
def update_laws(cgs, run_cgs=None):
    """data/laws/{cg}.json: every public and private law of the Congress, from the Congress.gov law endpoint.
    Congresses outside this run are only fetched when they have no laws file yet."""
    for cg in cgs:
        if run_cgs is not None and cg not in run_cgs and os.path.exists(os.path.join(OUT, "laws", "%d.json" % cg)):
            continue
        laws = []
        for kind in ("pub", "priv"):
            try:
                items, _ = paged("/law/%d/%s" % (cg, kind), lambda j: find_list(j, "bills"),
                                 lambda x: (x.get("type"), x.get("number")), max_pages=30, quiet=True)
            except Exception as ex:
                log("  laws (%s) for Congress %d failed: %s" % (kind, cg, ex))
                continue
            for x in items:
                nums = [l.get("number") for l in (x.get("laws") or []) if l.get("number")]
                la = x.get("latestAction") or {}
                laws.append({"law": nums[0] if nums else "", "kind": kind, "type": x.get("type"),
                             "number": str(x.get("number")), "title": (x.get("title") or "")[:300],
                             "date": la.get("actionDate") or (x.get("updateDate") or "")[:10]})
        if laws:
            laws.sort(key=lambda l: (l["date"] or "", l["law"]))
            save_json(os.path.join(OUT, "laws", "%d.json" % cg), {"updated": datetime.date.today().isoformat(), "congress": cg, "laws": laws})
        note("Laws: Congress %d has %d public/private law(s) recorded" % (cg, len(laws)))


def write_status(cgs):
    save_json(os.path.join(OUT, "status.json"), {
        "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "congresses": cgs, "requests": REQS, "summary": SUMMARY})



def default_congresses(today=None, grace_days=21):
    """The current Congress, plus the previous one only until grace_days after the new Congress begins (Jan 3)."""
    today = today or datetime.date.today()
    cur = current_congress(today)
    start = datetime.date(1789 + 2 * (cur - 1), 1, 3)
    return [cur - 1, cur] if (today - start).days < grace_days else [cur]


# ---------------------------------------------------------------- main
def main():
    migrate_legacy()
    env = os.environ.get("CONGRESSES", "").strip()
    cur = current_congress()
    cgs = sorted(int(x) for x in env.split(",") if x.strip()) if env else default_congresses()
    max_new = int(os.environ.get("MAX_NEW", "400"))
    leg_budget = int(os.environ.get("LEG_BUDGET", "1200"))
    title_budget = int(os.environ.get("TITLE_BUDGET", "600"))
    dpath = os.path.join(OUT, "members", "directory.json")
    dirmap = {e["id"]: e for e in load_json(dpath, [])}

    plan = []
    for cg in cgs:
        plan.append("House %d: fetch new roll call votes and member lists (up to %d new votes)" % (cg, max_new))
        plan.append("Senate %d: fetch new roll call votes from senate.gov (up to %d new votes)" % (cg, max_new))
        plan.append("Congress %d: recompute member statistics (missed votes, votes against party, Maverick scores)" % cg)
    plan.append("Save the member directory and the list of Congresses")
    plan.append("Sponsored and cosponsored bills for members (up to %d requests)" % leg_budget if leg_budget > 0 else
                "Sponsored and cosponsored bills (skipped: LEG_BUDGET is 0)")
    plan.append("CRS bill summaries (bulk, 250 per request, up to %s requests)" % os.environ.get("SUMMARY_BUDGET", "80"))
    plan.append("Bill lists for the Bills tab (built from the sponsored/cosponsored files, 1 request per Congress)")
    plan.append("Bill and amendment titles for the votes (up to %d requests)" % title_budget)
    plan.append("Bills signed into law (public and private laws) for each Congress")
    plan.append("Member contact details (website, phone, contact form) from congress-legislators")
    plan.append("Save sponsored/cosponsored counts and the data status")
    STEP["of"] = len(plan)
    log("Congresses to update: " + ", ".join(str(c) for c in cgs))
    log("Tasks this run:")
    for i, t in enumerate(plan, 1):
        log("  %d. %s" % (i, t))

    for cg in cgs:
        step("House %d votes" % cg)
        process_house(cg, max_new)
        step("Senate %d votes" % cg)
        process_senate(cg, max_new)
        step("Member statistics for Congress %d" % cg)
        update_matrix("house", cg, dirmap)
        update_matrix("senate", cg, dirmap)
    step("Saving member directory and Congress list")
    save_json(dpath, sorted(dirmap.values(), key=lambda e: ((e.get("last") or "").lower(), (e.get("first") or "").lower())))
    write_congresses()
    log("Saved %d member(s)." % len(dirmap))
    keep = tracked_congresses(cgs)
    log("Bill data is kept for Congress(es): %s (this run updates %s)." % (", ".join(map(str, keep)), ", ".join(map(str, cgs))))
    step("Sponsored and cosponsored bills")
    force = cgs if (os.environ.get("FORCE_REFRESH", "").lower() in ("1", "true", "yes") and env) else []
    update_legislation(dirmap, keep, leg_budget, int(os.environ.get("LEG_REFRESH_DAYS", "5")), force)
    step("Bill summaries")
    update_summaries(keep, int(os.environ.get("SUMMARY_BUDGET", "80")))
    step("Bill lists")
    build_bills(dirmap, keep)
    step("Bill and amendment titles")
    update_titles(keep, title_budget)
    step("Bills signed into law")
    update_laws(keep, cgs)
    step("Member contact details")
    update_contacts()
    step("Saving legislation counts and status")
    apply_counts(dirmap, keep)
    save_json(dpath, sorted(dirmap.values(), key=lambda e: ((e.get("last") or "").lower(), (e.get("first") or "").lower())))
    write_status(cgs)
    log("")
    log("===== Summary (elapsed %s, %d API requests) =====" % (elapsed(), REQS))
    for line in SUMMARY:
        log("  " + line)
    log("Done.")


if __name__ == "__main__":
    if not os.environ.get("CONGRESS_API_KEY"):
        sys.exit("Set CONGRESS_API_KEY first.")
    main()
