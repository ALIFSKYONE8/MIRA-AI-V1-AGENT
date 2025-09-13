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
             "agent_claim":agent_from_token}
        led["history"].append(rec); led["updated_at"]=rec["ts"]; save_ledger(led)
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
             "action":"GEN","acc":acc,"plan":plan,"key_tail":key[-10:]}
        led["history"].append(rec); led["updated_at"]=rec["ts"]; save_ledger(led)
        return {"key":key,"balance_left":led["balance"],"plan":plan,"agent_id":"SKYONE.TECH"}

def op_status()->dict:
    led=load_ledger()
    if led is None: return {"exists":False}
    return {"exists":True,"agent_id":led["agent_id"],"balance":led["balance"],
            "allowed_plans":led["allowed_plans"],"updated_at":led["updated_at"]}

# ===== CLI =====
def main():
    ap=argparse.ArgumentParser(description="AGENT: Offline Topup Keygen (bill style)")
    sub=ap.add_subparsers(dest="cmd", required=True)

    t=sub.add_parser("topup", help="Masuk token topup (tambah kuota)")
    t.add_argument("--token", required=True)
    t.add_argument("--agent-id", default=None)

    g=sub.add_parser("gen", help="Jana key (tolak 1 kuota)")
    g.add_argument("--acc", type=int, required=True)
    g.add_argument("--plan", type=str, choices=list(PLAN_DAYS.keys()), required=True)
    g.add_argument("--start", type=str, default=None)

    s=sub.add_parser("status", help="Semak baki & info ledger")

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

if name=="main":
    try:
        main()
    except Exception as e:
        print("Ralat:", e, file=sys.stderr); sys.exit(1)
