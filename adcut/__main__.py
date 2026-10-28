"""CLI:  python -m adcut <command> ...

  shoots                       list shoots
  board <shoot>                every line's take stack + how many videos it makes
  match <shoot>                re-match takes against the current script
  render <shoot> [N ...]       render videos (default: all not skipped)
  serve [--port 8770]          start the ad editor
  password ["new password"]    set the web-link password (none = make one up); see login.txt
"""
import argparse


def main():
    ap = argparse.ArgumentParser(prog="adcut", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("shoots")
    p = sub.add_parser("board"); p.add_argument("shoot")
    p = sub.add_parser("match"); p.add_argument("shoot")
    p = sub.add_parser("render"); p.add_argument("shoot"); p.add_argument("videos", nargs="*", type=int)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8770)
    p = sub.add_parser("password"); p.add_argument("pw", nargs="?")
    a = ap.parse_args()
    from adkit import resources
    resources.install()  # share the PC politely with PlayOn's real-time recordings (supercut/resources.py)

    from . import store
    if a.cmd == "shoots":
        for r in store.shoots():
            print(f"{r['id']:<32} {r['lines']} lines  {r['videos']} videos  {r['title']}")
    elif a.cmd == "board":
        s = store.load(a.shoot)
        v = store.videos(s)
        for i, line in enumerate(s["script"], 1):
            good, bad = store.stack(s, line["id"]), store.stack(s, line["id"], False)
            print(f"LINE {i}{' (optional)' if line['optional'] else ''}: {line['text']}")
            for k, t in enumerate(good, 1):
                print(f"  take {k:<2} [{t['in']:.2f}-{t['out']:.2f}] {t['status']:<6} {t['text']}")
            for t in bad:
                print(f"  reject  [{t['in']:.2f}-{t['out']:.2f}] {t['status']:<10} {'; '.join(t['flags'])}: {t['text']}")
        print(f"\n{v['count']} videos")
    elif a.cmd == "match":
        from .takes import match
        s = store.update(a.shoot, match)
        print(f"{store.videos(s)['count']} videos")
    elif a.cmd == "render":
        from .render import render_and_record
        s = store.load(a.shoot)
        nums = a.videos or [v["n"] for v in store.videos(s)["videos"] if not v["skip"]]
        for n in nums:
            print(render_and_record(a.shoot, n, print))
    elif a.cmd == "password":
        from . import auth
        auth.set_password(a.pw)
        print(f"Web password set. It's written in {auth.NOTE}")
    elif a.cmd == "serve":
        import os
        import uvicorn
        os.environ["ADCUT_PORT"] = str(a.port)
        print(f"Ad Factory: http://127.0.0.1:{a.port}")
        uvicorn.run("adcut.server:app", host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
