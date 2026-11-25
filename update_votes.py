#!/usr/bin/env python3
"""Saves House roll call votes from the Congress.gov API as permanent JSON files.

Run it on a schedule. Each run adds only votes it has not saved yet:
  data/index.json                      list of all saved votes (newest first)
  data/votes/119-2-327.json            one file per vote, district numbers included
  data/members-119.json                bioguideID -> district cache

Environment variables:
  CONGRESS_API_KEY   (required)
  CONGRESS           default 119
  SESSIONS           default "1,2"
  OUT_DIR            default "data"
  MAX_NEW            default 200 (max new votes saved per run; the rest come next run)
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

BASE = "https://api.congress.gov/v3"
ATLARGE = {"AK", "DE", "ND", "SD", "VT", "WY", "DC"}
YES, NO = {"yea", "aye", "yes"}, {"nay", "no"}


def get(path, **params):
    q = {"format": "json", "limit": 250, "api_key": os.environ["CONGRESS_API_KEY"]}
    q.update(params)
    url = BASE + path + "?" + urllib.parse.urlencode(q)
    for attempt in range(4):
        try:
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


def paged(path, finder):
    items, offset = [], 0
    while True:
        j = get(path, offset=offset)
        page = finder(j) if j else []
        items += page
        if len(page) < 250:
            return items
        offset += 250


def find_list(j, preferred):
    if preferred in j and isinstance(j[preferred], list):
        return j[preferred]
    for v in j.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def fetch_members(cg):
    out = {}
    for m in paged("/member/congress/" + str(cg), lambda j: find_list(j, "members")):
        if m.get("bioguideId"):
            out[m["bioguideId"]] = m.get("district")
    return out


def main():
    cg = int(os.environ.get("CONGRESS", "119"))
    sessions = [s.strip() for s in os.environ.get("SESSIONS", "1,2").split(",") if s.strip()]
    out_dir = os.environ.get("OUT_DIR", "data")
    max_new = int(os.environ.get("MAX_NEW", "200"))

    index_path = os.path.join(out_dir, "index.json")
    index = load_json(index_path, [])
    have = {(v["congress"], v["session"], v["roll"]) for v in index}

    mem_path = os.path.join(out_dir, "members-%d.json" % cg)
    members = load_json(mem_path, None)
    if members is None:
        members = fetch_members(cg)
        save_json(mem_path, members)
    refreshed = False

    added = 0
    for ss in sessions:
        votes = paged("/house-vote/%d/%s" % (cg, ss), lambda j: find_list(j, "houseRollCallVotes"))
        for v in sorted(votes, key=lambda x: x.get("rollCallNumber") or 0):
            roll = v.get("rollCallNumber")
            if roll is None or (cg, int(ss), roll) in have:
                continue
            if added >= max_new:
                break
            detail = paged("/house-vote/%d/%s/%d/members" % (cg, int(ss), roll),
                           lambda j: ((j or {}).get("houseRollCallVoteMemberVotes") or {}).get("results", []))
            if not detail:
                continue  # not published yet; try again next run
            head = get("/house-vote/%d/%s/%d/members" % (cg, int(ss), roll), limit=1)
            R = (head or {}).get("houseRollCallVoteMemberVotes", {})
            if any(m["bioguideID"] not in members for m in detail) and not refreshed:
                members = fetch_members(cg)
                save_json(mem_path, members)
                refreshed = True
            rows, yes, no = [], 0, 0
            for m in detail:
                d = members.get(m["bioguideID"])
                if d is None and m["voteState"] in ATLARGE:
                    d = 1
                cast = m.get("voteCast", "")
                yes += cast.lower() in YES
                no += cast.lower() in NO
                rows.append({"id": m["bioguideID"], "first": m.get("firstName", ""),
                             "last": m.get("lastName", ""), "party": m.get("voteParty", ""),
                             "state": m["voteState"], "district": d, "vote": cast})
            bill = ((R.get("legislationType") or "") + " " + str(R.get("legislationNumber") or "")).strip()
            meta = {"congress": cg, "session": int(ss), "roll": roll,
                    "date": R.get("startDate") or v.get("startDate"),
                    "question": R.get("voteQuestion") or v.get("voteQuestion"),
                    "result": R.get("result") or v.get("result"),
                    "bill": bill, "billUrl": R.get("legislationUrl")}
            fname = "votes/%d-%d-%d.json" % (cg, int(ss), roll)
            save_json(os.path.join(out_dir, fname), dict(meta, members=rows))
            index.append(dict(meta, yes=yes, no=no, file="data/" + fname if out_dir == "data" else fname))
            have.add((cg, int(ss), roll))
            added += 1
            print("saved", fname, flush=True)
    index.sort(key=lambda x: (x.get("date") or "", x["roll"]), reverse=True)
    save_json(index_path, index)
    print("added %d new vote(s); %d total" % (added, len(index)))


if __name__ == "__main__":
    if not os.environ.get("CONGRESS_API_KEY"):
        sys.exit("Set CONGRESS_API_KEY first.")
    main()
