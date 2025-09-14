#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AGENT TOOL — MIRA AI V1 (Offline)
- topup   : tambah kuota daripada token (lokal JSON ledger)
- status  : semak baki
- gen     : jana key (tolak 1 kuota) — output bill/resit
- history : senarai rekod (terbaru di atas) + export CSV

Nota:
- VERIFY_SECRET mesti sama dengan admin semasa mint token.
- Semua operasi 100% offline (fail ledger tempatan).
"""

from future import annotations
import argparse, base64, datetime as dt, hashlib, hmac, json, os, re, sys, zlib, threading, csv

# ===== Konfigurasi =====
SALT_KEY = "MIRA_AI_V1_SALT"          # MESTI sama dgn EA
VERIFY_SECRET = "MIRA AI V1 TOKEN"     # MESTI sama dgn ADMIN
LEDGER_PATH = os.getenv("MIRA_AGENT_LEDGER", "agent_ledger.json")
CSV_PATH    = os.getenv("MIRA_AGENT_CSV",    "history.csv")

# Plan + tempoh (hari)
PLAN_DAYS = {
    "1M": 30, "2M": 60, "3M": 90,
    "P1M": 30, "P2M": 60, "P3M": 90
}
# Plan + harga RM (untuk paparan bill)
PLAN_PRICE = {
    "1M": 95, "2M": 180, "3M": 250,
    "P1M": 75, "P2M": 159, "P3M": 239
}

MAP_FWD = str.maketrans("0123456789", "QWERTYUIOP")
BANNER  = "="*58 + "\n" + "SKYONE.TECH = MIRA AI V1 TOKEN".center(58) + "\n" + "="*58
_lock   = threading.Lock()

# ===== Util =====
def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def verify_topup_token(token: str) -> dict:
    try:
        data_b64, sig_b64 = token.strip().split(".")
    except ValueError:
        raise ValueError("Token format tidak sah.")
    data = b64d(data_b64); sig = b64d(sig_b64)
    exp  = hmac.new(VERIFY_SECRET.encode(), data, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, exp):
        raise ValueError("Token tidak sah (signature mismatch).")
    payload = json.loads(data)
    for k in ("tid","amount","plans","agent","ver"):
        if k not in payload:
            raise ValueError("Token payload tidak lengkap.")
    if payload["ver"] != 1:
        raise ValueError("Versi token tidak disokong.")
    if int(payload["amount"]) not in [10,20,30,50,75,100]:
        raise ValueError("Jumlah topup tidak dibenarkan.")
    for p in payload["plans"]:
        if p not in PLAN_DAYS:
            raise ValueError(f"Plan tidak sah: {p}")
    return payload

def to_base36(n:int)->str:
    chars="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"; n=abs(int(n))
    if n==0: return "0"; s=""
    while n: n,r=divmod(n,36); s=chars[r]+s
    return s

def owner_code_fixed()->str:
    text="SKYONE.TECH"
    crc=zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF
    chars="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    s=""; val=crc
    while val: val,r=divmod(val,36); s=chars[r]+s
    return s[-4:].rjust(4,"0")

def djb2(s:str)->int:
    h=5381
    for ch in s:
        h=((h<<5)+h)+ord(ch); h&=0x7fffffff
    return h

def enc_digits(s:str)->str:
    if not re.fullmatch(r"[0-9]+", s):
        raise ValueError("enc_digits hanya digit 0-9.")
    return s.translate(MAP_FWD)

def make_key(acc_no:int, plan:str, start_date:dt.date|None=None)->str:
    plan=plan.upper()
    if plan not in PLAN_DAYS:
        raise ValueError(f"Plan dibenarkan: {list(PLAN_DAYS.keys())}")
    if start_date is None:
        start_date=dt.date.today()
    exp_date=start_date+dt.timedelta(days=PLAN_DAYS[plan])
    exp_str=exp_date.strftime("%Y%m%d")
    base=f"{enc_digits(str(acc_no))}-{owner_code_fixed()}-{plan}-{enc_digits(exp_str)}"
    chk=djb2(base+"|"+SALT_KEY)%1_000_000
    return f"{base}-{chk:06d}"

# ===== Ledger =====
def load_ledger()->dict|None:
    if not os.path.exists(LEDGER_PATH): return None
    with open(LEDGER_PATH,"r",encoding="utf-8") as f:
        return json.load(f)

def save_ledger(ledger:dict)->None:
    tmp=LEDGER_PATH+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(ledger,f,ensure_ascii=False,indent=2)
    os.replace(tmp,LEDGER_PATH)

def ensure_ledger(agent_id:str|None=None, plans:list[str]|None=None)->dict:
    led=load_ledger()
    if led is None:
        now=dt.datetime.now().isoformat(timespec="seconds")
        led={"agent_id":agent_id or "AGENT_UNSET","balance":0,
             "allowed_plans":sorted(list(set(plans or list(PLAN_DAYS.keys())))),
             "used_token_ids":[], "history":[],
             "updated_at":now, "created_at":now}
        save_ledger(led)
        _export_history_csv(led)  # inisialisasi CSV kosong
    return led

# ===== CSV Export (auto setiap perubahan) =====
def _export_history_csv(ledger: dict, newest_first: bool = True) -> None:
    hist = ledger.get("history", [])
    # Terbaru di atas
    hist_sorted = sorted(hist, key=lambda x: x.get("ts",""), reverse=True if newest_first else False)

    rows = [["ts","action","acc","plan","amount","plans","ref","balance_after"]]
    for r in hist_sorted:
        if r["action"] == "TOPUP":
            rows.append([
                r["ts"], "TOPUP", "", "", r.get("amount",""),
                ",".join(r.get("plans",[])), r.get("token_id",""),
                r.get("balance_after","")
            ])
        else:  # GEN
            rows.append([
                r["ts"], "GEN", r.get("acc",""), r.get("plan",""),
                "", "", r.get("key_tail",""), r.get("balance_after","")
            ])
    try:
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
    except Exception as e:
        print("Amaran: gagal tulis CSV:", e)

# ===== Ops =====
def op_topup(token:str, force_agent:str|None=None)->dict:
    with _lock:
        payload=verify_topup_token(token)
        tid=payload["tid"]; amount=int(payload["amount"])
        plans=sorted(list(set(payload["plans"]))); agent_from_token=payload["agent"]

        led=load_ledger()
        if led is None:
            led=ensure_ledger(force_agent or agent_from_token, plans)
        else:
            if force_agent and led["agent_id"]!=force_agent:
                raise ValueError("Ledger milik agent lain.")
            led["allowed_plans"]=sorted(list(set(led["allowed_plans"])|set(plans)))
        if tid in led["used_token_ids"]:
            raise ValueError("Token ini sudah digunakan pada mesin ini.")

        led["balance"]+=amount
        led["used_token_ids"].append(tid)
        rec={"ts":dt.datetime.now().isoformat(timespec="seconds"),
             "action":"TOPUP","token_id":tid,"amount":amount,"plans":plans,
             "agent_claim":agent_from_token, "balance_after": led["balance"]}
        led["history"].append(rec); led["updated_at"]=rec["ts"]; save_ledger(led)
        _export_history_csv(led)   # auto CSV
        return {"agent_id":led["agent_id"],"added":amount,"balance":led["balance"],"plans":led["allowed_plans"]}

def op_gen(acc:int, plan:str, start:str|None)->dict:
    with _lock:
        led=load_ledger()
        if led is None: raise ValueError("Ledger tiada. Sila topup token dahulu.")
        plan=plan.upper()
        if plan not in led["allowed_plans"]:
            raise ValueError(f"Plan {plan} tidak dibenarkan. Allowed: {led['allowed_plans']}")
        if led["balance"]<=0:
            raise ValueError("Kuota habis. Sila topup token baharu.")
        start_date=None
        if start:
            y,m,d=map(int,start.split("-")); start_date=dt.date(y,m,d)
        key=make_key(acc,plan,start_date)
        led["balance"]-=1
        rec={"ts":dt.datetime.now().isoformat(timespec="seconds"),
             "action":"GEN","acc":acc,"plan":plan,"key_tail":key[-10:],
             "balance_after": led["balance"]}
        led["history"].append(rec); led["updated_at"]=rec["ts"]; save_ledger(led)
        _export_history_csv(led)   # auto CSV
        return {"key":key,"balance_left":led["balance"],"plan":plan,"agent_id":"SKYONE.TECH"}

def op_status()->dict:
    led=load_ledger()
    if led is None: return {"exists":False}
    return {"exists":True,"agent_id":led["agent_id"],"balance":led["balance"],
            "allowed_plans":led["allowed_plans"],"updated_at":led["updated_at"]}

def op_history(kind:str="all", export:str|None=None)->None:
    led=load_ledger()
    if led is None:
        print("Ledger tiada. Sila topup dahulu."); return
    hist=sorted(led.get("history",[]), key=lambda x: x.get("ts",""), reverse=True)
    if kind!="all":
        hist=[h for h in hist if h["action"].lower()==kind.lower()]

    print("\n"+BANNER+"\n")
    print(f"Agent : {led['agent_id']}  | Baki: {led['balance']}  | Plans: {','.join(led['allowed_plans'])}")
    print("-"*58)
    if not hist:
        print("(tiada rekod)")
    else:
        for r in hist:
            if r["action"]=="TOPUP":
                print(f"{r['ts']}  TOPUP  +{r['amount']}  plans={','.join(r['plans'])}  token={r['token_id']}  bal={r.get('balance_after','')}")
            elif r["action"]=="GEN":
                print(f"{r['ts']}  GEN    acc={r['acc']}  plan={r['plan']}  key_tail={r['key_tail']}  bal={r.get('balance_after','')}")
    print("\n"+BANNER+"\n")

    if export:
        # tulis semua ikut susunan terbaru
        rows=[["ts","action","acc","plan","amount","plans","ref","balance_after"]]
        for r in hist:
            if r["action"]=="TOPUP":
                rows.append([r["ts"],"TOPUP","", "", r.get("amount",""), ",".join(r.get("plans",[])), r.get("token_id",""), r.get("balance_after","")])
            else:
                rows.append([r["ts"],"GEN", r.get("acc",""), r.get("plan",""), "", "", r.get("key_tail",""), r.get("balance_after","")])
        try:
            with open(export,"w",newline="",encoding="utf-8") as f:
                csv.writer(f).writerows(rows)
            print(f"✅ Export CSV: {export}")
        except Exception as e:
            print("Amaran: gagal export CSV:", e)

# ===== CLI =====
def main():
    ap=argparse.ArgumentParser(description="AGENT: Offline Topup Keygen (bill style + history CSV)")
    sub=ap.add_subparsers(dest="cmd", required=True)

    t=sub.add_parser("topup", help="Masuk token topup (tambah kuota)")
    t.add_argument("--token", required=True)
    t.add_argument("--agent-id", default=None)

    g=sub.add_parser("gen", help="Jana key (tolak 1 kuota)")
    g.add_argument("--acc", type=int, required=True)
    g.add_argument("--plan", type=str, choices=list(PLAN_DAYS.keys()), required=True)
    g.add_argument("--start", type=str, default=None)

    s=sub.add_parser("status", help="Semak baki & info ledger")

    h=sub.add_parser("history", help="Senarai rekod (terbaru di atas) + export CSV")
    h.add_argument("--kind", choices=["all","topup","gen"], default="all")
    h.add_argument("--export", type=str, default=None, help="Export ke CSV (cth: history_all.csv)")

    args=ap.parse_args()

    if args.cmd=="topup":
        r=op_topup(args.token, args.agent_id)
        print("\n"+BANNER+"\n")
        print("Topup berjaya.")
        print(f"agent : {r['agent_id']}")
        print(f"tambah: {r['added']}")
        print(f"baki  : {r['balance']}")
        print(f"plans : {','.join(r['plans'])}")
        print("\n"+BANNER+"\n")
        return

    if args.cmd=="gen":
        r=op_gen(args.acc, args.plan, args.start)
        harga = PLAN_PRICE.get(r["plan"], 0)
        print("\n"+BANNER+"\n")
        print("MIRA AI V1 — KEY:\n")
        print(r["key"])
        print(f"\nagent : {r['agent_id']}")
        print(f"PLAN  : {r['plan']}")
        print(f"RM    : {harga}")
        print("\n"+BANNER+"\n")
        return

    if args.cmd=="status":
        st=op_status()
        if not st["exists"]:
            print("Ledger belum wujud. Sila topup dahulu.")
        else:
            print("\n"+BANNER+"\n")
            print(f"agent : {st['agent_id']} | baki: {st['balance']} | plan: {','.join(st['allowed_plans'])} | update: {st['updated_at']}")
            print("\n"+BANNER+"\n")
        return

if args.cmd=="history":
        op_history(args.kind, args.export)
        return

if name=="main":
    try:
        main()
    except Exception as e:
        print("Ralat:", e, file=sys.stderr); sys.exit(1)
